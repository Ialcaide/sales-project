import datetime
from unittest.mock import patch

import services
from client import SRIError
from models import ComprobanteElectronico, SecuencialSRI


def test_procesar_comprobante_autorizado(session, payload_dict):
    with patch('services.enviar_recepcion', return_value=('RECIBIDA', [])), \
         patch('services.consultar_autorizacion', return_value=(
             'AUTORIZADO', '123456789', datetime.datetime(2026, 7, 15, 10, 0, 0), '<xml/>', [],
         )):
        comprobante = services.procesar_comprobante(session, payload_dict)

    assert comprobante.estado == ComprobanteElectronico.AUTORIZADO
    assert comprobante.numero_autorizacion == '123456789'
    assert comprobante.secuencial == '000000001'
    assert comprobante.xml_firmado
    assert comprobante.clave_acceso and len(comprobante.clave_acceso) == 49


def test_procesar_comprobante_es_idempotente_por_referencia_externa(session, payload_dict):
    with patch('services.enviar_recepcion', return_value=('RECIBIDA', [])), \
         patch('services.consultar_autorizacion', return_value=('AUTORIZADO', '1', None, '', [])):
        primero = services.procesar_comprobante(session, payload_dict)
        segundo = services.procesar_comprobante(session, payload_dict)

    assert primero.id == segundo.id
    assert SecuencialSRI.siguiente(session, '001', '001') == 2  # solo se reservó 1 secuencial antes de esta llamada


def test_procesar_comprobante_devuelta_no_consulta_autorizacion(session, payload_dict):
    with patch('services.enviar_recepcion', return_value=('DEVUELTA', ['45: campo obligatorio faltante'])), \
         patch('services.consultar_autorizacion') as mock_consultar:
        comprobante = services.procesar_comprobante(session, payload_dict)

    assert comprobante.estado == ComprobanteElectronico.DEVUELTA
    assert comprobante.mensajes == ['45: campo obligatorio faltante']
    mock_consultar.assert_not_called()


def test_procesar_comprobante_error_de_envio_marca_error(session, payload_dict):
    with patch('services.enviar_recepcion', side_effect=SRIError('no se pudo conectar al SRI')):
        comprobante = services.procesar_comprobante(session, payload_dict)

    assert comprobante.estado == ComprobanteElectronico.ERROR
    assert 'no se pudo conectar al SRI' in comprobante.mensajes[-1]


def test_consultar_estado_sri_actualiza_comprobante_existente(session, payload_dict):
    with patch('services.enviar_recepcion', return_value=('RECIBIDA', [])), \
         patch('services.consultar_autorizacion', return_value=('EN PROCESO', '', None, '', [])):
        comprobante = services.procesar_comprobante(session, payload_dict)

    assert comprobante.estado == ComprobanteElectronico.EN_PROCESO

    with patch('services.consultar_autorizacion', return_value=(
        'AUTORIZADO', '999', datetime.datetime(2026, 7, 15, 12, 0, 0), '<xml/>', [],
    )):
        data = services.consultar_estado_sri(session, comprobante.clave_acceso)

    assert data['estado_sri'] == 'AUTORIZADO'
    assert data['numero_autorizacion'] == '999'
    session.refresh(comprobante)
    assert comprobante.estado == ComprobanteElectronico.AUTORIZADO


def test_consultar_estado_sri_sin_comprobante_local_no_falla(session):
    with patch('services.consultar_autorizacion', return_value=('NO_ENCONTRADO', '', None, '', [])):
        data = services.consultar_estado_sri(session, 'clave-que-no-existe-localmente')

    assert data['estado_sri'] == 'NO_ENCONTRADO'


def test_consultar_estado_sri_propaga_sri_error(session):
    with patch('services.consultar_autorizacion', side_effect=SRIError('sin conexión')):
        try:
            services.consultar_estado_sri(session, 'cualquier-clave')
            assert False, 'debía lanzar SRIError'
        except SRIError:
            pass
