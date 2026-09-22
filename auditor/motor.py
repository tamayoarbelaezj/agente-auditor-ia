"""Orquestación de la auditoría: extracción → acción → controles → estado → índice."""

from __future__ import annotations

import logging

from .acciones import clasificar_accion
from .config import ESTADO_CONFORME, ESTADO_REVISION, Reglas
from .controles import REGISTRO, ContextoControl
from .extraccion import Extractor
from .fidelidad import EvaluadorFidelidad, EvaluadorProvisional
from .modelos import Caso, CasoInvalido, EstadoControl, ResultadoControl, Veredicto
from .normalizacion import normalizar

log = logging.getLogger(__name__)


class Auditor:
    """Agente Auditor (Agent A)."""

    def __init__(self, reglas: Reglas, evaluador: EvaluadorFidelidad | None = None) -> None:
        self.reglas = reglas
        self.evaluador = evaluador or EvaluadorProvisional(reglas)
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
        estado = self.resolver_estado(resultados)
        return Veredicto(
            id_caso=caso.id_caso,
            estado=estado,
            etiqueta=self.reglas.etiqueta(estado),
            indice=self.evaluador.puntuar(caso, extraccion, resultados),
            diagnostico=self._diagnostico(resultados) or "Sin controles aplicables.",
            accion=accion,
            extraccion=extraccion,
            resultados=resultados,
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
