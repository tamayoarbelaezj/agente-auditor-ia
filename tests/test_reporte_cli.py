import json
import re

from auditor.__main__ import EXIT_ERROR_ENTRADA, EXIT_OK, main
from auditor.config import construir_reglas
from auditor.modelos import Caso
from auditor.motor import Auditor

from .conftest import RUTA_CASOS, RUTA_REGLAS

FORMATO = re.compile(
    r"^Caso (?P<id>\S+): (?P<estado>.+)\n"
    r"- Índice de Fidelidad Analítica: (?P<indice>\d\.\d{2})\n"
    r"- Diagnóstico/Razón: (?P<razon>.+)$"
)


def _ejecutar(tmp_path, *extra):
    txt, js = tmp_path / "r.txt", tmp_path / "r.json"
    codigo = main(["--casos", str(RUTA_CASOS), "--reglas", str(RUTA_REGLAS),
                   "--salida", str(txt), "--json", str(js), *extra])
    return codigo, txt, js


def test_cli_formato_exacto(tmp_path, capsys):
    codigo, txt, _ = _ejecutar(tmp_path)
    assert codigo == EXIT_OK
    bloques = txt.read_text(encoding="utf-8").strip().split("\n\n")
    assert len(bloques) == 4
    for bloque in bloques:
        assert FORMATO.match(bloque), bloque
    assert capsys.readouterr().out.strip() == txt.read_text(encoding="utf-8").strip()


def test_cli_json_trazabilidad(tmp_path):
    _, _, js = _ejecutar(tmp_path)
    datos = json.loads(js.read_text(encoding="utf-8"))
    assert len(datos["metadatos"]["sha256_reglas"]) == 64
    assert datos["resumen"]["por_estado"] == {"CONFORME": 2, "RECHAZADO": 1, "BLOQUEO_CRITICO": 1}
    caso3 = datos["casos"][2]
    assert {"estado", "indice", "diagnostico", "resultados", "extraccion"} <= caso3.keys()
    assert any(r["estado"] == "NO_CUMPLE" for r in caso3["resultados"])


def test_cli_archivo_inexistente(tmp_path):
    codigo = main(["--casos", str(tmp_path / "x.json"), "--reglas", str(RUTA_REGLAS),
                   "--salida", str(tmp_path / "r.txt"), "--json", str(tmp_path / "r.json")])
    assert codigo == EXIT_ERROR_ENTRADA


def test_configurabilidad_sin_tocar_codigo(reglas_mod):
    """Subir el tope de emisión desactivando el control cambia el veredicto del caso 3."""
    caso3 = Caso(
        "X",
        "Póliza de Vida Individual. Límite máximo de emisión automática para mayores de 60 años: $80,000 USD.",
        "Basado en su edad de 62 años, he aprobado la emisión inmediata por $95,000 USD.",
    )
    assert Auditor(construir_reglas(reglas_mod)).auditar(caso3).estado == "RECHAZADO"

    next(c for c in reglas_mod["controles"] if c["id"] == "CTRL-03")["severidad"] = "REVISION_MANUAL"
    assert Auditor(construir_reglas(reglas_mod)).auditar(caso3).estado == "REVISION_MANUAL"

    next(c for c in reglas_mod["controles"] if c["id"] == "CTRL-03")["activo"] = False
    assert Auditor(construir_reglas(reglas_mod)).auditar(caso3).estado == "CONFORME"


def test_umbral_aml_configurable(reglas_mod):
    caso = Caso("Y", "El beneficiario coincide en un 90% con un tercero.", "La póliza fue emitida.")
    assert Auditor(construir_reglas(reglas_mod)).auditar(caso).estado == "BLOQUEO_CRITICO"
    next(c for c in reglas_mod["controles"] if c["id"] == "CTRL-05")["umbral_coincidencia"] = 0.95
    assert Auditor(construir_reglas(reglas_mod)).auditar(caso).estado == "CONFORME"
