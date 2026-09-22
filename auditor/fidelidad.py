"""Índice de Fidelidad Analítica: interfaz enchufable.

El motor solo depende del protocolo ``EvaluadorFidelidad``. El evaluador
provisional (Pilar 1) pondera el cumplimiento de controles por severidad; en el
Pilar 2 se registra un evaluador semántico sin modificar el motor.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from .config import Reglas
from .modelos import Caso, EstadoControl, Extraccion, ResultadoControl


class EvaluadorFidelidad(Protocol):
    nombre: str

    def puntuar(
        self, caso: Caso, extraccion: Extraccion, resultados: list[ResultadoControl]
    ) -> float:
        """Devuelve un puntaje en [0, 1]; 1 = decisión totalmente fiel al contexto."""
        ...


class EvaluadorProvisional:
    """I = sum(w_i * cumple_i) / sum(w_i), sobre los controles que aplican.

    w_i es el peso de la severidad del control en reglas.json. Si ningún
    control aplica, no hay evidencia de infidelidad y el índice es 1.0.
    """

    nombre = "provisional"

    def __init__(self, reglas: Reglas) -> None:
        self.reglas = reglas

    def puntuar(
        self, caso: Caso, extraccion: Extraccion, resultados: list[ResultadoControl]
    ) -> float:
        aplicables = [r for r in resultados if r.aplica]
        total = sum(self.reglas.peso(r.severidad) for r in aplicables)
        if total == 0:
            return 1.0
        cumplidos = sum(
            self.reglas.peso(r.severidad) for r in aplicables if r.estado is EstadoControl.CUMPLE
        )
        return round(cumplidos / total, 2)


EVALUADORES: dict[str, Callable[[Reglas], EvaluadorFidelidad]] = {
    EvaluadorProvisional.nombre: EvaluadorProvisional,
}


def crear_evaluador(nombre: str, reglas: Reglas) -> EvaluadorFidelidad:
    try:
        return EVALUADORES[nombre](reglas)
    except KeyError:
        raise ValueError(f"Evaluador desconocido: {nombre}. Disponibles: {sorted(EVALUADORES)}") from None
