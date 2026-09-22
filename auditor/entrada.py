"""Carga del lote de casos (logs de Agent B) con validación por caso."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from .archivos import leer_json
from .excepciones import CasoInvalidoError, EntradaError
from .modelos import Caso, CasoInvalido

log = logging.getLogger(__name__)

CAMPOS_TEXTO = ("contexto_rag", "respuesta_agent_b")


def _validar_caso(item: Any) -> Caso:
    if not isinstance(item, dict):
        raise CasoInvalidoError("el caso no es un objeto JSON")

    if "id_caso" not in item:
        raise CasoInvalidoError("falta el campo 'id_caso'")
    id_caso = item["id_caso"]
    if isinstance(id_caso, bool) or not isinstance(id_caso, (int, str)) or str(id_caso).strip() == "":
        raise CasoInvalidoError("'id_caso' debe ser un entero o texto no vacío")

    textos = {}
    for campo in CAMPOS_TEXTO:
        if campo not in item:
            raise CasoInvalidoError(f"falta el campo '{campo}'")
        valor = item[campo]
        if not isinstance(valor, str):
            raise CasoInvalidoError(f"'{campo}' debe ser texto")
        if not valor.strip():
            raise CasoInvalidoError(f"'{campo}' está vacío")
        textos[campo] = valor
    return Caso(id_caso=id_caso, **textos)


def parsear_casos(datos: Any) -> list[Caso | CasoInvalido]:
    """Valida cada elemento del lote; los inválidos se devuelven como CasoInvalido."""
    if not isinstance(datos, list):
        raise EntradaError("La raíz del archivo de casos debe ser una lista JSON")

    resultado: list[Caso | CasoInvalido] = []
    vistos: set[str] = set()
    for pos, item in enumerate(datos):
        id_crudo = item.get("id_caso") if isinstance(item, dict) else None
        try:
            caso = _validar_caso(item)
            if str(caso.id_caso) in vistos:
                raise CasoInvalidoError(f"'id_caso' duplicado: {caso.id_caso}")
            vistos.add(str(caso.id_caso))
            resultado.append(caso)
        except CasoInvalidoError as exc:
            log.warning("Caso en posición %d inválido: %s", pos, exc)
            resultado.append(CasoInvalido(id_caso=id_crudo, posicion=pos, motivo=str(exc)))
    return resultado


def cargar_casos(ruta: str | Path) -> tuple[list[Caso | CasoInvalido], str]:
    """Lee el archivo de casos y devuelve (casos, sha256)."""
    datos, sha = leer_json(ruta, EntradaError)
    casos = parsear_casos(datos)
    log.info("Cargados %d casos desde %s", len(casos), ruta)
    return casos, sha
