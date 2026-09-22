"""Lectura segura de archivos JSON y huellas para trazabilidad."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .excepciones import AuditorError


def leer_json(ruta: str | Path, error_cls: type[AuditorError]) -> tuple[Any, str]:
    """Lee un JSON en UTF-8 y devuelve (contenido, sha256 del archivo).

    Cualquier problema de E/S o de sintaxis se traduce a ``error_cls`` con un
    mensaje que indica archivo, línea y columna.
    """
    ruta = Path(ruta)
    try:
        crudo = ruta.read_bytes()
    except FileNotFoundError as exc:
        raise error_cls(f"No existe el archivo: {ruta}") from exc
    except OSError as exc:
        raise error_cls(f"No se pudo leer {ruta}: {exc}") from exc

    try:
        contenido = json.loads(crudo.decode("utf-8-sig"))
    except UnicodeDecodeError as exc:
        raise error_cls(f"{ruta} no está codificado en UTF-8: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise error_cls(
            f"JSON mal formado en {ruta} (línea {exc.lineno}, columna {exc.colno}): {exc.msg}"
        ) from exc

    return contenido, hashlib.sha256(crudo).hexdigest()
