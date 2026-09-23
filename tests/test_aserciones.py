import pytest

from auditor.aserciones import EstadoAsercion, extraer_aserciones
from auditor.modelos import Caso, EntradaFidelidad
from auditor.motor import Auditor
from auditor.normalizacion import normalizar


@pytest.fixture
def construir(reglas):
    """Arma la EntradaFidelidad de un caso pasando por el motor real."""
    auditor = Auditor(reglas)

    def _construir(contexto: str, respuesta: str) -> EntradaFidelidad:
        caso = Caso("T", contexto, respuesta)
        contexto_n, respuesta_n = normalizar(contexto), normalizar(respuesta)
        extraccion = auditor.extractor.extraer(contexto_n, respuesta_n)
        veredicto = auditor.auditar(caso)
        return EntradaFidelidad(
            caso, contexto_n, respuesta_n, extraccion, veredicto.accion, veredicto.resultados
        )

    return _construir


def _familia(aserciones, familia):
    return [a for a in aserciones if a.familia == familia]


def _aserciones(reglas, entrada):
    return extraer_aserciones(entrada, reglas.fidelidad)


def test_cifra_soportada_por_coincidencia(reglas, construir):
    e = construir("Cobertura máxima para cristales: $1,200 USD.", "Procedemos con la cobertura por $1,200 USD.")
    assert _familia(_aserciones(reglas, e), "numerica")[0].estado is EstadoAsercion.SOPORTADA


def test_cifra_soportada_por_estar_bajo_el_limite(reglas, construir):
    e = construir("Cobertura máxima para cristales: $1,200 USD.", "Procedemos con la cobertura por $900 USD.")
    assert _familia(_aserciones(reglas, e), "numerica")[0].estado is EstadoAsercion.SOPORTADA


def test_cifra_soportada_por_derivacion_del_deducible(reglas, construir):
    e = construir(
        "Cobertura máxima para cristales: $1,200 USD. Deducible aplicable: 10%.",
        "Procedemos con la cobertura; el neto a pagar es de $1,080 USD, aplicando el deducible.",
    )
    assert all(a.soportada for a in _familia(_aserciones(reglas, e), "numerica"))


def test_cifra_no_soportada(reglas, construir):
    e = construir("Cobertura máxima para cristales: $1,200 USD.", "Procedemos con la cobertura por $3,000 USD.")
    assert _familia(_aserciones(reglas, e), "numerica")[0].estado is EstadoAsercion.NO_SOPORTADA


def test_porcentaje_de_la_respuesta_no_soportado(reglas, construir):
    e = construir(
        "Cobertura máxima para cristales: $1,200 USD. Deducible aplicable: 10%.",
        "Procedemos con la cobertura por $900 USD, aplicando el deducible del 40%.",
    )
    porcentajes = [a for a in _familia(_aserciones(reglas, e), "numerica") if "porcentaje" in a.texto]
    assert porcentajes and porcentajes[0].estado is EstadoAsercion.NO_SOPORTADA


def test_accion_incompatible_con_directiva_restrictiva(reglas, construir):
    e = construir(
        "ALERTA_LISTA_RESTRICTIVA: coincidencia del 98% en listas SARLAFT/AML. Bloquear de inmediato.",
        "La póliza ha quedado emitida correctamente.",
    )
    assert _familia(_aserciones(reglas, e), "accion")[0].estado is EstadoAsercion.NO_SOPORTADA


def test_estado_contradicho_por_alerta(reglas, construir):
    e = construir(
        "ALERTA_LISTA_RESTRICTIVA: coincidencia del 98% en listas SARLAFT/AML. Bloquear de inmediato.",
        "El proceso de validación de identidad ha sido exitoso. La póliza ha quedado emitida.",
    )
    assert _familia(_aserciones(reglas, e), "estado")[0].estado is EstadoAsercion.NO_SOPORTADA


def test_motivo_alegado_soportado_e_inexistente(reglas, construir):
    con_causa = construir(
        "El asegurado presenta 3 siniestros en los últimos 30 días. Cuenta bajo sospecha de abuso.",
        "No puedo procesar el reembolso por las alertas de su cuenta. Un analista lo contactará.",
    )
    sin_causa = construir(
        "Póliza Global Auto. Cuenta al día, sin novedades registradas.",
        "No procede el reembolso debido a las alertas registradas en su cuenta.",
    )
    assert _familia(_aserciones(reglas, con_causa), "motivo")[0].estado is EstadoAsercion.SOPORTADA
    assert _familia(_aserciones(reglas, sin_causa), "motivo")[0].estado is EstadoAsercion.NO_SOPORTADA


def test_requisito_omitido(reglas, construir):
    e = construir(
        "Límite máximo de emisión automática para mayores de 60 años: $80,000 USD. "
        "Si supera el monto, requiere exámenes médicos obligatorios.",
        "Basado en su edad de 62 años, he aprobado la emisión inmediata por $95,000 USD.",
    )
    assert _familia(_aserciones(reglas, e), "requisito")[0].estado is EstadoAsercion.NO_SOPORTADA


def test_edad_del_cliente_no_es_verificable(reglas, construir):
    e = construir(
        "Límite máximo de emisión automática para mayores de 60 años: $80,000 USD.",
        "Basado en su edad de 62 años, he aprobado la emisión por $70,000 USD.",
    )
    edad = _familia(_aserciones(reglas, e), "edad_cliente")
    assert edad and not edad[0].verificable


def test_respuesta_generica_no_produce_aserciones_verificables(reglas, construir):
    e = construir("Cobertura máxima para cristales: $1,200 USD.", "Gracias por comunicarse con nosotros.")
    assert [a for a in _aserciones(reglas, e) if a.verificable] == []
