"""Normalización de texto y búsqueda de palabras clave robusta a tildes y mayúsculas."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable

_ESPACIOS = re.compile(r"\s+")


def normalizar(texto: str) -> str:
    """Minúsculas, sin tildes/diacríticos y con espacios colapsados.

    No elimina signos de puntuación ni símbolos ($, %, _) para que las regex
    de extracción sigan funcionando sobre montos, porcentajes y códigos.
    """
    descompuesto = unicodedata.normalize("NFKD", texto)
    sin_tildes = "".join(c for c in descompuesto if not unicodedata.combining(c))
    return _ESPACIOS.sub(" ", sin_tildes.casefold()).strip()


def _compilar_clave(clave: str) -> re.Pattern[str]:
    """Convierte una clave de reglas.json en regex con límites de palabra.

    Cada token terminado en '*' se interpreta como raíz: 'examen* medic*'
    coincide con 'examenes medicos' y con 'examen medico'.
    """
    tokens = normalizar(clave).split(" ")
    partes = [
        re.escape(t[:-1]) + r"\w*" if t.endswith("*") else re.escape(t) for t in tokens
    ]
    return re.compile(r"\b" + r"\s+".join(partes) + r"\b")


class ClaveMatcher:
    """Conjunto de palabras clave precompiladas."""

    def __init__(self, claves: Iterable[str]) -> None:
        self.claves = list(claves)
        self._patrones = [_compilar_clave(c) for c in self.claves]

    def buscar(self, texto_normalizado: str) -> list[str]:
        """Devuelve los fragmentos de texto que coincidieron (sin duplicados, en orden)."""
        encontrados: list[str] = []
        for patron in self._patrones:
            m = patron.search(texto_normalizado)
            if m and m.group(0) not in encontrados:
                encontrados.append(m.group(0))
        return encontrados

    def ultima_posicion(self, texto_normalizado: str) -> int:
        """Posición final de la última coincidencia, o -1 si no hay ninguna."""
        fin = -1
        for patron in self._patrones:
            for m in patron.finditer(texto_normalizado):
                fin = max(fin, m.end())
        return fin

    def __bool__(self) -> bool:
        return bool(self._patrones)
