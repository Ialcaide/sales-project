"""
Cliente HTTP de sri_facturacion_service — un proyecto Django INDEPENDIENTE
(ver sri_facturacion_service/ en la raíz de este repo) que ahora concentra
toda la firma electrónica y el envío al SRI, para poder reutilizarse desde
cualquier otro proyecto, no solo este. Este módulo mantiene EXACTAMENTE el
mismo contrato público que tenía antes (mismas 4 funciones, misma firma) —
billing/views.py y facturacion_electronica/views.py siguen llamándolas
igual, sin ningún cambio de su lado.

`generar_y_enviar_comprobante()` sigue sin dejar escapar una excepción NUNCA
(mismo criterio "best effort" de siempre): un problema acá (el microservicio
caído, mal configurado, tarda demasiado) no debe revertir ni bloquear la
venta ya completada.
"""
import logging

import requests
from django.conf import settings

from .models import ComprobanteElectronico

logger = logging.getLogger(__name__)


class SRIError(Exception):
    """Algo falló al hablar con sri_facturacion_service (red, timeout,
    respuesta con error) — mismo nombre que la excepción que antes vivía en
    client.py (esa lógica se movió al microservicio); se deja el mismo
    nombre acá para que facturacion_electronica/views.py no tenga que
    cambiar su `from . import client` / `client.SRIError`."""


# Catálogo del SRI (tabla 8, formas de pago) — traduce forma_pago/tipo_pago
# de billing.Invoice (un dato de ESTE proyecto) al código que espera el
# microservicio. Esta traducción se queda acá a propósito: el microservicio
# no tiene por qué saber qué es un billing.Invoice ni cómo guarda su forma
# de pago.
CODIGOS_FORMA_PAGO_SRI = {
    'efectivo': '01',
    'tarjeta': '19',
    'paypal': '19',
}
CODIGO_FORMA_PAGO_CREDITO = '20'


def codigo_forma_pago(invoice):
    if invoice.tipo_pago == invoice.CREDITO:
        return CODIGO_FORMA_PAGO_CREDITO
    return CODIGOS_FORMA_PAGO_SRI.get(invoice.forma_pago, '01')


def _headers():
    return {'Content-Type': 'application/json', 'X-API-Key': settings.FACTURACION_ELECTRONICA_SERVICE_API_KEY}


def _url(path):
    return f'{settings.FACTURACION_ELECTRONICA_SERVICE_URL.rstrip("/")}{path}'


def _payload_desde_invoice(invoice, config):
    """Arma el payload genérico que espera sri_facturacion_service a partir
    de ESTE invoice/config — es la pieza que "adapta" el modelo propio de
    este proyecto al contrato del microservicio (ver
    sri_facturacion_service/comprobantes/serializers.py para la forma exacta
    que exige del otro lado)."""
    customer = invoice.customer
    if customer.es_consumidor_final:
        comprador = {'es_consumidor_final': True}
    else:
        comprador = {
            'es_consumidor_final': False,
            'tipo_identificacion': customer.tipo_identificacion,
            'identificacion': customer.dni,
            'razon_social': customer.full_name,
            'direccion': customer.address or '',
            'email': customer.email or '',
            'telefono': customer.phone or '',
        }

    lineas = [
        {
            'codigo': str(detail.product_id),
            'descripcion': detail.product.name,
            'cantidad': str(detail.quantity),
            'precio_unitario': str(detail.unit_price),
            'codigo_barras': detail.product.barcode or '',
        }
        for detail in invoice.details.all()
    ]

    es_credito = invoice.tipo_pago == invoice.CREDITO
    forma_pago = {'codigo_sri': codigo_forma_pago(invoice), 'es_credito': es_credito}
    if es_credito:
        forma_pago['monto_a_pagar'] = str(invoice.total_a_pagar)
        if invoice.fecha_limite_pago:
            dias_plazo = (invoice.fecha_limite_pago - invoice.invoice_date.date()).days
            forma_pago['plazo_dias'] = max(dias_plazo, 1)

    return {
        'referencia_externa': f'billing.invoice:{invoice.id}',
        'fecha_emision': invoice.invoice_date.date().isoformat(),
        'emisor': {
            'ruc': config.empresa_ruc,
            'razon_social': config.empresa_nombre,
            'nombre_comercial': config.sri_nombre_comercial,
            'direccion_matriz': config.empresa_direccion,
            'obligado_contabilidad': config.sri_obligado_contabilidad,
            'establecimiento': config.sri_establecimiento,
            'punto_emision': config.sri_punto_emision,
        },
        'comprador': comprador,
        'lineas': lineas,
        'iva_porcentaje': str(config.iva_porcentaje),
        'subtotal': str(invoice.subtotal),
        'iva_valor': str(invoice.tax),
        'total': str(invoice.total),
        'forma_pago': forma_pago,
    }


def _guardar_local(invoice, data):
    """Crea/actualiza el ComprobanteElectronico LOCAL de este proyecto con
    lo que devolvió el microservicio — sigue existiendo acá porque
    invoice_detail.html, los botones de reintentar/consultar, y los tests de
    este proyecto leen este modelo directo (con su OneToOneField a
    billing.Invoice), nunca le preguntan al microservicio en cada render."""
    from django.utils.dateparse import parse_datetime

    fecha_autorizacion = parse_datetime(data['fecha_autorizacion']) if data.get('fecha_autorizacion') else None
    defaults = {
        'tipo_comprobante': data['tipo_comprobante'],
        'ambiente': data['ambiente'],
        'establecimiento': data['establecimiento'],
        'punto_emision': data['punto_emision'],
        'secuencial': data['secuencial'],
        'clave_acceso': data['clave_acceso'],
        'estado': data['estado'],
        'xml_generado': data.get('xml_generado', ''),
        'xml_firmado': data.get('xml_firmado', ''),
        'xml_autorizado': data.get('xml_autorizado', ''),
        'numero_autorizacion': data.get('numero_autorizacion', ''),
        'fecha_autorizacion': fecha_autorizacion,
        'mensajes': data.get('mensajes', []),
    }
    comprobante, _creado = ComprobanteElectronico.objects.update_or_create(
        invoice=invoice, defaults=defaults,
    )
    return comprobante


def generar_y_enviar_comprobante(invoice):
    """Punto de entrada principal. Devuelve el ComprobanteElectronico en el
    estado al que se logró llegar, o None si ni siquiera se pudo reservar
    un secuencial/clave de acceso (config de SRI incompleta/inválida, o el
    microservicio no respondió)."""
    comprobante = getattr(invoice, 'comprobante_electronico', None)
    if comprobante is not None:
        return comprobante

    from configuracion.models import ConfiguracionSistema
    config = ConfiguracionSistema.get_solo()

    try:
        payload = _payload_desde_invoice(invoice, config)
        response = requests.post(
            _url('/api/comprobantes/'), json=payload, headers=_headers(),
            timeout=settings.FACTURACION_ELECTRONICA_SERVICE_TIMEOUT,
        )
    except requests.RequestException:
        logger.exception('No se pudo contactar a sri_facturacion_service para la factura #%s', invoice.id)
        return None

    if response.status_code not in (200, 201):
        logger.error(
            'sri_facturacion_service respondió %s al generar el comprobante de la factura #%s: %s',
            response.status_code, invoice.id, response.text,
        )
        return None

    data = response.json().get('comprobante')
    if not data:
        return None
    return _guardar_local(invoice, data)


def reintentar(invoice):
    """Vuelve a intentar el flujo para una factura sin comprobante, o cuyo
    comprobante quedó en un estado no definitivo (ERROR/DEVUELTA/
    NO_AUTORIZADO) — usado por el botón manual 'Reintentar generación'.
    Como sri_facturacion_service identifica cada comprobante por
    referencia_externa, alcanza con volver a pedir lo mismo: el servicio
    decide solo si reutiliza el que ya existía o crea uno nuevo."""
    comprobante = getattr(invoice, 'comprobante_electronico', None)
    ESTADOS_REINTENTABLES = {
        ComprobanteElectronico.ERROR, ComprobanteElectronico.DEVUELTA, ComprobanteElectronico.NO_AUTORIZADO,
    }
    if comprobante is not None and comprobante.estado not in ESTADOS_REINTENTABLES:
        return comprobante

    from configuracion.models import ConfiguracionSistema
    config = ConfiguracionSistema.get_solo()

    try:
        payload = _payload_desde_invoice(invoice, config)
        response = requests.post(
            _url('/api/comprobantes/'), json=payload, headers=_headers(),
            timeout=settings.FACTURACION_ELECTRONICA_SERVICE_TIMEOUT,
        )
    except requests.RequestException:
        logger.exception('No se pudo contactar a sri_facturacion_service al reintentar la factura #%s', invoice.id)
        return comprobante

    if response.status_code not in (200, 201):
        logger.error(
            'sri_facturacion_service respondió %s al reintentar la factura #%s: %s',
            response.status_code, invoice.id, response.text,
        )
        return comprobante

    data = response.json().get('comprobante')
    if not data:
        return comprobante
    return _guardar_local(invoice, data)


def consultar_autorizacion_manual(comprobante):
    """Botón manual 'Consultar autorización' (para cuando el SRI quedó
    EN_PROCESO en el intento automático) — nunca deja escapar una excepción."""
    try:
        response = requests.get(
            _url(f'/api/comprobantes/{comprobante.clave_acceso}/estado-sri/'), headers=_headers(),
            timeout=settings.FACTURACION_ELECTRONICA_SERVICE_TIMEOUT,
        )
    except requests.RequestException as e:
        _marcar_error_local(comprobante, str(e))
        return comprobante

    if response.status_code != 200:
        _marcar_error_local(comprobante, response.text)
        return comprobante

    data = response.json()
    comprobante.estado = _ESTADOS_SRI.get(data['estado_sri'], ComprobanteElectronico.EN_PROCESO)
    comprobante.numero_autorizacion = data.get('numero_autorizacion', '')
    comprobante.mensajes = data.get('mensajes', [])
    comprobante.save(update_fields=['estado', 'numero_autorizacion', 'mensajes'])
    return comprobante


_ESTADOS_SRI = {
    'AUTORIZADO': ComprobanteElectronico.AUTORIZADO,
    'NO AUTORIZADO': ComprobanteElectronico.NO_AUTORIZADO,
    'EN PROCESO': ComprobanteElectronico.EN_PROCESO,
    'NO_ENCONTRADO': ComprobanteElectronico.EN_PROCESO,
}


def _marcar_error_local(comprobante, mensaje):
    comprobante.estado = ComprobanteElectronico.ERROR
    comprobante.mensajes = (comprobante.mensajes or []) + [mensaje]
    comprobante.save(update_fields=['estado', 'mensajes'])


def consultar_autorizacion_publica(clave_acceso):
    """Punto de entrada de la API de verificación
    (facturacion_electronica/views.py -> verificar_autorizacion_api):
    consulta el SRI EN VIVO (a través del microservicio) por CUALQUIER clave
    de acceso, exista o no un ComprobanteElectronico local para ella. Deja
    escapar SRIError — la vista decide el status HTTP (502) según su propio
    criterio, no es "best effort" como el resto de este módulo."""
    try:
        response = requests.get(
            _url(f'/api/comprobantes/{clave_acceso}/estado-sri/'), headers=_headers(),
            timeout=settings.FACTURACION_ELECTRONICA_SERVICE_TIMEOUT,
        )
    except requests.RequestException as e:
        raise SRIError(f'No se pudo contactar al servicio de facturación electrónica: {e}') from e

    if response.status_code != 200:
        raise SRIError(response.json().get('error', 'Error desconocido del servicio de facturación electrónica.'))

    data = response.json()
    from django.utils.dateparse import parse_datetime
    fecha_autorizacion = parse_datetime(data['fecha_autorizacion']) if data.get('fecha_autorizacion') else None

    comprobante = ComprobanteElectronico.objects.filter(clave_acceso=clave_acceso).first()
    if comprobante is not None:
        comprobante.estado = _ESTADOS_SRI.get(data['estado_sri'], ComprobanteElectronico.EN_PROCESO)
        comprobante.numero_autorizacion = data.get('numero_autorizacion', '')
        if fecha_autorizacion:
            comprobante.fecha_autorizacion = fecha_autorizacion
        comprobante.mensajes = data.get('mensajes', [])
        comprobante.save(update_fields=['estado', 'numero_autorizacion', 'fecha_autorizacion', 'mensajes'])

    return data['estado_sri'], data.get('numero_autorizacion', ''), fecha_autorizacion, data.get('mensajes', [])
