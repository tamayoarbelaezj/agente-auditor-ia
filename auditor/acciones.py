"""Clasificación de la acción tomada por Agent B a partir de su respuesta."""

from __future__ import annotations

from .config import Reglas
from .modelos import ACCION_DESCONOCIDA, Accion


def clasificar_accion(respuesta_n: str, reglas: Reglas) -> Accion:
    """Primera acción, según la prioridad configurada, con alguna clave presente.

    La prioridad (ESCALAMIENTO > RECHAZO > APROBACION por defecto) evita que
    frases como "no puedo procesar ... un analista" se lean como aprobación.
    """
    for accion in reglas.prioridad_acciones:
        evidencia = reglas.claves_acciones[accion].buscar(respuesta_n)
        if evidencia:
            return Accion(accion, evidencia)
    return Accion(ACCION_DESCONOCIDA)
