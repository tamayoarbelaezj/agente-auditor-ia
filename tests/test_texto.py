import pytest

from auditor.normalizacion import normalizar
from auditor.texto import coseno_tf, tokenizar

STOP = {"de", "la", "el"}


def test_tokeniza_separando_simbolos():
    assert set(tokenizar(normalizar("Cobertura: $1,200 USD (SARLAFT/AML)."))) == {
        "cobertura",
        "200",
        "usd",
        "sarlaft",
        "aml",
    }


def test_descarta_stopwords_y_tokens_cortos():
    tokens = tokenizar(normalizar("El deducible de la póliza"), STOP, 3)
    assert set(tokens) == {"deducible", "poliza"}


def test_invariante_a_tildes_y_mayusculas():
    assert tokenizar(normalizar("PÓLIZA Médica")) == tokenizar(normalizar("poliza medica"))


def test_coseno_identico_disjunto_y_simetrico():
    a = tokenizar(normalizar("cobertura maxima para cristales"))
    b = tokenizar(normalizar("cobertura maxima para cristales"))
    c = tokenizar(normalizar("beneficiario listas restrictivas"))
    assert coseno_tf(a, b) == pytest.approx(1.0)
    assert coseno_tf(a, c) == 0.0
    assert coseno_tf(a, c) == coseno_tf(c, a)


def test_texto_vacio_no_revienta():
    assert coseno_tf(tokenizar(""), tokenizar(normalizar("algo de texto"))) == 0.0


def test_el_puntaje_no_depende_del_lote(reglas, casos_calibracion_dict):
    """Sin IDF, auditar un caso solo o dentro del lote da el mismo índice."""
    from auditor.entrada import parsear_casos
    from auditor.motor import Auditor

    auditor = Auditor(reglas)
    en_lote = {v.id_caso: v.indice for v in auditor.auditar_lote(parsear_casos(casos_calibracion_dict))}
    for crudo in casos_calibracion_dict:
        solo = auditor.auditar_lote(parsear_casos([crudo]))[0]
        assert solo.indice == en_lote[crudo["id_caso"]]
