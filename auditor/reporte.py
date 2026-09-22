"""Salida del auditor: formato de consola exigido y JSON de trazabilidad."""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from .modelos import Veredicto


def formatear_veredicto(v: Veredicto) -> str:
    """Estructura exacta requerida por el reto (3 líneas por caso)."""
    return (
        f"Caso {v.id_caso}: {v.etiqueta}\n"
        f"- Índice de Fidelidad Analítica: {v.indice:.2f}\n"
        f"- Diagnóstico/Razón: {v.diagnostico}"
    )


def formatear_reporte(veredictos: list[Veredicto]) -> str:
    return "\n\n".join(formatear_veredicto(v) for v in veredictos) + "\n"


def _serializable(obj: Any) -> Any:
    if isinstance(obj, Enum):
        return obj.value
    if isinstance(obj, dict):
        return {k: _serializable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_serializable(v) for v in obj]
    return obj


def construir_json(veredictos: list[Veredicto], metadatos: dict[str, Any]) -> dict[str, Any]:
    resumen: dict[str, int] = {}
    for v in veredictos:
        resumen[v.estado] = resumen.get(v.estado, 0) + 1
    return {
        "metadatos": {"generado_utc": datetime.now(timezone.utc).isoformat(), **metadatos},
        "resumen": {"total_casos": len(veredictos), "por_estado": resumen},
        "casos": [_serializable(asdict(v)) for v in veredictos],
    }


def escribir(ruta: str | Path, contenido: str) -> None:
    ruta = Path(ruta)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(contenido, encoding="utf-8")


def escribir_json(ruta: str | Path, datos: dict[str, Any]) -> None:
    escribir(ruta, json.dumps(datos, ensure_ascii=False, indent=2))
