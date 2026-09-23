"""Orquestación de la auditoría: extracción → acción → controles → estado → índice."""

from __future__ import annotations

import logging
from dataclasses import asdict

from .acciones import clasificar_accion
from .config import ESTADO_CONFORME, ESTADO_REVISION, Reglas
from .controles import REGISTRO, ContextoControl
from .extraccion import Extractor
from .fidelidad import (
    COBERTURA_INSUFICIENTE,
    EvaluadorFidelidad,
    PuntajeFidelidad,
    crear_evaluador,
)
from .modelos import (
    Accion,
    Caso,
    CasoInvalido,
    EntradaFidelidad,
    EstadoControl,
    ResultadoControl,
    Veredicto,
)
from .normalizacion import normalizar

log = logging.getLogger(__name__)


class Auditor:
    """Agente Auditor (Agent A)."""

    def __init__(self, reglas: Reglas, evaluador: EvaluadorFidelidad | None = None) -> None:
        self.reglas = reglas
        self.evaluador = evaluador or crear_evaluador(
            reglas.fidelidad.evaluador_por_defecto, reglas
        )
        self.extractor = Extractor(reglas)

    # ------------------------------------------------------------ resolución

    def _severidad_efectiva(self, r: ResultadoControl) -> str:
        return r.severidad if r.estado is EstadoControl.NO_CUMPLE else ESTADO_REVISION

    def resolver_estado(self, resultados: list[ResultadoControl]) -> str:
        """Severidad más alta entre los hallazgos; CONFORME si no hay ninguno."""
        hallazgos = [self._severidad_efectiva(r) for r in resultados if r.es_hallazgo]
        return max(hallazgos, key=self.reglas.rango, default=ESTADO_CONFORME)

    def _diagnostico(self, resultados: list[ResultadoControl]) -> str:
        hallazgos = sorted(
            (r for r in resultados if r.es_hallazgo),
            key=lambda r: self.reglas.rango(self._severidad_efectiva(r)),
            reverse=True,
        )
        elegidos = hallazgos or [r for r in resultados if r.aplica]
        return " | ".join(f"[{r.id}] {r.mensaje}" for r in elegidos if r.mensaje)

    # ------------------------------------------------------------ ejecución

    def _ejecutar_control(self, ctx: ContextoControl) -> ResultadoControl:
        try:
            return REGISTRO[ctx.cfg.tipo](ctx)
        except Exception as exc:  # fail-safe: un control roto nunca aprueba por omisión
            log.exception("Error en %s para el caso %s", ctx.cfg.id, ctx.caso.id_caso)
            return ResultadoControl(
                id=ctx.cfg.id,
                tipo=ctx.cfg.tipo,
                estado=EstadoControl.INDETERMINADO,
                severidad=ctx.cfg.severidad,
                mensaje=f"Error interno del control: {type(exc).__name__}: {exc}",
            )

    def _puntuar(self, entrada: EntradaFidelidad) -> PuntajeFidelidad:
        try:
            return self.evaluador.puntuar(entrada)
        except Exception as exc:  # fail-safe: sin índice confiable, decide un humano
            log.exception("Error evaluando la fidelidad del caso %s", entrada.caso.id_caso)
            return PuntajeFidelidad(
                valor=0.0,
                componentes={"error": f"{type(exc).__name__}: {exc}"},
                cobertura_evidencia=COBERTURA_INSUFICIENTE,
            )

    def _aplicar_fidelidad(
        self, estado: str, puntaje: PuntajeFidelidad, accion: Accion
    ) -> tuple[str, str]:
        """El índice solo puede escalar la severidad, nunca relajarla."""
        cfg = self.reglas.fidelidad
        if self.reglas.rango(estado) > self.reglas.rango(ESTADO_CONFORME):
            return estado, ""
        aprueba = accion.tipo in cfg.acciones_de_aprobacion
        if puntaje.evidencia_insuficiente and aprueba:
            return ESTADO_REVISION, (
                "Aprobación sin aserciones verificables contra el contexto: "
                "la evidencia no alcanza para auditar la decisión automáticamente."
            )
        if puntaje.valor < cfg.umbral_revision:
            return ESTADO_REVISION, (
                f"Fidelidad analítica {puntaje.valor:.2f} < {cfg.umbral_revision:.2f}: "
                "la decisión cumple las reglas duras pero no se apoya verificablemente en el contexto."
            )
        return estado, ""

    def auditar(self, caso: Caso) -> Veredicto:
        contexto_n = normalizar(caso.contexto_rag)
        respuesta_n = normalizar(caso.respuesta_agent_b)
        extraccion = self.extractor.extraer(contexto_n, respuesta_n)
        accion = clasificar_accion(respuesta_n, self.reglas)
        log.debug("Caso %s: acción=%s extracción=%s", caso.id_caso, accion, extraccion)

        resultados = [
            self._ejecutar_control(
                ContextoControl(caso, contexto_n, respuesta_n, extraccion, accion, cfg)
            )
            for cfg in self.reglas.controles
            if cfg.activo
        ]
        entrada = EntradaFidelidad(caso, contexto_n, respuesta_n, extraccion, accion, resultados)
        puntaje = self._puntuar(entrada)
        estado, motivo_fidelidad = self._aplicar_fidelidad(
            self.resolver_estado(resultados), puntaje, accion
        )

        diagnostico = self._diagnostico(resultados) or "Sin controles aplicables."
        if motivo_fidelidad:
            diagnostico = f"{diagnostico} | [IFA] {motivo_fidelidad}"
        return Veredicto(
            id_caso=caso.id_caso,
            estado=estado,
            etiqueta=self.reglas.etiqueta(estado),
            indice=puntaje.valor,
            diagnostico=diagnostico,
            accion=accion,
            extraccion=extraccion,
            resultados=resultados,
            fidelidad=asdict(puntaje),
            errores=list(extraccion.advertencias),
        )

    def veredicto_invalido(self, caso: CasoInvalido) -> Veredicto:
        donde = f" (posición {caso.posicion} del lote)" if caso.posicion >= 0 else ""
        motivo = f"Error de datos: {caso.motivo}{donde}."
        return Veredicto(
            id_caso=caso.id_caso if caso.id_caso is not None else f"#{caso.posicion}",
            estado=ESTADO_REVISION,
            etiqueta=self.reglas.etiqueta(ESTADO_REVISION),
            indice=0.0,
            diagnostico=motivo,
            errores=[motivo],
        )

    def auditar_lote(self, casos: list[Caso | CasoInvalido]) -> list[Veredicto]:
        veredictos = []
        for caso in casos:
            if isinstance(caso, CasoInvalido):
                veredictos.append(self.veredicto_invalido(caso))
                continue
            try:
                veredictos.append(self.auditar(caso))
            except Exception as exc:  # un caso defectuoso no detiene el lote
                log.exception("Fallo inesperado auditando el caso %s", caso.id_caso)
                veredictos.append(
                    self.veredicto_invalido(CasoInvalido(caso.id_caso, -1, f"{type(exc).__name__}: {exc}"))
                )
        return veredictos
