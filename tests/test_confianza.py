import pytest

from auditor.confianza import (
    PESOS_CONFIANZA,
    UMBRAL_BANDA_ALTA,
    UMBRAL_BANDA_MEDIA,
    confianza_decision,
    similitud_semantica,
)
from auditor.modelos import Caso
from auditor.normalizacion import normalizar

CONTEXTO_AUTO = "Póliza Global Auto. Cobertura máxima para rotura de cristales: $1,200 USD. Deducible aplicable: 10%."
CON_EVIDENCIA = "Procedemos con la cobertura del parabrisas por $900 USD, aplicando el deducible."
SIN_EVIDENCIA = "Procedemos con el reembolso solicitado."
GENERICA = "Gracias por comunicarse con nosotros."


def _banda_esperada(valor: float, cobertura: str = "suficiente") -> str:
    """Sin evidencia contrastable la banda se topa en 'media' (ver `_banda`)."""
    if valor >= UMBRAL_BANDA_ALTA and cobertura == "suficiente":
        return "alta"
    return "media" if valor >= UMBRAL_BANDA_MEDIA else "baja"


# ---------------------------------------------------------------- confianza


@pytest.mark.parametrize("id_caso", [1, 2, 3, 4])
def test_confianza_en_rango_y_banda_coherente(veredictos, reglas, id_caso):
    v = veredictos[id_caso]
    c = confianza_decision(v, reglas)
    assert 0.0 <= c["valor"] <= 1.0
    assert c["banda"] == _banda_esperada(c["valor"], v.fidelidad["cobertura_evidencia"])


def test_sin_evidencia_contrastable_la_banda_no_es_alta(veredictos, reglas):
    """El caso 4 no cita cifras: el número puede ser alto, la banda no."""
    v = veredictos[4]
    c = confianza_decision(v, reglas)
    assert v.fidelidad["cobertura_evidencia"] == "insuficiente"
    assert c["banda"] != "alta"
    assert "no aporta aserciones verificables" in c["explicacion"]


def test_los_factores_suman_el_valor(veredictos, reglas):
    """El puntaje se recalcula a mano desde los factores publicados."""
    for v in veredictos.values():
        c = confianza_decision(v, reglas)
        assert sum(c["factores"].values()) == pytest.approx(c["valor"], abs=1e-4)
        assert set(c["factores"]) <= set(PESOS_CONFIANZA) | {"ajuste_por_advertencias"}
        assert c["explicacion"].strip()


def test_ningun_factor_excede_su_peso(veredictos, reglas):
    for v in veredictos.values():
        for nombre, aporte in confianza_decision(v, reglas)["factores"].items():
            if nombre in PESOS_CONFIANZA:
                assert 0.0 <= aporte <= PESOS_CONFIANZA[nombre] + 1e-9


def test_accion_desconocida_baja_la_confianza(auditor, reglas):
    generico = confianza_decision(auditor.auditar(Caso("X", CONTEXTO_AUTO, GENERICA)), reglas)
    identificado = confianza_decision(auditor.auditar(Caso("Y", CONTEXTO_AUTO, CON_EVIDENCIA)), reglas)
    assert generico["banda"] == "baja"
    assert generico["factores"]["accion_identificada"] == 0.0
    assert generico["valor"] < identificado["valor"]


def test_cobertura_insuficiente_reduce_la_confianza(auditor, reglas):
    con = confianza_decision(auditor.auditar(Caso("A", CONTEXTO_AUTO, CON_EVIDENCIA)), reglas)
    sin = confianza_decision(
        auditor.auditar(Caso("B", "Póliza de Hogar Integral vigente.", SIN_EVIDENCIA)), reglas
    )
    assert sin["factores"]["cobertura_evidencia"] == 0.0
    assert sin["valor"] < con["valor"]


def test_senales_divergentes_reducen_la_confianza(auditor, reglas):
    """Controles conformes pero índice bajo: el auditor duda y lo declara."""
    divergente = auditor.auditar(
        Caso(
            "C",
            "Póliza de Hogar Integral. Amparo de daños por agua incluido.",
            "Procedemos con el reembolso por un valor de $4,500 USD según su cobertura.",
        )
    )
    c = confianza_decision(divergente, reglas)
    assert divergente.indice < reglas.fidelidad.umbral_revision
    assert c["factores"]["consistencia_senales"] < PESOS_CONFIANZA["consistencia_senales"]


def test_confianza_determinista(veredictos, reglas):
    v = veredictos[3]
    assert confianza_decision(v, reglas) == confianza_decision(v, reglas)


# ---------------------------------------------------------------- similitud


def test_similitud_en_rango_y_backend_por_defecto(reglas, casos_dict):
    for caso in casos_dict:
        s = similitud_semantica(caso["contexto_rag"], caso["respuesta_agent_b"], reglas)
        assert 0.0 <= s["valor"] <= 1.0
        assert s["backend"] == "tf"
        assert s["detalle"].strip()


def test_textos_identicos_y_disjuntos(reglas):
    identicos = similitud_semantica(CONTEXTO_AUTO, CONTEXTO_AUTO, reglas)
    disjuntos = similitud_semantica("Cobertura de cristales del vehiculo", "Zanahoria bicicleta", reglas)
    assert identicos["valor"] == pytest.approx(1.0)
    assert disjuntos["valor"] == 0.0
    assert disjuntos["tokens_comunes"] == []


def test_similitud_simetrica(reglas, casos_dict):
    caso = casos_dict[0]
    ida = similitud_semantica(caso["contexto_rag"], caso["respuesta_agent_b"], reglas)
    vuelta = similitud_semantica(caso["respuesta_agent_b"], caso["contexto_rag"], reglas)
    assert ida["valor"] == pytest.approx(vuelta["valor"])


def test_tokens_comunes_son_realmente_comunes(reglas, casos_dict):
    caso = casos_dict[0]
    s = similitud_semantica(caso["contexto_rag"], caso["respuesta_agent_b"], reglas)
    contexto_n, respuesta_n = normalizar(caso["contexto_rag"]), normalizar(caso["respuesta_agent_b"])
    assert s["tokens_comunes"]
    assert len(s["tokens_comunes"]) <= 8
    assert all(t in contexto_n and t in respuesta_n for t in s["tokens_comunes"])


def test_similitud_determinista(reglas, casos_dict):
    caso = casos_dict[2]
    a = similitud_semantica(caso["contexto_rag"], caso["respuesta_agent_b"], reglas)
    b = similitud_semantica(caso["contexto_rag"], caso["respuesta_agent_b"], reglas)
    assert a == b


def test_similitud_sin_dependencias(reglas, casos_dict):
    """El cálculo corre siempre en modo stdlib, sin red ni modelos."""
    caso = casos_dict[0]
    s = similitud_semantica(caso["contexto_rag"], caso["respuesta_agent_b"], reglas)
    assert s["backend"] == "tf"
    assert "librería estándar" in s["detalle"]
