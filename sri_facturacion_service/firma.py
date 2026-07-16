"""
Firma electrónica del XML del comprobante, perfil XAdES-BES enveloped, que
es lo que exige el SRI para aceptar un comprobante en el web service de
recepción.

IMPORTANTE — límite de esto: implementa la estructura de firma documentada
públicamente por el SRI, pero solo se pudo verificar en este entorno que:
(a) el .p12 se carga y la clave/certificado quedan disponibles, y (b) la
firma resultante es criptográficamente válida (se puede volver a verificar
con las mismas claves públicas). NO se pudo probar la aceptación real
contra el web service del SRI (eso requiere el certificado real del usuario
y red hacia sri.gob.ec, ninguno de los dos disponibles acá) — esa prueba la
tiene que hacer el usuario.

Nunca se le pide al usuario pegar el .p12 ni su contraseña en el chat: se
leen de disco (SRI_CERTIFICADO_PATH) y de una variable de entorno
(SRI_CERTIFICADO_PASSWORD), ambas configuradas en su `.env` local.
"""
import base64
import datetime
import hashlib
import uuid

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.serialization import Encoding, pkcs12
from lxml import etree

DS_NS = 'http://www.w3.org/2000/09/xmldsig#'
ETSI_NS = 'http://uri.etsi.org/01903/v1.3.2#'
C14N_ALGO = 'http://www.w3.org/2001/10/xml-exc-c14n#'
ENVELOPED_SIGNATURE_ALGO = 'http://www.w3.org/2000/09/xmldsig#enveloped-signature'
SHA256_DIGEST_ALGO = 'http://www.w3.org/2001/04/xmlenc#sha256'
RSA_SHA256_SIGNATURE_ALGO = 'http://www.w3.org/2001/04/xmldsig-more#rsa-sha256'

NSMAP_DS = {'ds': DS_NS}
NSMAP_ETSI = {'etsi': ETSI_NS}


class FirmaError(Exception):
    """Algo falló al cargar el certificado o al firmar el XML."""


def cargar_certificado(path, password):
    """Lee un .p12/.pfx de disco y devuelve (private_key, certificate).
    NUNCA registra ni expone la contraseña ni la clave privada en logs."""
    if not path:
        raise FirmaError(
            'No hay certificado configurado (SRI_CERTIFICADO_PATH vacío en el .env). '
            'Configura la ruta a tu archivo .p12 real para poder firmar comprobantes.'
        )
    try:
        with open(path, 'rb') as f:
            datos_p12 = f.read()
    except OSError as e:
        raise FirmaError(f'No se pudo leer el certificado en {path!r}: {e}') from e

    try:
        private_key, certificate, _ = pkcs12.load_key_and_certificates(
            datos_p12, (password or '').encode('utf-8'),
        )
    except Exception as e:
        raise FirmaError(f'No se pudo abrir el certificado (contraseña incorrecta o archivo inválido): {e}') from e

    if private_key is None or certificate is None:
        raise FirmaError('El certificado no contiene una clave privada o un certificado X.509 válidos.')
    return private_key, certificate


def _digest_b64(data):
    return base64.b64encode(hashlib.sha256(data).digest()).decode('ascii')


def _c14n(element):
    return etree.tostring(element, method='c14n', exclusive=True)


def firmar_xml(xml_bytes, private_key, certificate):
    """
    Firma `xml_bytes` (el XML de la factura sin firmar) insertando un
    <ds:Signature> XAdES-BES enveloped al final del elemento raíz. Devuelve
    el XML firmado como bytes.
    """
    root = etree.fromstring(xml_bytes)
    if root.get('id') != 'comprobante':
        raise FirmaError('El XML a firmar debe tener id="comprobante" en su elemento raíz.')

    signature_id = f'Signature{uuid.uuid4().hex[:8]}'
    cert_id = f'Certificate{uuid.uuid4().hex[:8]}'
    signed_properties_id = f'SignedProperties{uuid.uuid4().hex[:8]}'
    signature_value_id = f'SignatureValue{uuid.uuid4().hex[:8]}'
    qualifying_properties_id = f'QualifyingProperties{uuid.uuid4().hex[:8]}'

    cert_der = certificate.public_bytes(encoding=Encoding.DER)
    cert_b64 = base64.b64encode(cert_der).decode('ascii')
    cert_digest = _digest_b64(cert_der)

    issuer_name = certificate.issuer.rfc4514_string()
    serial_number = str(certificate.serial_number)

    # --- digest del comprobante completo (referencia principal) ---
    comprobante_digest = _digest_b64(_c14n(root))

    # --- SignedProperties (XAdES) ---
    # OJO: nsmap incluye 'ds' desde el arranque (no solo 'etsi'), aunque acá
    # todavía no haya ningún elemento ds: directo — SignedProperties SÍ usa
    # ds:DigestMethod/ds:DigestValue más abajo (CertDigest, IssuerSerial), y
    # su digest se calcula MIENTRAS este árbol sigue separado del resto de
    # la firma (recién se une con obj.append(qualifying_properties) más
    # abajo). Si no se declara 'ds' acá desde ya, lxml le inventa un prefijo
    # cualquiera en este punto (ns0, ns1...) para esos elementos ds: sueltos,
    # DISTINTO del prefijo "ds" que sí van a tener una vez insertados dentro
    # de <ds:Signature> — la canonicalización exclusiva (C14N) depende del
    # prefijo real usado, así que ese desacople por sí solo ya rompe el
    # digest (confirmado con signxml: "Digest mismatch for reference 1
    # (#SignedProperties...)"). Fijar el mismo prefijo acá evita el problema
    # sin tener que reordenar cuándo se arma cada pieza del árbol.
    qualifying_properties = etree.Element(f'{{{ETSI_NS}}}QualifyingProperties', nsmap={**NSMAP_ETSI, **NSMAP_DS})
    qualifying_properties.set('Target', '#comprobante')
    qualifying_properties.set('Id', qualifying_properties_id)
    signed_properties = etree.SubElement(qualifying_properties, f'{{{ETSI_NS}}}SignedProperties')
    signed_properties.set('Id', signed_properties_id)
    signed_sig_props = etree.SubElement(signed_properties, f'{{{ETSI_NS}}}SignedSignatureProperties')
    signing_time = etree.SubElement(signed_sig_props, f'{{{ETSI_NS}}}SigningTime')
    signing_time.text = datetime.datetime.now().isoformat(timespec='seconds')
    signing_cert = etree.SubElement(signed_sig_props, f'{{{ETSI_NS}}}SigningCertificate')
    cert_el = etree.SubElement(signing_cert, f'{{{ETSI_NS}}}Cert')
    cert_digest_el = etree.SubElement(cert_el, f'{{{ETSI_NS}}}CertDigest')
    etree.SubElement(cert_digest_el, f'{{{DS_NS}}}DigestMethod', Algorithm=SHA256_DIGEST_ALGO)
    etree.SubElement(cert_digest_el, f'{{{DS_NS}}}DigestValue').text = cert_digest
    issuer_serial = etree.SubElement(cert_el, f'{{{ETSI_NS}}}IssuerSerial')
    etree.SubElement(issuer_serial, f'{{{DS_NS}}}X509IssuerName').text = issuer_name
    etree.SubElement(issuer_serial, f'{{{DS_NS}}}X509SerialNumber').text = serial_number
    signed_data_obj_props = etree.SubElement(signed_properties, f'{{{ETSI_NS}}}SignedDataObjectProperties')
    data_object_format = etree.SubElement(signed_data_obj_props, f'{{{ETSI_NS}}}DataObjectFormat')
    data_object_format.set('ObjectReference', '#comprobante')
    etree.SubElement(data_object_format, f'{{{ETSI_NS}}}MimeType').text = 'text/xml'

    signed_properties_digest = _digest_b64(_c14n(signed_properties))

    # --- SignedInfo ---
    signature = etree.Element(f'{{{DS_NS}}}Signature', nsmap=NSMAP_DS)
    signature.set('Id', signature_id)
    signed_info = etree.SubElement(signature, f'{{{DS_NS}}}SignedInfo')
    etree.SubElement(signed_info, f'{{{DS_NS}}}CanonicalizationMethod', Algorithm=C14N_ALGO)
    etree.SubElement(signed_info, f'{{{DS_NS}}}SignatureMethod', Algorithm=RSA_SHA256_SIGNATURE_ALGO)

    ref_comprobante = etree.SubElement(signed_info, f'{{{DS_NS}}}Reference', URI='#comprobante')
    transforms = etree.SubElement(ref_comprobante, f'{{{DS_NS}}}Transforms')
    # enveloped-signature PRIMERO: le dice al verificador que quite el propio
    # <ds:Signature> del documento antes de canonicalizar — sin esto, el
    # verificador recalcula el digest sobre el documento CON la firma ya
    # puesta (nunca coincide con lo que nosotros calculamos ANTES de
    # insertarla) y rechaza con "firma inválida". Confirmado con signxml
    # (InvalidDigest) antes de este fix.
    etree.SubElement(transforms, f'{{{DS_NS}}}Transform', Algorithm=ENVELOPED_SIGNATURE_ALGO)
    etree.SubElement(transforms, f'{{{DS_NS}}}Transform', Algorithm=C14N_ALGO)
    etree.SubElement(ref_comprobante, f'{{{DS_NS}}}DigestMethod', Algorithm=SHA256_DIGEST_ALGO)
    etree.SubElement(ref_comprobante, f'{{{DS_NS}}}DigestValue').text = comprobante_digest

    ref_signed_props = etree.SubElement(
        signed_info, f'{{{DS_NS}}}Reference', URI=f'#{signed_properties_id}', Type='http://uri.etsi.org/01903#SignedProperties',
    )
    # Sin <ds:Transforms> declarado acá, un verificador espec-compliant no
    # tiene por qué asumir que se usó C14N exclusivo para este digest (que
    # es justo lo que hace _c14n() del lado de la firma) — sin la
    # declaración, recalcula con otro método por defecto y el digest nunca
    # coincide. Confirmado con signxml (mismatch en esta referencia
    # específicamente, ya con la de #comprobante corregida y pasando).
    signed_props_transforms = etree.SubElement(ref_signed_props, f'{{{DS_NS}}}Transforms')
    etree.SubElement(signed_props_transforms, f'{{{DS_NS}}}Transform', Algorithm=C14N_ALGO)
    etree.SubElement(ref_signed_props, f'{{{DS_NS}}}DigestMethod', Algorithm=SHA256_DIGEST_ALGO)
    etree.SubElement(ref_signed_props, f'{{{DS_NS}}}DigestValue').text = signed_properties_digest

    # NO se agrega una <ds:Reference URI="#cert_id"> apuntando al KeyInfo:
    # XAdES-BES no la exige (el certificado ya queda ligado a la firma vía
    # SignedProperties/CertDigest más arriba), y la versión anterior de este
    # código la declaraba mal — el DigestValue se calculaba sobre los bytes
    # crudos del certificado (DER), pero la referencia apuntaba al elemento
    # XML <ds:KeyInfo> — dos cosas distintas que nunca iban a coincidir para
    # ningún verificador. Confirmado con signxml (mismatch en esta
    # referencia, ya con las dos anteriores corregidas y pasando).

    # --- Firmar el SignedInfo canonicalizado con la clave privada ---
    signed_info_c14n = _c14n(signed_info)
    firma_bytes = private_key.sign(signed_info_c14n, padding.PKCS1v15(), hashes.SHA256())
    signature_value_b64 = base64.b64encode(firma_bytes).decode('ascii')

    signature_value = etree.SubElement(signature, f'{{{DS_NS}}}SignatureValue', Id=signature_value_id)
    signature_value.text = signature_value_b64

    # --- KeyInfo (certificado + clave pública) ---
    key_info = etree.SubElement(signature, f'{{{DS_NS}}}KeyInfo', Id=cert_id)
    x509_data = etree.SubElement(key_info, f'{{{DS_NS}}}X509Data')
    etree.SubElement(x509_data, f'{{{DS_NS}}}X509Certificate').text = cert_b64

    # --- ds:Object con las propiedades XAdES ---
    obj = etree.SubElement(signature, f'{{{DS_NS}}}Object')
    obj.append(qualifying_properties)

    root.append(signature)
    # Mismo motivo que en xml_builder.py: sin standalone= (ver ese archivo) —
    # de lo contrario el SRI rechaza el envío con "35: ARCHIVO NO CUMPLE
    # ESTRUCTURA XML" aunque el resto del XML/firma sea correcto.
    return etree.tostring(root, xml_declaration=True, encoding='UTF-8')
