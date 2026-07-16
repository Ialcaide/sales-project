from models import ComprobanteElectronico, SecuencialSRI


def test_siguiente_empieza_en_1(session):
    assert SecuencialSRI.siguiente(session, '001', '001') == 1


def test_siguiente_incrementa(session):
    SecuencialSRI.siguiente(session, '001', '001')
    SecuencialSRI.siguiente(session, '001', '001')
    assert SecuencialSRI.siguiente(session, '001', '001') == 3


def test_siguiente_es_independiente_por_serie(session):
    assert SecuencialSRI.siguiente(session, '001', '001') == 1
    assert SecuencialSRI.siguiente(session, '002', '001') == 1
    assert SecuencialSRI.siguiente(session, '001', '002') == 1
    assert SecuencialSRI.siguiente(session, '001', '001') == 2


def test_ambiente_display():
    comprobante = ComprobanteElectronico(
        referencia_externa='x', payload={}, establecimiento='001', punto_emision='001',
        secuencial='000000001', clave_acceso='1' * 49, ambiente=ComprobanteElectronico.AMBIENTE_PRUEBAS,
    )
    assert comprobante.ambiente_display() == 'Pruebas'
    comprobante.ambiente = ComprobanteElectronico.AMBIENTE_PRODUCCION
    assert comprobante.ambiente_display() == 'Producción'


def test_to_dict_incluye_los_campos_esperados():
    comprobante = ComprobanteElectronico(
        referencia_externa='billing.invoice:1', payload={}, establecimiento='001', punto_emision='001',
        secuencial='000000001', clave_acceso='1' * 49,
    )
    data = comprobante.to_dict()
    assert data['referencia_externa'] == 'billing.invoice:1'
    assert data['clave_acceso'] == '1' * 49
    assert data['estado'] == ComprobanteElectronico.GENERADO
    assert data['fecha_autorizacion'] is None
