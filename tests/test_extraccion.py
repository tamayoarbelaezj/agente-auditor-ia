import pytest

from auditor.extraccion import Extractor, parsear_numero
from auditor.normalizacion import ClaveMatcher, normalizar


@pytest.mark.parametrize(
    ("crudo", "miles", "decimal", "esperado"),
    [
        ("1,200", ",", ".", 1200.0),
        ("95,000", ",", ".", 95000.0),
        ("1,200.50", ",", ".", 1200.5),
        ("1.200,50", ".", ",", 1200.5),
        ("900", ",", ".", 900.0),
    ],
)
def test_parsear_numero(crudo, miles, decimal, esperado):
    assert parsear_numero(crudo, miles, decimal) == esperado


def test_parsear_numero_invalido():
    with pytest.raises(ValueError):
        parsear_numero("1.2.3", ",", ".")


def test_normalizar_tildes_y_mayusculas():
    assert normalizar("  Límite  MÁXIMO de Emisión  ") == "limite maximo de emision"


def test_clave_raiz_y_limite_de_palabra():
    m = ClaveMatcher(["examen* medic*", "aml"])
    assert m.buscar("requiere examenes medicos") == ["examenes medicos"]
    assert m.buscar("proceso amlo") == []


@pytest.fixture
def ext(reglas):
    return Extractor(reglas)


def test_roles_de_monto_y_porcentaje(ext):
    e = ext.extraer(
        normalizar("Cobertura máxima para rotura de cristales: $1,200 USD. Deducible aplicable: 10%."),
        normalizar("Pagamos $900 USD."),
    )
    assert e.monto("limite_cobertura") == 1200
    assert e.monto_maximo("monto_respuesta") == 900
    assert e.porcentaje("deducible") == pytest.approx(0.10)


def test_edad_umbral_vs_edad_cliente(ext):
    e = ext.extraer(
        normalizar("Límite máximo de emisión automática para mayores de 60 años: $80,000 USD."),
        normalizar("Basado en su edad de 62 años, aprobado por $95,000 USD."),
    )
    assert (e.edad_umbral, e.edad_cliente) == (60, 62)
    assert e.monto("limite_emision") == 80000


def test_siniestros_y_ventana(ext):
    e = ext.extraer(normalizar("Historial de 3 siniestros reportados en los últimos 30 días."), "x")
    assert (e.siniestros_conteo, e.siniestros_dias) == (3, 30)


def test_requisito(ext):
    e = ext.extraer(normalizar("Si supera el monto, requiere exámenes médicos obligatorios."), "x")
    assert e.requisitos == ["examenes medicos"]


def test_coincidencia_lista(ext):
    e = ext.extraer(normalizar("El beneficiario coincide en un 98% con listas AML."), "x")
    assert e.porcentaje("coincidencia_lista") == pytest.approx(0.98)


def test_monto_no_parseable_se_registra_como_advertencia(ext):
    e = ext.extraer("tope $1.2.3 usd", "x")
    assert e.montos == {}
    assert e.advertencias
