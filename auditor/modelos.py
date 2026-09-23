"""Modelos de datos del auditor."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class EstadoControl(str, Enum):
    CUMPLE = "CUMPLE"
    NO_CUMPLE = "NO_CUMPLE"
    INDETERMINADO = "INDETERMINADO"
    NO_APLICA = "NO_APLICA"


ACCION_DESCONOCIDA = "DESCONOCIDA"


@dataclass(frozen=True)
class Caso:
    id_caso: int | str
    contexto_rag: str
    respuesta_agent_b: str


@dataclass(frozen=True)
class CasoInvalido:
    """Entrada que no pasó la validación; se reporta sin detener el lote."""

    id_caso: int | str | None
    posicion: int
    motivo: str


@dataclass
class Extraccion:
    """Entidades extraídas del contexto RAG y de la respuesta de Agent B."""

    montos: dict[str, list[float]] = field(default_factory=dict)
    porcentajes: dict[str, list[float]] = field(default_factory=dict)
    edad_umbral: int | None = None
    edad_cliente: int | None = None
    siniestros_conteo: int | None = None
    siniestros_dias: int | None = None
    requisitos: list[str] = field(default_factory=list)
    neto_declarado: float | None = None
    advertencias: list[str] = field(default_factory=list)

    def monto(self, rol: str) -> float | None:
        """Primer monto con el rol dado (los límites suelen ser únicos)."""
        valores = self.montos.get(rol)
        return valores[0] if valores else None

    def monto_maximo(self, rol: str) -> float | None:
        """Mayor monto con el rol dado (criterio conservador para montos aprobados)."""
        valores = self.montos.get(rol)
        return max(valores) if valores else None

    def porcentaje(self, rol: str) -> float | None:
        valores = self.porcentajes.get(rol)
        return valores[0] if valores else None


@dataclass(frozen=True)
class Accion:
    tipo: str
    evidencia: list[str] = field(default_factory=list)


@dataclass
class ResultadoControl:
    id: str
    tipo: str
    estado: EstadoControl
    severidad: str
    mensaje: str = ""
    evidencia: dict[str, Any] = field(default_factory=dict)

    @property
    def aplica(self) -> bool:
        return self.estado is not EstadoControl.NO_APLICA

    @property
    def es_hallazgo(self) -> bool:
        return self.estado in (EstadoControl.NO_CUMPLE, EstadoControl.INDETERMINADO)


@dataclass(frozen=True)
class EntradaFidelidad:
    """Todo lo que el evaluador de fidelidad necesita de un caso ya procesado."""

    caso: Caso
    contexto_n: str
    respuesta_n: str
    extraccion: Extraccion
    accion: Accion
    resultados: list[ResultadoControl]


@dataclass
class Veredicto:
    id_caso: int | str | None
    estado: str
    etiqueta: str
    indice: float
    diagnostico: str
    accion: Accion | None = None
    extraccion: Extraccion | None = None
    resultados: list[ResultadoControl] = field(default_factory=list)
    fidelidad: dict[str, Any] = field(default_factory=dict)
    errores: list[str] = field(default_factory=list)
