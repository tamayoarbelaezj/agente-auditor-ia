import json

import pytest

from auditor.config import cargar_reglas, construir_reglas
from auditor.controles import REGISTRO
from auditor.entrada import cargar_casos, parsear_casos
from auditor.excepciones import ConfigError, EntradaError
from auditor.modelos import Caso, EstadoControl
from auditor.motor import Auditor


def test_archivo_casos_inexistente(tmp_path):
    with pytest.raises(EntradaError, match="No existe"):
        cargar_casos(tmp_path / "nada.json")


def test_json_mal_formado(tmp_path):
    ruta = tmp_path / "casos.json"
    ruta.write_text('[{"id_caso": 1,', encoding="utf-8")
    with pytest.raises(EntradaError, match="línea 1"):
        cargar_casos(ruta)


def test_raiz_no_lista():
    with pytest.raises(EntradaError):
        parsear_casos({"id_caso": 1})


def test_casos_invalidos_no_detienen_el_lote(auditor, casos_dict):
    lote = [
        casos_dict[0],
        {"id_caso": 2, "contexto_rag": "x"},  # falta respuesta
        {"id_caso": 3, "contexto_rag": "  ", "respuesta_agent_b": "y"},  # vacío
        "no soy un objeto",
        dict(casos_dict[0]),  # id duplicado
    ]
    veredictos = auditor.auditar_lote(parsear_casos(lote))
    assert [v.estado for v in veredictos] == ["CONFORME"] + ["REVISION_MANUAL"] * 4
    assert "respuesta_agent_b" in veredictos[1].diagnostico
    assert all(v.indice == 0.0 for v in veredictos[1:])


def test_reglas_inexistentes(tmp_path):
    with pytest.raises(ConfigError):
        cargar_reglas(tmp_path / "reglas.json")


@pytest.mark.parametrize(
    ("mutar", "mensaje"),
    [
        (lambda d: d["controles"][0].update(tipo="inventado"), "tipo' desconocido"),
        (lambda d: d["patrones"].update(monto="(sin cerrar"), "Regex inválida"),
        (lambda d: d["controles"][1].update(severidad="GRAVISIMO"), "severidad' inválida"),
        (lambda d: d["controles"][2].update(id="CTRL-00"), "duplicado"),
        (lambda d: d["patrones"].pop("monto"), "patrones.monto"),
        (lambda d: d["severidades"]["orden"].remove("REVISION_MANUAL"), "REVISION_MANUAL"),
    ],
)
def test_reglas_invalidas(reglas_mod, mutar, mensaje):
    mutar(reglas_mod)
    with pytest.raises(ConfigError, match=mensaje):
        construir_reglas(reglas_mod)


def test_control_que_falla_queda_indeterminado(reglas, monkeypatch):
    def explota(ctx):
        raise RuntimeError("boom")

    monkeypatch.setitem(REGISTRO, "tope_cobertura", explota)
    v = Auditor(reglas).auditar(
        Caso(1, "Cobertura máxima: $1,200 USD.", "Procedemos con la cobertura por $900 USD.")
    )
    ctrl = next(r for r in v.resultados if r.id == "CTRL-01")
    assert ctrl.estado is EstadoControl.INDETERMINADO
    assert v.estado == "REVISION_MANUAL"


def test_reglas_json_real_es_valido(reglas):
    assert {c.tipo for c in reglas.controles} <= set(REGISTRO)
    json.dumps(reglas.version)
