import random

import pytest

from auditor.entrada import parsear_casos
from auditor.modelos import EstadoControl


def _control(veredicto, cid):
    return next(r for r in veredicto.resultados if r.id == cid)


@pytest.mark.parametrize(
    ("id_caso", "estado", "minimo", "maximo"),
    [
        (1, "CONFORME", 0.93, 1.00),
        (2, "CONFORME", 0.85, 0.95),
        (3, "RECHAZADO", 0.10, 0.25),
        (4, "BLOQUEO_CRITICO", 0.00, 0.05),
    ],
)
def test_veredicto_esperado(veredictos, id_caso, estado, minimo, maximo):
    """Se asertan rangos, no constantes frágiles (ver 2.2.md §1.6)."""
    v = veredictos[id_caso]
    assert v.estado == estado
    assert minimo <= v.indice <= maximo


def test_orden_estricto_de_fidelidad(veredictos):
    indices = [veredictos[i].indice for i in (1, 2, 3, 4)]
    assert indices[3] < indices[2] < indices[1] <= indices[0]


def test_caso1_tope_y_deducible(veredictos):
    v = veredictos[1]
    tope = _control(v, "CTRL-01")
    assert tope.estado is EstadoControl.CUMPLE
    assert (tope.evidencia["monto"], tope.evidencia["limite"]) == (900, 1200)
    ded = _control(v, "CTRL-02")
    assert ded.estado is EstadoControl.CUMPLE
    assert ded.evidencia["neto"] == pytest.approx(810)


def test_caso2_fraude_escalado(veredictos):
    v = veredictos[2]
    assert v.accion.tipo == "ESCALAMIENTO"
    fraude = _control(v, "CTRL-04")
    assert fraude.estado is EstadoControl.CUMPLE
    assert fraude.evidencia["por_frecuencia"] is True


def test_caso3_exceso_limite_emision(veredictos):
    c = _control(veredictos[3], "CTRL-03")
    assert c.estado is EstadoControl.NO_CUMPLE
    assert c.evidencia["exceso"] == pytest.approx(15000)
    assert c.evidencia["edad"] == 62 and c.evidencia["umbral"] == 60
    assert c.evidencia["requisito_mencionado"] == []


def test_caso4_aml_y_alucinacion(veredictos):
    v = veredictos[4]
    aml = _control(v, "CTRL-05")
    assert aml.estado is EstadoControl.NO_CUMPLE
    assert aml.evidencia["coincidencia"] == pytest.approx(0.98)
    assert _control(v, "CTRL-06").estado is EstadoControl.NO_CUMPLE


def test_veredictos_no_dependen_del_id_ni_del_orden(auditor, casos_dict, veredictos):
    esperado = {c["contexto_rag"]: veredictos[c["id_caso"]].estado for c in casos_dict}
    mezclados = [dict(c, id_caso=100 + i * 7) for i, c in enumerate(casos_dict)]
    random.Random(42).shuffle(mezclados)
    for v, c in zip(auditor.auditar_lote(parsear_casos(mezclados)), mezclados):
        assert v.estado == esperado[c["contexto_rag"]]
