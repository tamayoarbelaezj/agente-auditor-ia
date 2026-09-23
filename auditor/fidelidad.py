"""Índice de Fidelidad Analítica (IFA).

    IFA = ( w_C·C + w_A·A + w_T·T ) · (1 − P)

- **C** cumplimiento normativo: controles del Pilar 1 ponderados por severidad.
- **A** anclaje factual: aserciones soportadas / aserciones verificables, la
  definición de *faithfulness* implementada de forma determinista.
- **T** cobertura temática: coseno de frecuencias, saturado y con peso bajo.
- **P** penalización multiplicativa por contradicciones irrecuperables.

El motor solo depende del protocolo ``EvaluadorFidelidad``; ``provisional`` se
conserva como línea base para comparar.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from .aserciones import Asercion, EstadoAsercion, extraer_aserciones
from .config import FidelidadConfig, Reglas
from .modelos import EntradaFidelidad, EstadoControl, ResultadoControl
from .texto import coseno_tf, tokenizar

COBERTURA_SUFICIENTE = "suficiente"
COBERTURA_INSUFICIENTE = "insuficiente"


@dataclass
class PuntajeFidelidad:
    valor: float
    componentes: dict[str, float | None] = field(default_factory=dict)
    pesos_efectivos: dict[str, float] = field(default_factory=dict)
    anclaje_por_familia: dict[str, dict[str, Any]] = field(default_factory=dict)
    aserciones: list[dict[str, Any]] = field(default_factory=list)
    penalizaciones: dict[str, float] = field(default_factory=dict)
    cobertura_evidencia: str = COBERTURA_SUFICIENTE

    @property
    def evidencia_insuficiente(self) -> bool:
        return self.cobertura_evidencia == COBERTURA_INSUFICIENTE


class EvaluadorFidelidad(Protocol):
    nombre: str

    def puntuar(self, entrada: EntradaFidelidad) -> PuntajeFidelidad:
        """Devuelve el puntaje en [0, 1]; 1 = decisión totalmente fiel al contexto."""
        ...


def _cumplimiento(reglas: Reglas, resultados: list[ResultadoControl]) -> float:
    """C: proporción de controles cumplidos, ponderada por severidad."""
    aplicables = [r for r in resultados if r.aplica]
    total = sum(reglas.peso(r.severidad) for r in aplicables)
    if total == 0:
        return 1.0
    cumplidos = sum(
        reglas.peso(r.severidad) for r in aplicables if r.estado is EstadoControl.CUMPLE
    )
    return cumplidos / total


class EvaluadorProvisional:
    """Línea base del Pilar 1: solo cumplimiento normativo (I = C)."""

    nombre = "provisional"

    def __init__(self, reglas: Reglas) -> None:
        self.reglas = reglas

    def puntuar(self, entrada: EntradaFidelidad) -> PuntajeFidelidad:
        cumplimiento = _cumplimiento(self.reglas, entrada.resultados)
        return PuntajeFidelidad(
            valor=round(cumplimiento, 2),
            componentes={"C": round(cumplimiento, 4)},
            pesos_efectivos={"cumplimiento": 1.0},
        )


class EvaluadorSemantico:
    """Cumplimiento + anclaje factual + cobertura temática, con penalización."""

    nombre = "semantico"

    def __init__(self, reglas: Reglas) -> None:
        self.reglas = reglas
        self.cfg: FidelidadConfig = reglas.fidelidad

    # ------------------------------------------------------------ componentes

    def _anclaje(self, aserciones: list[Asercion]) -> tuple[float | None, dict[str, dict[str, Any]]]:
        verificables = [a for a in aserciones if a.verificable]
        por_familia: dict[str, dict[str, Any]] = {}
        for a in verificables:
            fam = por_familia.setdefault(a.familia, {"soportadas": 0, "verificables": 0})
            fam["verificables"] += 1
            fam["soportadas"] += int(a.soportada)
        for fam in por_familia.values():
            fam["valor"] = round(fam["soportadas"] / fam["verificables"], 4)

        if not verificables:
            return None, por_familia
        soportadas = sum(1 for a in verificables if a.soportada)
        return soportadas / len(verificables), por_familia

    def _aserciones_independientes(self, aserciones: list[Asercion]) -> list[Asercion]:
        """Aserciones que NO se derivan de los controles (numérica y motivo)."""
        familias = set(self.cfg.familias_independientes)
        return [a for a in aserciones if a.verificable and a.familia in familias]

    def anclaje_independiente(self, aserciones: list[Asercion]) -> float | None:
        """A calculada solo con las familias que no se derivan de los controles.

        Sirve para responder, con evidencia, si el anclaje aporta algo por
        encima de lo que ya miden las reglas duras.
        """
        verificables = self._aserciones_independientes(aserciones)
        if not verificables:
            return None
        return sum(1 for a in verificables if a.soportada) / len(verificables)

    def _tematico(self, entrada: EntradaFidelidad) -> float:
        opciones = (self.cfg.stopwords, self.cfg.minimo_caracteres_token)
        contexto = tokenizar(entrada.contexto_n, *opciones)
        respuesta = tokenizar(entrada.respuesta_n, *opciones)
        return min(1.0, coseno_tf(contexto, respuesta) / self.cfg.cos_referencia)

    def _penalizaciones(
        self, entrada: EntradaFidelidad, aserciones: list[Asercion]
    ) -> dict[str, float]:
        pesos = self.cfg.penalizaciones
        activadas: dict[str, float] = {}

        incumplidos = [r for r in entrada.resultados if r.estado is EstadoControl.NO_CUMPLE]
        if any(r.tipo == "afirmacion_no_soportada" for r in incumplidos):
            activadas["afirmacion_no_soportada"] = pesos["afirmacion_no_soportada"]
        if any(r.severidad == "BLOQUEO_CRITICO" for r in incumplidos):
            activadas["bloqueo_critico"] = pesos["bloqueo_critico"]

        no_soportadas = [a for a in aserciones if a.estado is EstadoAsercion.NO_SOPORTADA]
        cifras = sum(1 for a in no_soportadas if a.familia == "numerica")
        if cifras:
            activadas["cifra_no_soportada"] = min(
                cifras * pesos["cifra_no_soportada"], pesos["tope_cifras_no_soportadas"]
            )
        if any(a.familia == "requisito" for a in no_soportadas):
            activadas["requisito_omitido"] = pesos["requisito_omitido"]
        if any(a.familia == "motivo" for a in no_soportadas):
            activadas["motivo_inexistente"] = pesos["motivo_inexistente"]
        return activadas

    # ------------------------------------------------------------ puntaje

    def puntuar(self, entrada: EntradaFidelidad) -> PuntajeFidelidad:
        aserciones = extraer_aserciones(entrada, self.cfg)
        cumplimiento = _cumplimiento(self.reglas, entrada.resultados)
        anclaje, por_familia = self._anclaje(aserciones)
        tematico = self._tematico(entrada)

        pesos = dict(self.cfg.pesos)
        if anclaje is None:
            # El vacío no puntúa: se reparte el peso del anclaje entre los otros
            # dos componentes y el caso queda marcado para revisión humana.
            resto = pesos["cumplimiento"] + pesos["tematico"]
            pesos = {
                "cumplimiento": pesos["cumplimiento"] / resto,
                "anclaje": 0.0,
                "tematico": pesos["tematico"] / resto,
            }
            base = pesos["cumplimiento"] * cumplimiento + pesos["tematico"] * tematico
        else:
            base = (
                pesos["cumplimiento"] * cumplimiento
                + pesos["anclaje"] * anclaje
                + pesos["tematico"] * tematico
            )

        # La cobertura se juzga con las familias independientes de los controles:
        # una aserción de acción "soportada" solo repite lo que ya midió C y no
        # constituye, por sí sola, evidencia de que la respuesta esté anclada.
        cobertura = (
            COBERTURA_SUFICIENTE
            if self._aserciones_independientes(aserciones)
            else COBERTURA_INSUFICIENTE
        )

        activadas = self._penalizaciones(entrada, aserciones)
        penalizacion = min(self.cfg.penalizaciones["tope"], sum(activadas.values()))
        valor = max(0.0, min(1.0, base * (1 - penalizacion)))

        return PuntajeFidelidad(
            valor=round(valor, 2),
            componentes={
                "C": round(cumplimiento, 4),
                "A": None if anclaje is None else round(anclaje, 4),
                "A_independiente": _redondear(self.anclaje_independiente(aserciones)),
                "T": round(tematico, 4),
                "P": round(penalizacion, 4),
            },
            pesos_efectivos={k: round(v, 4) for k, v in pesos.items()},
            anclaje_por_familia=por_familia,
            aserciones=[
                {
                    "familia": a.familia,
                    "texto": a.texto,
                    "estado": a.estado.value,
                    "motivo": a.motivo,
                    "evidencia": a.evidencia,
                }
                for a in aserciones
            ],
            penalizaciones={k: round(v, 4) for k, v in activadas.items()},
            cobertura_evidencia=cobertura,
        )


def _redondear(valor: float | None) -> float | None:
    return None if valor is None else round(valor, 4)


EVALUADORES: dict[str, Callable[[Reglas], EvaluadorFidelidad]] = {
    EvaluadorProvisional.nombre: EvaluadorProvisional,
    EvaluadorSemantico.nombre: EvaluadorSemantico,
}


def crear_evaluador(nombre: str, reglas: Reglas) -> EvaluadorFidelidad:
    try:
        return EVALUADORES[nombre](reglas)
    except KeyError:
        raise ValueError(
            f"Evaluador desconocido: {nombre}. Disponibles: {sorted(EVALUADORES)}"
        ) from None
