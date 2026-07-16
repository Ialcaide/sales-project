import datetime
from unittest.mock import patch

from client import SRIError


def test_index_no_requiere_api_key(client):
    response = client.get('/')
    assert response.status_code == 200
    data = response.json()
    assert data['servicio'] == 'sri_facturacion_service'
    assert data['estado'] == 'ok'
    assert data['ambiente_sri'] in ('pruebas', 'produccion')
    assert data['recepcion_wsdl'].startswith('https://')
    assert data['autorizacion_wsdl'].startswith('https://')


def test_crear_comprobante_sin_api_key_es_401(client, payload_dict):
    response = client.post('/api/comprobantes/', json=payload_dict)
    assert response.status_code == 401


def test_crear_comprobante_con_api_key_incorrecta_es_401(client, payload_dict):
    response = client.post('/api/comprobantes/', json=payload_dict, headers={'X-API-Key': 'incorrecta'})
    assert response.status_code == 401


def test_crear_comprobante_ok(client, payload_dict, api_key_headers):
    with patch('services.enviar_recepcion', return_value=('RECIBIDA', [])), \
         patch('services.consultar_autorizacion', return_value=(
             'AUTORIZADO', '123456789', datetime.datetime(2026, 7, 15, 10, 0, 0), '<xml/>', [],
         )):
        response = client.post('/api/comprobantes/', json=payload_dict, headers=api_key_headers)

    assert response.status_code == 201
    data = response.json()['comprobante']
    assert data['estado'] == 'autorizado'
    assert data['numero_autorizacion'] == '123456789'
    assert len(data['clave_acceso']) == 49


def test_crear_comprobante_payload_invalido_es_422(client, payload_dict, api_key_headers):
    payload_dict['comprador'] = {'es_consumidor_final': False}  # faltan tipo_identificacion/identificacion/razon_social
    response = client.post('/api/comprobantes/', json=payload_dict, headers=api_key_headers)
    assert response.status_code == 422


def test_detalle_comprobante_no_encontrado_es_404(client, api_key_headers):
    response = client.get('/api/comprobantes/clave-inexistente/', headers=api_key_headers)
    assert response.status_code == 404


def test_detalle_comprobante_encontrado(client, payload_dict, api_key_headers):
    with patch('services.enviar_recepcion', return_value=('RECIBIDA', [])), \
         patch('services.consultar_autorizacion', return_value=('EN PROCESO', '', None, '', [])):
        creado = client.post('/api/comprobantes/', json=payload_dict, headers=api_key_headers).json()['comprobante']

    response = client.get(f'/api/comprobantes/{creado["clave_acceso"]}/', headers=api_key_headers)
    assert response.status_code == 200
    assert response.json()['comprobante']['clave_acceso'] == creado['clave_acceso']


def test_estado_sri_ok(client, api_key_headers):
    with patch('services.consultar_autorizacion', return_value=('EN PROCESO', '', None, '', [])):
        response = client.get('/api/comprobantes/una-clave-cualquiera/estado-sri/', headers=api_key_headers)

    assert response.status_code == 200
    assert response.json()['estado_sri'] == 'EN PROCESO'


def test_estado_sri_error_del_sri_es_502(client, api_key_headers):
    with patch('services.consultar_autorizacion', side_effect=SRIError('sin conexión al SRI')):
        response = client.get('/api/comprobantes/una-clave-cualquiera/estado-sri/', headers=api_key_headers)

    assert response.status_code == 502


def test_ride_no_encontrado_es_404(client, api_key_headers):
    response = client.get('/api/comprobantes/clave-inexistente/ride/', headers=api_key_headers)
    assert response.status_code == 404


def test_ride_devuelve_pdf(client, payload_dict, api_key_headers):
    with patch('services.enviar_recepcion', return_value=('RECIBIDA', [])), \
         patch('services.consultar_autorizacion', return_value=(
             'AUTORIZADO', '123456789', datetime.datetime(2026, 7, 15, 10, 0, 0), '<xml/>', [],
         )):
        creado = client.post('/api/comprobantes/', json=payload_dict, headers=api_key_headers).json()['comprobante']

    response = client.get(f'/api/comprobantes/{creado["clave_acceso"]}/ride/', headers=api_key_headers)
    assert response.status_code == 200
    assert response.headers['content-type'] == 'application/pdf'
    assert response.content.startswith(b'%PDF')
