"""
Arma el XML de una factura electrónica según el esquema público del SRI
(`factura`, versión 2.1.0). No depende de red ni de certificado.

A diferencia del original (sales_project/facturacion_electronica/xml_builder.py,
que tomaba un `billing.Invoice` de Django directo), acá se recibe un `payload`
genérico (dict ya validado por comprobantes/serializers.py) — así este
servicio no necesita saber nada de cómo está armado el modelo de factura de
NINGÚN proyecto cliente, solo qué campos vienen en el payload (ver
comprobantes/serializers.py -> PAYLOAD_SCHEMA para la forma exacta).

OJO: el SRI actualiza de tanto en tanto la versión del esquema y los
catálogos (ej. los códigos de porcentaje de IVA). Esto apunta a la versión
2.1.0 y a los códigos de IVA vigentes al momento de escribir esto — antes de
usar en serio, comparar contra la ficha técnica publicada actualmente en
sri.gob.ec.
"""
from decimal import Decimal

from lxml import etree

VERSION_ESQUEMA = '2.1.0'

# Códigos de porcentaje de IVA del catálogo del SRI (tabla 17 de la ficha
# técnica). Se resuelve por el % que manda el cliente en el payload en vez
# de asumir un único valor fijo.
CODIGOS_PORCENTAJE_IVA = {
    Decimal('0'): '0',
    Decimal('12.00'): '2',
    Decimal('14.00'): '3',
    Decimal('15.00'): '4',
}


def _codigo_porcentaje_iva(porcentaje):
    return CODIGOS_PORCENTAJE_IVA.get(Decimal(str(porcentaje)), '4')


# Catálogo del SRI (tabla 8, formas de pago) — el cliente manda directamente
# el código SRI que corresponde (ver comprobantes/serializers.py), este
# servicio no adivina a partir de un forma_pago propio de ningún proyecto.
CODIGO_FORMA_PAGO_DEFAULT = '01'

DESCRIPCION_FORMA_PAGO_SRI = {
    '01': 'SIN UTILIZACIÓN DEL SISTEMA FINANCIERO',
    '16': 'TARJETA DE DÉBITO',
    '17': 'DINERO ELECTRÓNICO',
    '18': 'TARJETA PREPAGO',
    '19': 'TARJETA DE CRÉDITO',
    '20': 'OTROS CON UTILIZACIÓN DEL SISTEMA FINANCIERO',
}


def _sub(parent, tag, text=None):
    el = etree.SubElement(parent, tag)
    if text is not None:
        el.text = str(text)
    return el


def construir_xml_factura(payload, comprobante):
    """
    payload: dict genérico ya validado (ver serializers.py) con las claves
    emisor/comprador/lineas/iva_porcentaje/subtotal/iva_valor/total/forma_pago.
    comprobante: ComprobanteElectronico ya con clave_acceso/secuencial/
    establecimiento/punto_emision/ambiente asignados (ver services.py).
    Devuelve el XML como bytes (UTF-8, sin firmar todavía).
    """
    emisor = payload['emisor']
    comprador = payload['comprador']
    forma_pago = payload['forma_pago']

    factura = etree.Element('factura', id='comprobante', version=VERSION_ESQUEMA)

    info_tributaria = etree.SubElement(factura, 'infoTributaria')
    _sub(info_tributaria, 'ambiente', comprobante.ambiente)
    _sub(info_tributaria, 'tipoEmision', '1')
    _sub(info_tributaria, 'razonSocial', emisor['razon_social'])
    if emisor.get('nombre_comercial'):
        _sub(info_tributaria, 'nombreComercial', emisor['nombre_comercial'])
    _sub(info_tributaria, 'ruc', emisor['ruc'])
    _sub(info_tributaria, 'claveAcceso', comprobante.clave_acceso)
    _sub(info_tributaria, 'codDoc', comprobante.tipo_comprobante)
    _sub(info_tributaria, 'estab', comprobante.establecimiento)
    _sub(info_tributaria, 'ptoEmi', comprobante.punto_emision)
    _sub(info_tributaria, 'secuencial', f'{int(comprobante.secuencial):09d}')
    _sub(info_tributaria, 'dirMatriz', emisor.get('direccion_matriz') or 'S/N')

    info_factura = etree.SubElement(factura, 'infoFactura')
    _sub(info_factura, 'fechaEmision', payload['fecha_emision_ddmmyyyy'])
    _sub(info_factura, 'dirEstablecimiento', emisor.get('direccion_matriz') or 'S/N')
    _sub(info_factura, 'obligadoContabilidad', 'SI' if emisor.get('obligado_contabilidad') else 'NO')

    # Ficha técnica del SRI (ANEXO 9, FACTURA VERSIÓN 2.1.0): para
    # tipoIdentificacionComprador='07' (venta a consumidor final),
    # razonSocialComprador e identificacionComprador van con estos valores
    # FIJOS — nunca los datos reales del comprador. El cliente ya nos avisa
    # con es_consumidor_final=True (ver serializers.py), no lo inferimos acá.
    if comprador.get('es_consumidor_final'):
        tipo_id = '07'
        razon_social_comprador = 'CONSUMIDOR FINAL'
        identificacion_comprador = '9999999999999'
    else:
        # Catálogo del SRI (tabla 6, tipos de identificación): 04=RUC, 05=cédula, 06=pasaporte.
        tipo_id = {'ruc': '04', 'cedula': '05', 'pasaporte': '06'}.get(comprador['tipo_identificacion'], '05')
        razon_social_comprador = comprador['razon_social']
        identificacion_comprador = comprador['identificacion']
    _sub(info_factura, 'tipoIdentificacionComprador', tipo_id)
    _sub(info_factura, 'razonSocialComprador', razon_social_comprador)
    _sub(info_factura, 'identificacionComprador', identificacion_comprador)
    _sub(info_factura, 'totalSinImpuestos', f'{Decimal(str(payload["subtotal"])):.2f}')
    _sub(info_factura, 'totalDescuento', '0.00')

    total_con_impuestos = etree.SubElement(info_factura, 'totalConImpuestos')
    total_impuesto = etree.SubElement(total_con_impuestos, 'totalImpuesto')
    _sub(total_impuesto, 'codigo', '2')  # 2 = IVA
    _sub(total_impuesto, 'codigoPorcentaje', _codigo_porcentaje_iva(payload['iva_porcentaje']))
    _sub(total_impuesto, 'baseImponible', f'{Decimal(str(payload["subtotal"])):.2f}')
    _sub(total_impuesto, 'valor', f'{Decimal(str(payload["iva_valor"])):.2f}')

    _sub(info_factura, 'propina', '0.00')
    _sub(info_factura, 'importeTotal', f'{Decimal(str(payload["total"])):.2f}')
    _sub(info_factura, 'moneda', 'DOLAR')

    pagos = etree.SubElement(info_factura, 'pagos')
    pago = etree.SubElement(pagos, 'pago')
    _sub(pago, 'formaPago', forma_pago.get('codigo_sri', CODIGO_FORMA_PAGO_DEFAULT))
    if forma_pago.get('es_credito'):
        _sub(pago, 'total', f'{Decimal(str(forma_pago["monto_a_pagar"])):.2f}')
        if forma_pago.get('plazo_dias'):
            _sub(pago, 'plazo', max(int(forma_pago['plazo_dias']), 1))
            _sub(pago, 'unidadTiempo', 'dias')
    else:
        _sub(pago, 'total', f'{Decimal(str(payload["total"])):.2f}')

    detalles = etree.SubElement(factura, 'detalles')
    for linea in payload['lineas']:
        cantidad = Decimal(str(linea['cantidad']))
        precio_unitario = Decimal(str(linea['precio_unitario']))
        subtotal_linea = (cantidad * precio_unitario).quantize(Decimal('0.01'))
        detalle = etree.SubElement(detalles, 'detalle')
        _sub(detalle, 'codigoPrincipal', str(linea['codigo']))
        _sub(detalle, 'descripcion', linea['descripcion'])
        _sub(detalle, 'cantidad', f'{cantidad:.2f}')
        _sub(detalle, 'precioUnitario', f'{precio_unitario:.2f}')
        _sub(detalle, 'descuento', '0.00')
        _sub(detalle, 'precioTotalSinImpuesto', f'{subtotal_linea:.2f}')
        impuestos = etree.SubElement(detalle, 'impuestos')
        impuesto = etree.SubElement(impuestos, 'impuesto')
        _sub(impuesto, 'codigo', '2')
        _sub(impuesto, 'codigoPorcentaje', _codigo_porcentaje_iva(payload['iva_porcentaje']))
        _sub(impuesto, 'tarifa', f'{Decimal(str(payload["iva_porcentaje"])):.2f}')
        _sub(impuesto, 'baseImponible', f'{subtotal_linea:.2f}')
        iva_fraccion = Decimal(str(payload['iva_porcentaje'])) / Decimal('100')
        valor_iva = (subtotal_linea * iva_fraccion).quantize(Decimal('0.01'))
        _sub(impuesto, 'valor', f'{valor_iva:.2f}')

    # <infoAdicional> es opcional a nivel de <factura>, PERO si aparece el
    # XSD exige que tenga al menos un <campoAdicional> adentro — un
    # <infoAdicional></infoAdicional> vacío rompe la validación con "35:
    # ARCHIVO NO CUMPLE ESTRUCTURA XML". Confirmado validando contra el XSD
    # oficial del SRI (factura_V2.1.0.xsd).
    if comprador.get('email') or comprador.get('telefono'):
        info_adicional = etree.SubElement(factura, 'infoAdicional')
        if comprador.get('email'):
            _sub(info_adicional, 'campoAdicional', comprador['email']).set('nombre', 'email')
        if comprador.get('telefono'):
            _sub(info_adicional, 'campoAdicional', comprador['telefono']).set('nombre', 'telefono')

    # OJO: sin standalone= — lxml, si se pasa standalone=False, escribe
    # literalmente `standalone="no"` en la declaración XML, y NINGÚN ejemplo
    # oficial del SRI (ficha técnica) trae ese atributo — el SRI lo rechaza
    # con "35: ARCHIVO NO CUMPLE ESTRUCTURA XML". Omitirlo del todo produce
    # la declaración exacta que sí espera: <?xml version="1.0" encoding="UTF-8"?>
    return etree.tostring(factura, xml_declaration=True, encoding='UTF-8')
