from lxml import etree

from models import ComprobanteElectronico
from xml_builder import construir_xml_factura


def _comprobante(**overrides):
    defaults = dict(
        referencia_externa='billing.invoice:1', payload={}, tipo_comprobante='01',
        ambiente=ComprobanteElectronico.AMBIENTE_PRUEBAS, establecimiento='001', punto_emision='001',
        secuencial='000000001', clave_acceso='1' * 49,
    )
    defaults.update(overrides)
    return ComprobanteElectronico(**defaults)


def test_construir_xml_factura_consumidor_final(payload_dict):
    comprobante = _comprobante()
    xml_bytes = construir_xml_factura(payload_dict, comprobante)

    root = etree.fromstring(xml_bytes)
    assert root.tag == 'factura'
    assert root.findtext('.//claveAcceso') == comprobante.clave_acceso
    assert root.findtext('.//tipoIdentificacionComprador') == '07'
    assert root.findtext('.//razonSocialComprador') == 'CONSUMIDOR FINAL'
    assert root.findtext('.//importeTotal') == '23.00'


def test_construir_xml_factura_comprador_con_ruc(payload_dict):
    payload_dict['comprador'] = {
        'es_consumidor_final': False, 'tipo_identificacion': 'ruc', 'identificacion': '0987654321001',
        'razon_social': 'Cliente Empresa S.A.', 'direccion': '', 'email': 'cliente@correo.com', 'telefono': '',
    }
    comprobante = _comprobante()
    xml_bytes = construir_xml_factura(payload_dict, comprobante)

    root = etree.fromstring(xml_bytes)
    assert root.findtext('.//tipoIdentificacionComprador') == '04'
    assert root.findtext('.//identificacionComprador') == '0987654321001'
    campo_email = root.find('.//infoAdicional/campoAdicional[@nombre="email"]')
    assert campo_email.text == 'cliente@correo.com'


def test_construir_xml_factura_credito_incluye_plazo(payload_dict):
    payload_dict['forma_pago'] = {'codigo_sri': '20', 'es_credito': True, 'monto_a_pagar': '23.00', 'plazo_dias': 30}
    comprobante = _comprobante()
    xml_bytes = construir_xml_factura(payload_dict, comprobante)

    root = etree.fromstring(xml_bytes)
    assert root.findtext('.//pagos/pago/formaPago') == '20'
    assert root.findtext('.//pagos/pago/plazo') == '30'
