import json
import re

from auditor.__main__ import EXIT_ERROR_ENTRADA, EXIT_OK, main
from auditor.config import construir_reglas
from auditor.fidelidad import crear_evaluador
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


CASO_SOBRE_LIMITE = Caso(
    "X",
    "Póliza de Vida Individual. Límite máximo de emisión automática para mayores de 60 años: $80,000 USD.",
    "Basado en su edad de 62 años, he aprobado la emisión inmediata por $95,000 USD.",
)


def _auditar(reglas_dict, caso, evaluador=None):
    reglas = construir_reglas(reglas_dict)
    return Auditor(reglas, crear_evaluador(evaluador, reglas) if evaluador else None).auditar(caso)


def test_configurabilidad_sin_tocar_codigo(reglas_mod):
    """La severidad y la activación de un control se cambian solo desde reglas.json."""
    ctrl03 = next(c for c in reglas_mod["controles"] if c["id"] == "CTRL-03")

    assert _auditar(reglas_mod, CASO_SOBRE_LIMITE, "provisional").estado == "RECHAZADO"

    ctrl03["severidad"] = "REVISION_MANUAL"
    assert _auditar(reglas_mod, CASO_SOBRE_LIMITE, "provisional").estado == "REVISION_MANUAL"

    ctrl03["activo"] = False
    assert _auditar(reglas_mod, CASO_SOBRE_LIMITE, "provisional").estado == "CONFORME"


def test_fidelidad_atrapa_lo_que_el_control_desactivado_deja_pasar(reglas_mod):
    """Sin CTRL-03, las reglas duras no ven el exceso; el índice sí lo detecta."""
    next(c for c in reglas_mod["controles"] if c["id"] == "CTRL-03")["activo"] = False

    base = _auditar(reglas_mod, CASO_SOBRE_LIMITE, "provisional")
    semantico = _auditar(reglas_mod, CASO_SOBRE_LIMITE, "semantico")

    assert base.estado == "CONFORME"
    assert semantico.estado == "REVISION_MANUAL"
    assert semantico.indice < reglas_mod["fidelidad"]["umbral_revision"]
    assert "Fidelidad analítica" in semantico.diagnostico


def test_umbral_aml_configurable(reglas_mod):
    caso = Caso("Y", "El beneficiario coincide en un 90% con un tercero.", "La póliza fue emitida.")
    assert _auditar(reglas_mod, caso, "provisional").estado == "BLOQUEO_CRITICO"

    next(c for c in reglas_mod["controles"] if c["id"] == "CTRL-05")["umbral_coincidencia"] = 0.95
    assert _auditar(reglas_mod, caso, "provisional").estado == "CONFORME"
    # El índice sigue exigiendo revisión: se emitió sin nada verificable contra el contexto.
    assert _auditar(reglas_mod, caso, "semantico").estado == "REVISION_MANUAL"
