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
        # Paráfrasis de aprobación (claves ampliadas)
        ("Reconocemos el arreglo del vidrio por $900, descontando el 10% pactado.", "APROBACION"),
        ("Autorizamos el reembolso del servicio.", "APROBACION"),
        ("Cubrimos el valor del siniestro reportado.", "APROBACION"),
        # Las formas negadas de esas mismas claves no pueden leerse como aprobación
        ("No cubrimos este siniestro.", "RECHAZO"),
        ("No procede la cobertura solicitada.", "RECHAZO"),
        ("No autorizamos el reembolso.", "RECHAZO"),
        ("No reconocemos el valor reclamado.", "RECHAZO"),
    ],
)
def test_clasificar_accion(reglas, respuesta, esperada):
    assert clasificar_accion(normalizar(respuesta), reglas).tipo == esperada


def test_accion_desconocida_exige_revision(auditor):
    from auditor.modelos import Caso

    v = auditor.auditar(Caso(1, "Póliza Hogar.", "Gracias por escribirnos."))
    assert v.estado == "REVISION_MANUAL"
