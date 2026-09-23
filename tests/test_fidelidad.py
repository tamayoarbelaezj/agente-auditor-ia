import pytest

from auditor.config import construir_reglas
from auditor.entrada import parsear_casos
from auditor.fidelidad import COBERTURA_INSUFICIENTE, EVALUADORES, crear_evaluador
from auditor.modelos import Caso
from auditor.motor import Auditor

CONTEXTO_AUTO = "Póliza Global Auto. Cobertura máxima para rotura de cristales: $1,200 USD. Deducible aplicable: 10%."


@pytest.fixture
def calibracion(reglas, casos_calibracion_dict):
    return {v.id_caso: v for v in Auditor(reglas).auditar_lote(parsear_casos(casos_calibracion_dict))}


def test_registro_de_evaluadores(reglas):
    assert set(EVALUADORES) == {"provisional", "semantico"}
    assert reglas.fidelidad.evaluador_por_defecto == "semantico"
    assert Auditor(reglas).evaluador.nombre == "semantico"


def test_indice_en_rango(calibracion):
    assert all(0.0 <= v.indice <= 1.0 for v in calibracion.values())


def test_componentes_publicados(calibracion):
    fid = calibracion[1].fidelidad
    assert set(fid["componentes"]) >= {"C", "A", "T", "P", "A_independiente"}
    assert fid["pesos_efectivos"]["cumplimiento"] == pytest.approx(0.45)
    assert fid["anclaje_por_familia"]["numerica"]["verificables"] >= 1
    assert all("motivo" in a for a in fid["aserciones"])


def test_compatibilidad_del_evaluador_provisional(reglas, casos_dict):
    auditor = Auditor(reglas, crear_evaluador("provisional", reglas))
    indices = [v.indice for v in auditor.auditar_lote(parsear_casos(casos_dict))]
    assert indices == [1.00, 1.00, 0.30, 0.13]


def test_monotonia_quitar_evidencia_no_sube_el_indice(reglas):
    auditor = Auditor(reglas)
    respuesta = "Procedemos con la cobertura por $900 USD, aplicando el deducible."
    con_evidencia = auditor.auditar(Caso("A", CONTEXTO_AUTO, respuesta)).indice
    sin_limite = auditor.auditar(Caso("B", "Póliza Global Auto vigente.", respuesta)).indice
    assert sin_limite <= con_evidencia


def test_agregar_una_alerta_no_sube_el_indice(reglas):
    auditor = Auditor(reglas)
    respuesta = "La póliza ha quedado emitida correctamente y la validación fue exitosa."
    limpio = auditor.auditar(Caso("A", "Póliza de Vida Individual vigente.", respuesta)).indice
    alertado = auditor.auditar(
        Caso("B", "Póliza de Vida Individual. ALERTA_LISTA_RESTRICTIVA: bloquear de inmediato.", respuesta)
    ).indice
    assert alertado <= limpio


def test_determinismo(reglas, casos_dict):
    a = [v.indice for v in Auditor(reglas).auditar_lote(parsear_casos(casos_dict))]
    b = [v.indice for v in Auditor(reglas).auditar_lote(parsear_casos(casos_dict))]
    assert a == b


def test_invariante_a_tildes_y_mayusculas(reglas):
    auditor = Auditor(reglas)
    original = auditor.auditar(
        Caso("A", CONTEXTO_AUTO, "Procedemos con la cobertura por $900 USD, aplicando el deducible.")
    )
    gritado = auditor.auditar(
        Caso("B", CONTEXTO_AUTO.upper(), "PROCEDEMOS CON LA COBERTURA POR $900 USD, APLICANDO EL DEDUCIBLE.")
    )
    assert original.indice == gritado.indice


def test_el_vacio_no_puntua(reglas):
    """Aprobar sin aserciones verificables no puede quedar CONFORME."""
    v = Auditor(reglas).auditar(
        Caso("X", "Póliza de Hogar Integral vigente.", "Procedemos con el reembolso solicitado.")
    )
    assert v.fidelidad["cobertura_evidencia"] == COBERTURA_INSUFICIENTE
    assert v.estado == "REVISION_MANUAL"
    assert "sin aserciones verificables" in v.diagnostico


def test_pesos_renormalizados_suman_uno(reglas):
    v = Auditor(reglas).auditar(
        Caso("X", "Póliza de Hogar Integral vigente.", "Procedemos con el reembolso solicitado.")
    )
    assert sum(v.fidelidad["pesos_efectivos"].values()) == pytest.approx(1.0)


def test_umbral_eleva_a_revision_manual(calibracion, reglas):
    v = calibracion[11]
    assert v.estado == "REVISION_MANUAL"
    assert v.indice < reglas.fidelidad.umbral_revision
    assert "Fidelidad analítica" in v.diagnostico


def test_el_indice_nunca_relaja_una_severidad(calibracion):
    assert calibracion[4].estado == "BLOQUEO_CRITICO"
    assert calibracion[3].estado == "RECHAZADO"


def test_penalizacion_acotada_por_el_tope(calibracion, reglas):
    assert calibracion[4].fidelidad["componentes"]["P"] == pytest.approx(
        reglas.fidelidad.penalizaciones["tope"]
    )


def test_fail_safe_si_el_evaluador_falla(reglas):
    class Roto:
        nombre = "roto"

        def puntuar(self, entrada):
            raise RuntimeError("boom")

    v = Auditor(reglas, Roto()).auditar(
        Caso("X", CONTEXTO_AUTO, "Procedemos con la cobertura por $900 USD, aplicando el deducible.")
    )
    assert v.indice == 0.0
    assert v.estado == "REVISION_MANUAL"
    assert "error" in v.fidelidad["componentes"]


@pytest.mark.parametrize(
    ("mutar", "mensaje"),
    [
        (lambda f: f["pesos"].update(anclaje=0.9), "debe sumar 1.0"),
        (lambda f: f.update(umbral_revision=1.5), "umbral_revision"),
        (lambda f: f["texto"].update(backend="magia"), "backend"),
        (lambda f: f["texto"].update(cos_referencia=0), "cos_referencia"),
        (lambda f: f.update(evaluador_por_defecto="inventado"), "evaluador_por_defecto"),
        (lambda f: f["penalizaciones"].update(tope=1.5), "penalizaciones.tope"),
    ],
)
def test_configuracion_invalida(reglas_mod, mutar, mensaje):
    from auditor.excepciones import ConfigError

    mutar(reglas_mod["fidelidad"])
    with pytest.raises(ConfigError, match=mensaje):
        construir_reglas(reglas_mod)


def test_auditor_no_depende_de_librerias_externas():
    """El MVP corre con la librería estándar: nada de ragas ni embeddings."""
    import pkgutil

    import auditor

    prohibidas = ("ragas", "sentence_transformers", "langchain", "sklearn", "numpy")
    for modulo in pkgutil.iter_modules(auditor.__path__):
        fuente = (auditor.__path__[0] + "/" + modulo.name + ".py")
        with open(fuente, encoding="utf-8") as f:
            texto = f.read()
        assert not any(f"import {p}" in texto for p in prohibidas), modulo.name
