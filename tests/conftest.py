import copy
import json
from pathlib import Path

import pytest

from auditor.config import cargar_reglas
from auditor.entrada import cargar_casos
from auditor.motor import Auditor

RAIZ = Path(__file__).resolve().parents[1]
RUTA_REGLAS = RAIZ / "reglas.json"
RUTA_CASOS = RAIZ / "data" / "casos.json"
RUTA_CALIBRACION = RAIZ / "data" / "casos_calibracion.json"


@pytest.fixture(scope="session")
def reglas_dict():
    return json.loads(RUTA_REGLAS.read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def reglas():
    return cargar_reglas(RUTA_REGLAS)


@pytest.fixture
def reglas_mod(reglas_dict):
    """Copia editable de reglas.json; se compila con construir_reglas()."""
    return copy.deepcopy(reglas_dict)


@pytest.fixture(scope="session")
def casos_dict():
    return json.loads(RUTA_CASOS.read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def casos_calibracion_dict():
    return json.loads(RUTA_CALIBRACION.read_text(encoding="utf-8"))


@pytest.fixture
def auditor(reglas):
    return Auditor(reglas)


@pytest.fixture(scope="session")
def veredictos(reglas):
    casos, _ = cargar_casos(RUTA_CASOS)
    return {v.id_caso: v for v in Auditor(reglas).auditar_lote(casos)}

