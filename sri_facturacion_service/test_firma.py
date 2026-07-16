import pytest
from lxml import etree

import config
from firma import FirmaError, cargar_certificado, firmar_xml

XML_SIN_FIRMAR = b'<?xml version="1.0" encoding="UTF-8"?><factura id="comprobante" version="2.1.0"><infoTributaria><ruc>1234567890001</ruc></infoTributaria></factura>'


def test_cargar_certificado_real():
    private_key, certificate = cargar_certificado(config.SRI_CERTIFICADO_PATH, config.SRI_CERTIFICADO_PASSWORD)
    assert private_key is not None
    assert certificate is not None


def test_cargar_certificado_password_incorrecta():
    with pytest.raises(FirmaError):
        cargar_certificado(config.SRI_CERTIFICADO_PATH, 'contraseña-incorrecta')


def test_cargar_certificado_ruta_vacia():
    with pytest.raises(FirmaError):
        cargar_certificado('', config.SRI_CERTIFICADO_PASSWORD)


def test_firmar_xml_produce_un_elemento_de_firma_xades():
    private_key, certificate = cargar_certificado(config.SRI_CERTIFICADO_PATH, config.SRI_CERTIFICADO_PASSWORD)
    xml_firmado = firmar_xml(XML_SIN_FIRMAR, private_key, certificate)

    root = etree.fromstring(xml_firmado)
    firma = root.find('.//{http://www.w3.org/2000/09/xmldsig#}Signature')
    assert firma is not None
