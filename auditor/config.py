"""Carga y validación de reglas.json.

Toda la lógica parametrizable del auditor (umbrales, palabras clave, regex,
severidades, etiquetas y mensajes) vive en ese archivo; aquí solo se valida y
se precompila para que el motor no tenga valores embebidos.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .archivos import leer_json
from .excepciones import ConfigError
from .normalizacion import ClaveMatcher

PATRONES_OBLIGATORIOS = ("monto", "porcentaje")
SEVERIDADES_OBLIGATORIAS = ("CONFORME", "REVISION_MANUAL")
ESTADO_CONFORME = "CONFORME"
ESTADO_REVISION = "REVISION_MANUAL"


@dataclass(frozen=True)
class RolesConfig:
    ventana_previa: int
    roles: list[tuple[str, ClaveMatcher]]


@dataclass(frozen=True)
class ControlConfig:
    id: str
    tipo: str
    severidad: str
    activo: bool
    parametros: dict[str, Any]
    claves: dict[str, ClaveMatcher]
    mensajes: dict[str, str]


@dataclass(frozen=True)
class FidelidadConfig:
    """Parámetros del Índice de Fidelidad Analítica (ver README, §métrica)."""

    evaluador_por_defecto: str
    umbral_revision: float
    pesos: dict[str, float]
    tolerancia_relativa: float
    derivaciones: list[str]
    familias_activas: list[str]
    familias_independientes: list[str]
    familias_no_verificables: list[str]
    acciones_restrictivas: list[str]
    acciones_de_aprobacion: list[str]
    claves_directiva_restrictiva: ClaveMatcher
    claves_estado: ClaveMatcher
    claves_motivo_alegado: ClaveMatcher
    backend: str
    cos_referencia: float
    minimo_caracteres_token: int
    stopwords: frozenset[str]
    penalizaciones: dict[str, float]


@dataclass(frozen=True)
class Reglas:
    version: str
    moneda: dict[str, str]
    orden_severidad: list[str]
    pesos: dict[str, float]
    etiquetas: dict[str, str]
    patrones: dict[str, re.Pattern[str]]
    roles_monto: RolesConfig
    roles_porcentaje: RolesConfig
    prioridad_acciones: list[str]
    claves_acciones: dict[str, ClaveMatcher]
    controles: list[ControlConfig]
    fidelidad: FidelidadConfig
    sha256: str = ""
    ruta: Path | None = field(default=None, compare=False)

    def rango(self, severidad: str) -> int:
        return self.orden_severidad.index(severidad)

    def etiqueta(self, severidad: str) -> str:
        return self.etiquetas.get(severidad, severidad)

    def peso(self, severidad: str) -> float:
        return self.pesos.get(severidad, 0.0)


# ---------------------------------------------------------------- utilidades


def _requerir(d: Any, clave: str, tipo: type | tuple[type, ...], ruta: str) -> Any:
    completa = f"{ruta}.{clave}" if ruta else clave
    if not isinstance(d, dict) or clave not in d:
        raise ConfigError(f"Falta el campo obligatorio '{completa}'")
    valor = d[clave]
    if not isinstance(valor, tipo) or (isinstance(valor, bool) and tipo is not bool):
        nombre = tipo.__name__ if isinstance(tipo, type) else "/".join(t.__name__ for t in tipo)
        raise ConfigError(f"'{completa}' debe ser de tipo {nombre}")
    return valor


def _lista_de_str(valor: Any, ruta: str) -> list[str]:
    if not isinstance(valor, list) or not all(isinstance(v, str) and v.strip() for v in valor):
        raise ConfigError(f"'{ruta}' debe ser una lista de textos no vacíos")
    return valor


def _compilar(patron: str, ruta: str) -> re.Pattern[str]:
    try:
        return re.compile(patron)
    except re.error as exc:
        raise ConfigError(f"Regex inválida en '{ruta}': {exc}") from exc


def _roles(d: dict, nombre: str) -> RolesConfig:
    bloque = _requerir(d, nombre, dict, "")
    ventana = _requerir(bloque, "ventana_previa", int, nombre)
    if ventana <= 0:
        raise ConfigError(f"'{nombre}.ventana_previa' debe ser positivo")
    roles = []
    for i, rol in enumerate(_requerir(bloque, "roles", list, nombre)):
        ruta = f"{nombre}.roles[{i}]"
        roles.append(
            (
                _requerir(rol, "rol", str, ruta),
                ClaveMatcher(_lista_de_str(_requerir(rol, "claves", list, ruta), f"{ruta}.claves")),
            )
        )
    return RolesConfig(ventana, roles)


def _controles(lista: list, orden: list[str]) -> list[ControlConfig]:
    from .controles import REGISTRO  # import diferido: controles no depende de config en runtime

    vistos: set[str] = set()
    controles = []
    for i, c in enumerate(lista):
        ruta = f"controles[{i}]"
        cid = _requerir(c, "id", str, ruta)
        if cid in vistos:
            raise ConfigError(f"'{ruta}.id' duplicado: {cid}")
        vistos.add(cid)

        tipo = _requerir(c, "tipo", str, ruta)
        if tipo not in REGISTRO:
            raise ConfigError(
                f"'{ruta}.tipo' desconocido: {tipo}. Tipos disponibles: {sorted(REGISTRO)}"
            )
        severidad = _requerir(c, "severidad", str, ruta)
        if severidad not in orden or severidad == ESTADO_CONFORME:
            raise ConfigError(f"'{ruta}.severidad' inválida: {severidad}")

        mensajes = c.get("mensajes", {})
        if not isinstance(mensajes, dict) or not all(isinstance(v, str) for v in mensajes.values()):
            raise ConfigError(f"'{ruta}.mensajes' debe ser un objeto de textos")

        claves = {
            k: ClaveMatcher(_lista_de_str(v, f"{ruta}.{k}"))
            for k, v in c.items()
            if k.startswith("claves")
        }
        parametros = {
            k: v
            for k, v in c.items()
            if k not in {"id", "tipo", "severidad", "activo", "mensajes"} and k not in claves
        }
        controles.append(
            ControlConfig(
                id=cid,
                tipo=tipo,
                severidad=severidad,
                activo=bool(c.get("activo", True)),
                parametros=parametros,
                claves=claves,
                mensajes=mensajes,
            )
        )
    return controles


def _numero(d: dict, clave: str, ruta: str, minimo: float = 0.0, maximo: float = 1.0) -> float:
    valor = _requerir(d, clave, (int, float), ruta)
    if not minimo <= float(valor) <= maximo:
        raise ConfigError(f"'{ruta}.{clave}' debe estar entre {minimo} y {maximo}")
    return float(valor)


BACKENDS_TEXTO = ("tf",)
PENALIZACIONES_OBLIGATORIAS = (
    "tope",
    "afirmacion_no_soportada",
    "bloqueo_critico",
    "requisito_omitido",
    "cifra_no_soportada",
    "tope_cifras_no_soportadas",
    "motivo_inexistente",
)


def _fidelidad(datos: dict) -> FidelidadConfig:
    from .fidelidad import EVALUADORES  # import diferido para evitar el ciclo

    bloque = _requerir(datos, "fidelidad", dict, "")
    evaluador = _requerir(bloque, "evaluador_por_defecto", str, "fidelidad")
    if evaluador not in EVALUADORES:
        raise ConfigError(
            f"'fidelidad.evaluador_por_defecto' desconocido: {evaluador}. "
            f"Disponibles: {sorted(EVALUADORES)}"
        )

    pesos_crudos = _requerir(bloque, "pesos", dict, "fidelidad")
    pesos = {c: _numero(pesos_crudos, c, "fidelidad.pesos") for c in ("cumplimiento", "anclaje", "tematico")}
    if abs(sum(pesos.values()) - 1.0) > 1e-6:
        raise ConfigError(f"'fidelidad.pesos' debe sumar 1.0 (suma {sum(pesos.values())})")

    anclaje = _requerir(bloque, "anclaje", dict, "fidelidad")
    texto = _requerir(bloque, "texto", dict, "fidelidad")
    backend = _requerir(texto, "backend", str, "fidelidad.texto")
    if backend not in BACKENDS_TEXTO:
        raise ConfigError(
            f"'fidelidad.texto.backend' desconocido: {backend}. Disponibles: {list(BACKENDS_TEXTO)}"
        )
    cos_ref = _numero(texto, "cos_referencia", "fidelidad.texto", minimo=1e-6)
    min_token = _requerir(texto, "minimo_caracteres_token", int, "fidelidad.texto")
    if min_token < 1:
        raise ConfigError("'fidelidad.texto.minimo_caracteres_token' debe ser positivo")

    penal_crudas = _requerir(bloque, "penalizaciones", dict, "fidelidad")
    penalizaciones = {
        k: _numero(penal_crudas, k, "fidelidad.penalizaciones") for k in PENALIZACIONES_OBLIGATORIAS
    }

    return FidelidadConfig(
        evaluador_por_defecto=evaluador,
        umbral_revision=_numero(bloque, "umbral_revision", "fidelidad"),
        pesos=pesos,
        tolerancia_relativa=_numero(anclaje, "tolerancia_relativa", "fidelidad.anclaje"),
        derivaciones=_lista_de_str(
            _requerir(anclaje, "derivaciones", list, "fidelidad.anclaje"), "fidelidad.anclaje.derivaciones"
        ),
        familias_activas=_lista_de_str(
            _requerir(anclaje, "familias_activas", list, "fidelidad.anclaje"),
            "fidelidad.anclaje.familias_activas",
        ),
        familias_independientes=_lista_de_str(
            _requerir(anclaje, "familias_independientes", list, "fidelidad.anclaje"),
            "fidelidad.anclaje.familias_independientes",
        ),
        familias_no_verificables=_lista_de_str(
            _requerir(anclaje, "familias_no_verificables", list, "fidelidad.anclaje"),
            "fidelidad.anclaje.familias_no_verificables",
        ),
        acciones_restrictivas=_lista_de_str(
            _requerir(anclaje, "acciones_restrictivas", list, "fidelidad.anclaje"),
            "fidelidad.anclaje.acciones_restrictivas",
        ),
        acciones_de_aprobacion=_lista_de_str(
            _requerir(anclaje, "acciones_de_aprobacion", list, "fidelidad.anclaje"),
            "fidelidad.anclaje.acciones_de_aprobacion",
        ),
        claves_directiva_restrictiva=ClaveMatcher(
            _lista_de_str(
                _requerir(anclaje, "claves_directiva_restrictiva", list, "fidelidad.anclaje"),
                "fidelidad.anclaje.claves_directiva_restrictiva",
            )
        ),
        claves_estado=ClaveMatcher(
            _lista_de_str(
                _requerir(anclaje, "claves_estado", list, "fidelidad.anclaje"),
                "fidelidad.anclaje.claves_estado",
            )
        ),
        claves_motivo_alegado=ClaveMatcher(
            _lista_de_str(
                _requerir(anclaje, "claves_motivo_alegado", list, "fidelidad.anclaje"),
                "fidelidad.anclaje.claves_motivo_alegado",
            )
        ),
        backend=backend,
        cos_referencia=cos_ref,
        minimo_caracteres_token=min_token,
        stopwords=frozenset(
            _lista_de_str(_requerir(texto, "stopwords", list, "fidelidad.texto"), "fidelidad.texto.stopwords")
        ),
        penalizaciones=penalizaciones,
    )


# ---------------------------------------------------------------- API pública


def construir_reglas(datos: Any, sha256: str = "", ruta: Path | None = None) -> Reglas:
    """Valida un diccionario ya parseado y devuelve la configuración compilada."""
    if not isinstance(datos, dict):
        raise ConfigError("La raíz de reglas.json debe ser un objeto JSON")

    sev = _requerir(datos, "severidades", dict, "")
    orden = _lista_de_str(_requerir(sev, "orden", list, "severidades"), "severidades.orden")
    faltantes = [s for s in SEVERIDADES_OBLIGATORIAS if s not in orden]
    if faltantes:
        raise ConfigError(f"'severidades.orden' debe incluir {faltantes}")
    pesos = _requerir(sev, "pesos", dict, "severidades")
    for s, w in pesos.items():
        if s not in orden or not isinstance(w, (int, float)) or w < 0:
            raise ConfigError(f"'severidades.pesos.{s}' inválido")
    etiquetas = sev.get("etiquetas", {})

    patrones_crudos = _requerir(datos, "patrones", dict, "")
    for p in PATRONES_OBLIGATORIOS:
        _requerir(patrones_crudos, p, str, "patrones")
    patrones = {k: _compilar(v, f"patrones.{k}") for k, v in patrones_crudos.items()}

    acciones = _requerir(datos, "acciones", dict, "")
    prioridad = _lista_de_str(_requerir(acciones, "prioridad", list, "acciones"), "acciones.prioridad")
    claves_acc = _requerir(acciones, "claves", dict, "acciones")
    for a in prioridad:
        if a not in claves_acc:
            raise ConfigError(f"'acciones.claves' no define la acción '{a}'")

    controles = _controles(_requerir(datos, "controles", list, ""), orden)
    for c in controles:
        if c.severidad not in pesos:
            raise ConfigError(f"'severidades.pesos' no define peso para '{c.severidad}' ({c.id})")

    moneda = datos.get("moneda", {})
    return Reglas(
        version=str(datos.get("version", "sin-version")),
        moneda={
            "codigo": moneda.get("codigo", "USD"),
            "separador_miles": moneda.get("separador_miles", ","),
            "separador_decimal": moneda.get("separador_decimal", "."),
        },
        orden_severidad=orden,
        pesos={k: float(v) for k, v in pesos.items()},
        etiquetas=etiquetas,
        patrones=patrones,
        roles_monto=_roles(datos, "roles_monto"),
        roles_porcentaje=_roles(datos, "roles_porcentaje"),
        prioridad_acciones=prioridad,
        claves_acciones={
            a: ClaveMatcher(_lista_de_str(claves_acc[a], f"acciones.claves.{a}")) for a in prioridad
        },
        controles=controles,
        fidelidad=_fidelidad(datos),
        sha256=sha256,
        ruta=ruta,
    )


def cargar_reglas(ruta: str | Path) -> Reglas:
    datos, sha = leer_json(ruta, ConfigError)
    return construir_reglas(datos, sha, Path(ruta))
