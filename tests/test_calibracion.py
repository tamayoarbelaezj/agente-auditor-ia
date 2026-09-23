"""La calibración es parte del control: si se degrada, la suite debe avisar."""

import pytest

from auditor.entrada import parsear_casos

from .conftest import RUTA_CALIBRACION, RUTA_REGLAS

calibrar = pytest.importorskip("tools.calibrar")


@pytest.fixture(scope="module")
def corrida(reglas_dict_modulo, casos_modulo, etiquetas):
    indices = {k: v.indice for k, v in calibrar.auditar(reglas_dict_modulo, casos_modulo, "semantico").items()}
    return indices, calibrar.barrido(indices, etiquetas)


@pytest.fixture(scope="module")
def reglas_dict_modulo():
    import json

    return json.loads(RUTA_REGLAS.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def crudos():
    import json

    return json.loads(RUTA_CALIBRACION.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def casos_modulo(crudos):
    return parsear_casos(crudos)


@pytest.fixture(scope="module")
def etiquetas(crudos):
    return {c["id_caso"]: c["etiqueta_esperada"] for c in crudos}


def test_f1_alto_en_el_umbral_configurado(corrida, reglas_dict_modulo, etiquetas):
    indices, _ = corrida
    umbral = reglas_dict_modulo["fidelidad"]["umbral_revision"]
    medida = calibrar.medir(indices, etiquetas, umbral)
    # No se exige 1.0: con 11 casos sería sobreajuste disfrazado de rigor.
    assert medida.f1 >= 0.9
    assert medida.recall >= 0.9


def test_umbral_configurado_dentro_de_la_meseta(corrida, reglas_dict_modulo):
    _, medidas = corrida
    optimos, ancho = calibrar.meseta(medidas)
    umbral = reglas_dict_modulo["fidelidad"]["umbral_revision"]
    assert min(optimos) <= umbral <= max(optimos)
    assert ancho >= 0.10


def test_orden_estricto_entre_fieles_e_infieles(corrida, etiquetas):
    indices, _ = corrida
    fieles = [v for k, v in indices.items() if etiquetas[k] == "FIEL"]
    infieles = [v for k, v in indices.items() if etiquetas[k] == "NO_FIEL"]
    assert min(fieles) > max(infieles)


def test_sensibilidad_no_cambia_clasificaciones(reglas_dict_modulo, casos_modulo, etiquetas):
    umbral = reglas_dict_modulo["fidelidad"]["umbral_revision"]
    cambios = calibrar.sensibilidad(reglas_dict_modulo, casos_modulo, etiquetas, umbral)
    assert all(n == 0 for _, n in cambios), cambios
