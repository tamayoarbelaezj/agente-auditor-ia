import pytest

from auditor.acciones import clasificar_accion
from auditor.normalizacion import normalizar


@pytest.mark.parametrize(
    ("respuesta", "esperada"),
    [
        ("Procedemos con la cobertura del cambio de parabrisas.", "APROBACION"),
        ("He aprobado la emisión inmediata de su póliza.", "APROBACION"),
        ("La póliza ha quedado emitida correctamente.", "APROBACION"),
        ("Su solicitud fue rechazada.", "RECHAZO"),
        # Prioridad: contiene 'no puedo procesar' y 'un analista' → escalamiento
        ("No puedo procesar este reembolso. Un analista se contactará con usted.", "ESCALAMIENTO"),
        ("Gracias por escribirnos.", "DESCONOCIDA"),
    ],
)
def test_clasificar_accion(reglas, respuesta, esperada):
    assert clasificar_accion(normalizar(respuesta), reglas).tipo == esperada


def test_accion_desconocida_exige_revision(auditor):
    from auditor.modelos import Caso

    v = auditor.auditar(Caso(1, "Póliza Hogar.", "Gracias por escribirnos."))
    assert v.estado == "REVISION_MANUAL"
