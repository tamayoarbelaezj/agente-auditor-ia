"""Confianza del auditor y similitud texto a texto (señales de apoyo).

Dos utilidades pensadas para la demostración en vivo y para el reporte, que no
alteran el veredicto ni el Índice de Fidelidad Analítica:

- ``confianza_decision``: **cuánta evidencia tuvo Agent A para emitir su
  veredicto**. No es la confianza de un LLM: no tenemos los *logprobs* de
  Agent B ni se consulta modelo alguno. Es un promedio ponderado de señales
  observables (acción reconocida, controles concluyentes, cobertura de
  evidencia, aserciones verificables y coherencia entre señales), así que es
  determinista, se recalcula a mano y se puede auditar factor por factor.
- ``similitud_semantica``: coseno de frecuencias entre el contexto normativo y
  la respuesta del agente, con la misma tokenización que el componente T del
  índice. Solo librería estándar.
"""

from __future__ import annotations

import logging
from collections import Counter
from typing import Any

from .config import Reglas
from .modelos import ACCION_DESCONOCIDA, EstadoControl, Veredicto
from .normalizacion import normalizar
from .texto import coseno_tf, tokenizar

log = logging.getLogger(__name__)

# ------------------------------------------------------------------ confianza

PESOS_CONFIANZA = {
    "accion_identificada": 0.20,
    "controles_concluyentes": 0.25,
    "cobertura_evidencia": 0.15,
    "aserciones_verificables": 0.15,
    "consistencia_senales": 0.25,
}
ASERCIONES_PARA_MAXIMO = 3
PENALIZACION_POR_ADVERTENCIA = 0.05
MAX_PENALIZACION_ADVERTENCIAS = 0.15
SENALES_DIVERGENTES = 0.30

UMBRAL_BANDA_ALTA = 0.80
UMBRAL_BANDA_MEDIA = 0.55


def _banda(valor: float, cobertura_suficiente: bool = True) -> str:
    """Banda de confianza; sin evidencia contrastable nunca llega a 'alta'.

    Declarar confianza alta mientras se admite que la respuesta no aportó nada
    verificable sería contradictorio: el tope a 'media' mantiene coherente lo
    que el número dice y lo que la explicación reconoce.
    """
    if valor >= UMBRAL_BANDA_ALTA and cobertura_suficiente:
        return "alta"
    return "media" if valor >= UMBRAL_BANDA_MEDIA else "baja"


def _senal_controles(veredicto: Veredicto) -> tuple[float, int, int]:
    """Proporción de controles que aplicaron y llegaron a una conclusión."""
    aplicables = [r for r in veredicto.resultados if r.aplica]
    concluyentes = [
        r for r in aplicables if r.estado in (EstadoControl.CUMPLE, EstadoControl.NO_CUMPLE)
    ]
    if not aplicables:
        return 0.0, 0, 0
    return len(concluyentes) / len(aplicables), len(concluyentes), len(aplicables)


def _senal_consistencia(veredicto: Veredicto, reglas: Reglas) -> tuple[float, bool, bool]:
    """1.0 si controles e índice apuntan al mismo lado; 0.30 si divergen."""
    hay_hallazgos = any(r.es_hallazgo for r in veredicto.resultados)
    indice_bajo = veredicto.indice < reglas.fidelidad.umbral_revision
    coherente = hay_hallazgos == indice_bajo
    return (1.0 if coherente else SENALES_DIVERGENTES), hay_hallazgos, indice_bajo


def _aserciones_verificables(veredicto: Veredicto) -> int:
    familias = veredicto.fidelidad.get("anclaje_por_familia", {})
    return sum(int(datos.get("verificables", 0)) for datos in familias.values())


def _explicacion(
    banda: str, valor: float, senales: dict[str, float], detalle: dict[str, Any]
) -> str:
    fuertes = [n for n, s in senales.items() if s >= 0.99]
    debiles = sorted((s, n) for n, s in senales.items() if s < 0.99)
    motivos = {
        "accion_identificada": f"la acción de Agent B no se pudo identificar ({detalle['accion']})",
        "controles_concluyentes": (
            f"solo {detalle['concluyentes']} de {detalle['aplicables']} controles aplicables "
            "llegaron a una conclusión"
        ),
        "cobertura_evidencia": "la respuesta no aporta aserciones verificables independientes",
        "aserciones_verificables": (
            f"hay {detalle['verificables']} aserción(es) verificable(s), menos de las "
            f"{ASERCIONES_PARA_MAXIMO} deseables"
        ),
        "consistencia_senales": (
            "los controles y el índice de fidelidad apuntan en direcciones distintas"
        ),
    }
    # Primero lo que sí sustenta el veredicto y después lo que falta: leído en
    # vivo, empezar por la carencia hace sonar débil a una confianza alta.
    base = (
        f"Confianza {banda} ({valor:.2f}): {detalle['concluyentes']} de {detalle['aplicables']} "
        f"controles concluyentes y {len(fuertes)} de {len(senales)} señales completas"
    )
    if debiles:
        faltantes = "; ".join(motivos[n] for _, n in debiles[:2])
        base += f". Queda por resolver: {faltantes}."
    else:
        base += f", con acción {detalle['accion']} identificada y señales coherentes."
    if detalle["advertencias"]:
        base += f" Hay {detalle['advertencias']} advertencia(s) de extracción que la reducen."
    return base


def confianza_decision(veredicto: Veredicto, reglas: Reglas) -> dict[str, Any]:
    """Cuánta evidencia respalda el veredicto del auditor, en [0, 1].

    No mide la seguridad de ningún modelo generativo: mide la calidad de la
    evidencia disponible para auditar (acción reconocible, controles que
    concluyeron, aserciones contrastables y coherencia entre señales). Por eso
    es reproducible y cada factor se puede sustentar ante el Comité.

    ``factores`` es aditivo: sus aportes suman el valor devuelto (antes de
    acotarlo a [0, 1]), de modo que el puntaje se recalcula a mano.
    """
    accion = veredicto.accion.tipo if veredicto.accion else ACCION_DESCONOCIDA
    ratio_controles, concluyentes, aplicables = _senal_controles(veredicto)
    verificables = _aserciones_verificables(veredicto)
    cobertura = veredicto.fidelidad.get("cobertura_evidencia", "insuficiente")
    consistencia, hay_hallazgos, indice_bajo = _senal_consistencia(veredicto, reglas)

    senales = {
        "accion_identificada": 0.0 if accion == ACCION_DESCONOCIDA else 1.0,
        "controles_concluyentes": ratio_controles,
        "cobertura_evidencia": 1.0 if cobertura == "suficiente" else 0.0,
        "aserciones_verificables": min(verificables, ASERCIONES_PARA_MAXIMO) / ASERCIONES_PARA_MAXIMO,
        "consistencia_senales": consistencia,
    }
    factores = {nombre: round(PESOS_CONFIANZA[nombre] * senal, 4) for nombre, senal in senales.items()}

    advertencias = len(veredicto.errores)
    if advertencias:
        castigo = min(advertencias * PENALIZACION_POR_ADVERTENCIA, MAX_PENALIZACION_ADVERTENCIAS)
        factores["ajuste_por_advertencias"] = -round(castigo, 4)

    valor = round(max(0.0, min(1.0, sum(factores.values()))), 4)
    banda = _banda(valor, cobertura == "suficiente")
    detalle = {
        "accion": accion,
        "concluyentes": concluyentes,
        "aplicables": aplicables,
        "verificables": verificables,
        "advertencias": advertencias,
        "hay_hallazgos": hay_hallazgos,
        "indice_bajo": indice_bajo,
    }
    return {
        "valor": valor,
        "banda": banda,
        "factores": factores,
        "explicacion": _explicacion(banda, valor, senales, detalle),
    }


# ------------------------------------------------------------------ similitud

MAX_TOKENS_COMUNES = 8

_ADVERTENCIA_INVERSA = (
    "En este dataset la similitud léxica correlaciona de forma inversa con la fidelidad "
    "(el caso 3, el peor, es el de mayor solapamiento), así que indica anclaje temático, "
    "nunca que la decisión sea correcta."
)


def _tokens_comunes(a: Counter[str], b: Counter[str]) -> list[str]:
    comunes = a.keys() & b.keys()
    return [t for _, t in sorted(((-(a[t] + b[t]), t) for t in comunes))][:MAX_TOKENS_COMUNES]


def similitud_semantica(contexto: str, respuesta: str, reglas: Reglas) -> dict[str, Any]:
    """Coseno entre el contexto normativo y la respuesta de Agent B, en [0, 1].

    Usa frecuencias de término (``backend="tf"``) con la misma tokenización y
    stopwords que el componente T del índice, de modo que el número que se ve
    en la demostración es el mismo que entra en la métrica. Sin dependencias:
    determinista, sin red y sin modelo cargado.
    """
    cfg = reglas.fidelidad
    tokens_ctx = tokenizar(normalizar(contexto), cfg.stopwords, cfg.minimo_caracteres_token)
    tokens_rsp = tokenizar(normalizar(respuesta), cfg.stopwords, cfg.minimo_caracteres_token)
    valor = round(coseno_tf(tokens_ctx, tokens_rsp), 4)
    return {
        "valor": valor,
        "backend": "tf",
        "detalle": (
            f"Coseno de frecuencias: {valor:.0%} de solapamiento léxico entre contexto y "
            f"respuesta, calculado con la librería estándar. {_ADVERTENCIA_INVERSA}"
        ),
        "tokens_comunes": _tokens_comunes(tokens_ctx, tokens_rsp),
    }
