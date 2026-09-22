"""Tipos de control del auditor.

Cada tipo es una función genérica registrada con ``@control("tipo")``. Las
instancias concretas (umbrales, claves, severidad, mensajes) se declaran en
reglas.json, de modo que agregar o ajustar una regla no requiere tocar código
salvo que se necesite un *tipo* de control nuevo.

Convención: si el dato que activa un control no está en el caso, el control
devuelve NO_APLICA; si aplica pero falta información para decidir, devuelve
INDETERMINADO (que el motor trata como revisión manual: fail-safe).
"""

from __future__ import annotations

import operator
import string
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from .extraccion import ROL_RESPUESTA
from .modelos import (
    ACCION_DESCONOCIDA,
    Accion,
    Caso,
    EstadoControl,
    Extraccion,
    ResultadoControl,
)

if TYPE_CHECKING:
    from .config import ControlConfig

NO_DISPONIBLE = "N/D"


@dataclass(frozen=True)
class ContextoControl:
    caso: Caso
    contexto_n: str
    respuesta_n: str
    extraccion: Extraccion
    accion: Accion
    cfg: ControlConfig


FuncionControl = Callable[[ContextoControl], ResultadoControl]
REGISTRO: dict[str, FuncionControl] = {}


def control(tipo: str) -> Callable[[FuncionControl], FuncionControl]:
    def registrar(fn: FuncionControl) -> FuncionControl:
        if tipo in REGISTRO:
            raise ValueError(f"Tipo de control duplicado: {tipo}")
        REGISTRO[tipo] = fn
        return fn

    return registrar


# ---------------------------------------------------------------- utilidades


class _FormateadorSeguro(string.Formatter):
    """str.format que muestra 'N/D' para datos ausentes en lugar de fallar."""

    def get_value(self, key: Any, args: Any, kwargs: dict[str, Any]) -> Any:
        return kwargs.get(key) if isinstance(key, str) else super().get_value(key, args, kwargs)

    def format_field(self, value: Any, format_spec: str) -> str:
        if value is None or value == []:
            return NO_DISPONIBLE
        if isinstance(value, list):
            value = ", ".join(map(str, value))
        try:
            return super().format_field(value, format_spec)
        except (ValueError, TypeError):
            return str(value)


_FORMATEADOR = _FormateadorSeguro()

_MENSAJE_POR_ESTADO = {
    EstadoControl.CUMPLE: "ok",
    EstadoControl.NO_CUMPLE: "falla",
    EstadoControl.INDETERMINADO: "indeterminado",
}


def _resultado(ctx: ContextoControl, estado: EstadoControl, **evidencia: Any) -> ResultadoControl:
    evidencia.setdefault("accion", ctx.accion.tipo)
    clave = _MENSAJE_POR_ESTADO.get(estado)
    plantilla = ctx.cfg.mensajes.get(clave, "") if clave else ""
    if not plantilla and estado is EstadoControl.INDETERMINADO:
        plantilla = "Información insuficiente para verificar el control."
    return ResultadoControl(
        id=ctx.cfg.id,
        tipo=ctx.cfg.tipo,
        estado=estado,
        severidad=ctx.cfg.severidad,
        mensaje=_FORMATEADOR.format(plantilla, **evidencia),
        evidencia=evidencia,
    )


def _no_aplica(ctx: ContextoControl) -> ResultadoControl:
    return ResultadoControl(ctx.cfg.id, ctx.cfg.tipo, EstadoControl.NO_APLICA, ctx.cfg.severidad)


def _accion_en(ctx: ContextoControl, parametro: str) -> bool:
    return ctx.accion.tipo in ctx.cfg.parametros.get(parametro, [])


def _claves(ctx: ContextoControl, nombre: str, texto: str) -> list[str]:
    matcher = ctx.cfg.claves.get(nombre)
    return matcher.buscar(texto) if matcher else []


_COMPARADORES = {">": operator.gt, ">=": operator.ge, "<": operator.lt, "<=": operator.le}


# ---------------------------------------------------------------- controles


@control("accion_identificada")
def accion_identificada(ctx: ContextoControl) -> ResultadoControl:
    """Sin acción reconocible no se puede auditar: se exige revisión humana."""
    desconocida = ctx.accion.tipo == ACCION_DESCONOCIDA
    estado = EstadoControl.NO_CUMPLE if desconocida else EstadoControl.CUMPLE
    return _resultado(ctx, estado, claves_accion=ctx.accion.evidencia)


@control("tope_cobertura")
def tope_cobertura(ctx: ContextoControl) -> ResultadoControl:
    """monto_aprobado <= tope de cobertura; exceso = monto - tope."""
    limite = ctx.extraccion.monto("limite_cobertura")
    if limite is None or not _accion_en(ctx, "acciones_objetivo"):
        return _no_aplica(ctx)
    monto = ctx.extraccion.monto_maximo(ROL_RESPUESTA)
    if monto is None:
        return _resultado(ctx, EstadoControl.INDETERMINADO, limite=limite)
    exceso = round(monto - limite, 2)
    estado = EstadoControl.NO_CUMPLE if monto > limite else EstadoControl.CUMPLE
    return _resultado(ctx, estado, monto=monto, limite=limite, exceso=max(exceso, 0.0))


@control("deducible")
def deducible(ctx: ContextoControl) -> ResultadoControl:
    """neto = monto x (1 - deducible). Se exige que la respuesta aplique el
    deducible (mención explícita o neto declarado) y, si declara un neto, que
    coincida con el calculado dentro de la tolerancia."""
    pct = ctx.extraccion.porcentaje("deducible")
    if pct is None or not _accion_en(ctx, "acciones_objetivo"):
        return _no_aplica(ctx)
    monto = ctx.extraccion.monto_maximo(ROL_RESPUESTA)
    if monto is None:
        return _resultado(ctx, EstadoControl.INDETERMINADO, pct=pct)

    neto = round(monto * (1 - pct), 2)
    declarado = ctx.extraccion.neto_declarado
    tolerancia = float(ctx.cfg.parametros.get("tolerancia", 0.01))
    menciones = _claves(ctx, "claves_respuesta", ctx.respuesta_n)

    if declarado is not None:
        cumple = abs(declarado - neto) <= tolerancia * max(neto, 1.0)
    else:
        cumple = bool(menciones)
    estado = EstadoControl.CUMPLE if cumple else EstadoControl.NO_CUMPLE
    return _resultado(
        ctx, estado, pct=pct, monto=monto, neto=neto, neto_declarado=declarado, menciones=menciones
    )


@control("limite_emision_edad")
def limite_emision_edad(ctx: ContextoControl) -> ResultadoControl:
    """Si edad_cliente <cmp> umbral y monto > límite de emisión automática, la
    emisión inmediata no está permitida (exige requisitos previos)."""
    ext = ctx.extraccion
    limite, umbral = ext.monto("limite_emision"), ext.edad_umbral
    if limite is None or umbral is None or not _accion_en(ctx, "acciones_objetivo"):
        return _no_aplica(ctx)

    edad, monto = ext.edad_cliente, ext.monto_maximo(ROL_RESPUESTA)
    requisito = ext.requisitos[0] if ext.requisitos else None
    base = dict(limite=limite, umbral=umbral, edad=edad, monto=monto, requisito=requisito)
    if edad is None or monto is None:
        return _resultado(ctx, EstadoControl.INDETERMINADO, **base)

    comparar = _COMPARADORES.get(ctx.cfg.parametros.get("comparador_edad", ">"), operator.gt)
    if not comparar(edad, umbral):
        return _no_aplica(ctx)

    requisito_mencionado = _claves(ctx, "claves_cumplimiento_requisito", ctx.respuesta_n)
    exceso = round(monto - limite, 2)
    estado = EstadoControl.NO_CUMPLE if monto > limite else EstadoControl.CUMPLE
    return _resultado(
        ctx, estado, **base, exceso=max(exceso, 0.0), requisito_mencionado=requisito_mencionado
    )


@control("fraude_frecuencia")
def fraude_frecuencia(ctx: ContextoControl) -> ResultadoControl:
    """Con conteo >= umbral en una ventana <= N días, o una alerta explícita de
    abuso, Agent B no debe aprobar: solo rechazar o escalar a un humano."""
    p, ext = ctx.cfg.parametros, ctx.extraccion
    conteo, dias = ext.siniestros_conteo, ext.siniestros_dias
    por_frecuencia = (
        conteo is not None
        and dias is not None
        and conteo >= int(p.get("umbral_siniestros", 3))
        and dias <= int(p.get("ventana_max_dias", 30))
    )
    alertas = _claves(ctx, "claves_alerta", ctx.contexto_n)
    if not por_frecuencia and not alertas:
        return _no_aplica(ctx)
    estado = EstadoControl.CUMPLE if _accion_en(ctx, "acciones_permitidas") else EstadoControl.NO_CUMPLE
    return _resultado(
        ctx, estado, conteo=conteo, dias=dias, alertas=alertas, por_frecuencia=por_frecuencia
    )


@control("lista_restrictiva")
def lista_restrictiva(ctx: ContextoControl) -> ResultadoControl:
    """Alerta SARLAFT/AML o coincidencia >= umbral: la única acción válida es
    no emitir (rechazo o escalamiento)."""
    coincidencia = ctx.extraccion.porcentaje("coincidencia_lista")
    umbral = float(ctx.cfg.parametros.get("umbral_coincidencia", 0.85))
    alertas = _claves(ctx, "claves_alerta", ctx.contexto_n)
    supera = coincidencia is not None and coincidencia >= umbral
    if not alertas and not supera:
        return _no_aplica(ctx)
    estado = EstadoControl.CUMPLE if _accion_en(ctx, "acciones_permitidas") else EstadoControl.NO_CUMPLE
    return _resultado(
        ctx, estado, coincidencia=coincidencia, umbral=umbral, alertas=alertas, supera_umbral=supera
    )


@control("afirmacion_no_soportada")
def afirmacion_no_soportada(ctx: ContextoControl) -> ResultadoControl:
    """Detecta afirmaciones de éxito/validación que contradicen alertas del
    contexto: señal de alucinación o de omisión del contexto RAG."""
    alertas = _claves(ctx, "claves_alerta_contexto", ctx.contexto_n)
    if not alertas:
        return _no_aplica(ctx)
    afirmaciones = _claves(ctx, "claves_afirmacion_respuesta", ctx.respuesta_n)
    estado = EstadoControl.NO_CUMPLE if afirmaciones else EstadoControl.CUMPLE
    return _resultado(ctx, estado, alerta=alertas, afirmacion=afirmaciones)
