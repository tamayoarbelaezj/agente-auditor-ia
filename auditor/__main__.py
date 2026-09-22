"""CLI del Agente Auditor.

Uso:
    python -m auditor --casos data/casos.json --reglas reglas.json \
        --salida salida/reporte.txt --json salida/reporte.json
"""

from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Sequence

from . import __version__
from .config import cargar_reglas
from .entrada import cargar_casos
from .excepciones import AuditorError
from .fidelidad import EVALUADORES, crear_evaluador
from .motor import Auditor
from .reporte import construir_json, escribir, escribir_json, formatear_reporte

EXIT_OK = 0
EXIT_ERROR_ENTRADA = 2

log = logging.getLogger("auditor")


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m auditor",
        description="Agent A: audita las decisiones de Agent B contra reglas de negocio, seguridad y riesgo.",
    )
    p.add_argument("--casos", default="data/casos.json", help="JSON con los logs de Agent B")
    p.add_argument("--reglas", default="reglas.json", help="archivo de configuración de controles")
    p.add_argument("--salida", default="salida/reporte.txt", help="reporte de texto (formato del reto)")
    p.add_argument("--json", default="salida/reporte.json", help="reporte JSON de trazabilidad")
    p.add_argument("--evaluador", default="provisional", choices=sorted(EVALUADORES),
                   help="algoritmo del Índice de Fidelidad Analítica")
    p.add_argument("--log-level", default="WARNING",
                   choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return p


def _configurar_consola() -> None:
    # La consola de Windows usa cp1252 por defecto; el reporte lleva tildes.
    for flujo in (sys.stdout, sys.stderr):
        if hasattr(flujo, "reconfigure"):
            flujo.reconfigure(encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    _configurar_consola()
    logging.basicConfig(level=args.log_level, format="%(levelname)s %(name)s: %(message)s")

    try:
        reglas = cargar_reglas(args.reglas)
        casos, sha_casos = cargar_casos(args.casos)
    except AuditorError as exc:
        log.error("%s", exc)
        return EXIT_ERROR_ENTRADA

    auditor = Auditor(reglas, crear_evaluador(args.evaluador, reglas))
    veredictos = auditor.auditar_lote(casos)

    texto = formatear_reporte(veredictos)
    print(texto, end="")
    try:
        escribir(args.salida, texto)
        escribir_json(
            args.json,
            construir_json(
                veredictos,
                {
                    "version_auditor": __version__,
                    "version_reglas": reglas.version,
                    "evaluador_fidelidad": args.evaluador,
                    "archivo_casos": str(args.casos),
                    "sha256_casos": sha_casos,
                    "archivo_reglas": str(args.reglas),
                    "sha256_reglas": reglas.sha256,
                },
            ),
        )
    except OSError as exc:
        log.error("No se pudo escribir el reporte: %s", exc)
        return EXIT_ERROR_ENTRADA
    log.info("Reportes escritos en %s y %s", args.salida, args.json)
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
