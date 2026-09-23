"""Descomposición de la respuesta de Agent B en aserciones verificables.

Es el equivalente determinista del primer paso de *faithfulness*: en lugar de
pedirle a un LLM que extraiga las afirmaciones de la respuesta, se derivan de
las entidades que ya extrajo el Pilar 1, de la acción clasificada y de los
resultados de los controles. Cada aserción se verifica contra el contexto
normativo con aritmética y palabras clave, de modo que el puntaje se puede
recalcular a mano.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any

from .extraccion import ROL_PORCENTAJE_RESPUESTA, ROL_RESPUESTA
from .modelos import ACCION_DESCONOCIDA, EntradaFidelidad, EstadoControl

if TYPE_CHECKING:
    from .config import FidelidadConfig

FAMILIA_NUMERICA = "numerica"
FAMILIA_MOTIVO = "motivo"
FAMILIA_ACCION = "accion"
FAMILIA_ESTADO = "estado"
FAMILIA_REQUISITO = "requisito"


class EstadoAsercion(str, Enum):
    SOPORTADA = "SOPORTADA"
    NO_SOPORTADA = "NO_SOPORTADA"
    NO_VERIFICABLE = "NO_VERIFICABLE"


@dataclass
class Asercion:
    familia: str
    texto: str
    estado: EstadoAsercion
    motivo: str = ""
    evidencia: dict[str, Any] = field(default_factory=dict)

    @property
    def verificable(self) -> bool:
        return self.estado is not EstadoAsercion.NO_VERIFICABLE

    @property
    def soportada(self) -> bool:
        return self.estado is EstadoAsercion.SOPORTADA


def _cerca(valor: float, referencia: float, tolerancia: float) -> bool:
    return abs(valor - referencia) <= tolerancia * max(abs(referencia), 1.0)


def _montos_contexto(entrada: EntradaFidelidad) -> list[float]:
    return [v for rol, vals in entrada.extraccion.montos.items() if rol != ROL_RESPUESTA for v in vals]


def _limites_contexto(entrada: EntradaFidelidad) -> list[float]:
    return [
        v
        for rol, vals in entrada.extraccion.montos.items()
        if rol.startswith("limite_")
        for v in vals
    ]


def _porcentajes_contexto(entrada: EntradaFidelidad) -> list[float]:
    return [
        v
        for rol, vals in entrada.extraccion.porcentajes.items()
        if rol != ROL_PORCENTAJE_RESPUESTA
        for v in vals
    ]


def _derivaciones(monto: float, porcentajes: list[float], activas: list[str]) -> list[float]:
    """Montos que se pueden derivar legítimamente de otro monto del contexto."""
    valores = []
    for pct in porcentajes:
        if "neto_deducible" in activas:
            valores.append(monto * (1 - pct))
        if "valor_deducible" in activas:
            valores.append(monto * pct)
    return valores


# ------------------------------------------------------------------ familias


def _aserciones_numericas(entrada: EntradaFidelidad, cfg: FidelidadConfig) -> list[Asercion]:
    ext = entrada.extraccion
    tol = cfg.tolerancia_relativa
    contexto = _montos_contexto(entrada)
    limites = _limites_contexto(entrada)
    pcts_contexto = _porcentajes_contexto(entrada)
    aserciones: list[Asercion] = []

    for monto in ext.montos.get(ROL_RESPUESTA, []):
        referencias = contexto + _derivaciones_de(contexto, pcts_contexto, cfg)
        if any(_cerca(monto, ref, tol) for ref in referencias):
            motivo = "coincide con una cifra del contexto o con una derivación admisible"
            estado = EstadoAsercion.SOPORTADA
        elif limites and any(monto <= lim * (1 + tol) for lim in limites):
            motivo = f"dentro de un límite del contexto ({min(l for l in limites if monto <= l * (1 + tol)):,.0f})"
            estado = EstadoAsercion.SOPORTADA
        else:
            motivo = "el contexto no respalda esta cifra" if contexto else "el contexto no contiene cifras"
            estado = EstadoAsercion.NO_SOPORTADA
        aserciones.append(
            Asercion(
                FAMILIA_NUMERICA,
                f"monto ${monto:,.0f}",
                estado,
                motivo,
                {"valor": monto, "limites_contexto": limites, "montos_contexto": contexto},
            )
        )

    for pct in ext.porcentajes.get(ROL_PORCENTAJE_RESPUESTA, []):
        soportada = any(_cerca(pct, ref, tol) for ref in pcts_contexto)
        aserciones.append(
            Asercion(
                FAMILIA_NUMERICA,
                f"porcentaje {pct:.0%}",
                EstadoAsercion.SOPORTADA if soportada else EstadoAsercion.NO_SOPORTADA,
                "coincide con un porcentaje del contexto"
                if soportada
                else "el contexto no menciona este porcentaje",
                {"valor": pct, "porcentajes_contexto": pcts_contexto},
            )
        )
    return aserciones


def _derivaciones_de(montos: list[float], pcts: list[float], cfg: FidelidadConfig) -> list[float]:
    derivados: list[float] = []
    for monto in montos:
        derivados.extend(_derivaciones(monto, pcts, cfg.derivaciones))
    return derivados


def _asercion_accion(entrada: EntradaFidelidad, cfg: FidelidadConfig) -> list[Asercion]:
    if entrada.accion.tipo == ACCION_DESCONOCIDA:
        return []
    incumplidos = [r.id for r in entrada.resultados if r.estado is EstadoControl.NO_CUMPLE]
    soportada = not incumplidos
    return [
        Asercion(
            FAMILIA_ACCION,
            f"acción {entrada.accion.tipo}",
            EstadoAsercion.SOPORTADA if soportada else EstadoAsercion.NO_SOPORTADA,
            "compatible con las directivas del contexto"
            if soportada
            else f"contradice las directivas verificadas por {', '.join(incumplidos)}",
            {"accion": entrada.accion.tipo, "controles_incumplidos": incumplidos},
        )
    ]


def _asercion_estado(entrada: EntradaFidelidad, cfg: FidelidadConfig) -> list[Asercion]:
    afirmaciones = cfg.claves_estado.buscar(entrada.respuesta_n)
    if not afirmaciones:
        return []
    alertas = cfg.claves_directiva_restrictiva.buscar(entrada.contexto_n)
    return [
        Asercion(
            FAMILIA_ESTADO,
            f"afirma '{afirmaciones[0]}'",
            EstadoAsercion.NO_SOPORTADA if alertas else EstadoAsercion.SOPORTADA,
            f"el contexto reporta {', '.join(alertas)}" if alertas else "el contexto no la contradice",
            {"afirmaciones": afirmaciones, "alertas_contexto": alertas},
        )
    ]


def _asercion_motivo(entrada: EntradaFidelidad, cfg: FidelidadConfig) -> list[Asercion]:
    if entrada.accion.tipo not in cfg.acciones_restrictivas:
        return []
    motivos = cfg.claves_motivo_alegado.buscar(entrada.respuesta_n)
    if not motivos:
        return []
    directivas = cfg.claves_directiva_restrictiva.buscar(entrada.contexto_n)
    return [
        Asercion(
            FAMILIA_MOTIVO,
            f"alega '{motivos[0]}'",
            EstadoAsercion.SOPORTADA if directivas else EstadoAsercion.NO_SOPORTADA,
            f"el contexto respalda la causa ({', '.join(directivas)})"
            if directivas
            else "el contexto no reporta ninguna causa restrictiva",
            {"motivos": motivos, "directivas_contexto": directivas},
        )
    ]


def _asercion_requisito(entrada: EntradaFidelidad, cfg: FidelidadConfig) -> list[Asercion]:
    requisitos = entrada.extraccion.requisitos
    if not requisitos or entrada.accion.tipo not in cfg.acciones_de_aprobacion:
        return []
    requisito = requisitos[0]
    palabras = [p for p in requisito.split() if len(p) >= 4]
    cumplido = bool(palabras) and all(p in entrada.respuesta_n for p in palabras)
    return [
        Asercion(
            FAMILIA_REQUISITO,
            f"requisito '{requisito}'",
            EstadoAsercion.SOPORTADA if cumplido else EstadoAsercion.NO_SOPORTADA,
            "la respuesta evidencia su cumplimiento"
            if cumplido
            else "el contexto lo exige y la respuesta no lo menciona",
            {"requisito": requisito},
        )
    ]


def _aserciones_no_verificables(entrada: EntradaFidelidad, cfg: FidelidadConfig) -> list[Asercion]:
    edad = entrada.extraccion.edad_cliente
    if edad is None or "edad_cliente" not in cfg.familias_no_verificables:
        return []
    return [
        Asercion(
            "edad_cliente",
            f"edad declarada {edad} años",
            EstadoAsercion.NO_VERIFICABLE,
            "dato del asegurado que el contexto no contiene",
            {"valor": edad},
        )
    ]


_FAMILIAS = {
    FAMILIA_NUMERICA: _aserciones_numericas,
    FAMILIA_MOTIVO: _asercion_motivo,
    FAMILIA_ACCION: _asercion_accion,
    FAMILIA_ESTADO: _asercion_estado,
    FAMILIA_REQUISITO: _asercion_requisito,
}


def extraer_aserciones(entrada: EntradaFidelidad, cfg: FidelidadConfig) -> list[Asercion]:
    """Todas las aserciones del caso, en el orden de `familias_activas`."""
    aserciones: list[Asercion] = []
    for familia in cfg.familias_activas:
        generador = _FAMILIAS.get(familia)
        if generador:
            aserciones.extend(generador(entrada, cfg))
    aserciones.extend(_aserciones_no_verificables(entrada, cfg))
    return aserciones
