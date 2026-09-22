"""Extracción de entidades cuantitativas y requisitos desde texto normalizado."""

from __future__ import annotations

import logging
import re

from .config import Reglas, RolesConfig
from .modelos import Extraccion

log = logging.getLogger(__name__)

ROL_RESPUESTA = "monto_respuesta"
ROL_SIN_ASIGNAR = "sin_rol"


def parsear_numero(crudo: str, separador_miles: str, separador_decimal: str) -> float:
    """Convierte '1,200' / '95,000.50' (o su variante regional) a float.

    Lanza ValueError si el texto no es un número válido tras quitar separadores.
    """
    limpio = crudo.strip().replace(separador_miles, "")
    if separador_decimal != ".":
        limpio = limpio.replace(separador_decimal, ".")
    if limpio.count(".") > 1:
        raise ValueError(f"número ambiguo: {crudo!r}")
    return float(limpio)


def _asignar_rol(texto: str, inicio: int, roles: RolesConfig) -> str:
    """Rol cuya palabra clave aparece más cerca (antes) de la cifra."""
    ventana = texto[max(0, inicio - roles.ventana_previa) : inicio]
    mejor, mejor_pos = ROL_SIN_ASIGNAR, -1
    for rol, matcher in roles.roles:
        pos = matcher.ultima_posicion(ventana)
        if pos > mejor_pos:
            mejor, mejor_pos = rol, pos
    return mejor


def _primer_grupo(m: re.Match[str]) -> str | None:
    return next((v for v in m.groupdict().values() if v), None)


class Extractor:
    def __init__(self, reglas: Reglas) -> None:
        self.reglas = reglas
        self.p = reglas.patrones
        self._miles = reglas.moneda["separador_miles"]
        self._decimal = reglas.moneda["separador_decimal"]

    def _numero(self, crudo: str, ext: Extraccion, que: str) -> float | None:
        try:
            return parsear_numero(crudo, self._miles, self._decimal)
        except ValueError:
            aviso = f"No se pudo interpretar {que} '{crudo}'"
            log.warning(aviso)
            ext.advertencias.append(aviso)
            return None

    def _montos(self, texto: str, ext: Extraccion, con_roles: bool) -> None:
        for m in self.p["monto"].finditer(texto):
            valor = self._numero(m.group("valor"), ext, "el monto")
            if valor is None:
                continue
            rol = _asignar_rol(texto, m.start(), self.reglas.roles_monto) if con_roles else ROL_RESPUESTA
            ext.montos.setdefault(rol, []).append(valor)

    def _porcentajes(self, texto: str, ext: Extraccion) -> None:
        for m in self.p["porcentaje"].finditer(texto):
            valor = self._numero(m.group("valor"), ext, "el porcentaje")
            if valor is None:
                continue
            if not 0 <= valor <= 100:
                ext.advertencias.append(f"Porcentaje fuera de rango: {valor}")
                continue
            rol = _asignar_rol(texto, m.start(), self.reglas.roles_porcentaje)
            ext.porcentajes.setdefault(rol, []).append(valor / 100)

    def _entero(self, nombre: str, texto: str) -> int | None:
        patron = self.p.get(nombre)
        m = patron.search(texto) if patron else None
        valor = _primer_grupo(m) if m else None
        return int(valor) if valor is not None else None

    def extraer(self, contexto_n: str, respuesta_n: str) -> Extraccion:
        """Recibe textos ya normalizados y devuelve las entidades encontradas."""
        ext = Extraccion()
        self._montos(contexto_n, ext, con_roles=True)
        self._montos(respuesta_n, ext, con_roles=False)
        self._porcentajes(contexto_n, ext)

        ext.edad_umbral = self._entero("edad_umbral", contexto_n)
        ext.edad_cliente = self._entero("edad_cliente", respuesta_n)

        if patron := self.p.get("siniestros_ventana"):
            if m := patron.search(contexto_n):
                ext.siniestros_conteo = int(m.group("conteo"))
                ext.siniestros_dias = int(m.group("dias"))

        if patron := self.p.get("requisito"):
            ext.requisitos = [m.group("requisito").strip() for m in patron.finditer(contexto_n)]

        if patron := self.p.get("neto_declarado"):
            if m := patron.search(respuesta_n):
                ext.neto_declarado = self._numero(m.group("valor"), ext, "el neto declarado")

        return ext
