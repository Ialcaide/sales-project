"""
Wrapper delgado sobre los web services SOAP del SRI (recepción y
autorización de comprobantes electrónicos), usando `zeep`. Es el ÚNICO
lugar del proyecto que le habla al SRI por red — mismo espíritu que
`paypal_pagos/client.py`: acá solo se arma/interpreta la llamada SOAP,
`facturacion_electronica/services.py` nunca la arma él mismo.

Los clientes de `zeep` se construyen bajo demanda (no al importar este
módulo) para que los tests puedan mockearlos sin tocar la red real, y para
no pagar el costo de descargar el WSDL si nunca se usa esta app.
"""
import logging

from zeep import Client
from zeep.exceptions import Fault, TransportError

import config

logger = logging.getLogger(__name__)

# Ambiente de PRUEBAS (certificación) — no genera obligación tributaria real.
RECEPCION_WSDL_PRUEBAS = 'https://celcer.sri.gob.ec/comprobantes-electronicos-ws/RecepcionComprobantesOffline?wsdl'
AUTORIZACION_WSDL_PRUEBAS = 'https://celcer.sri.gob.ec/comprobantes-electronicos-ws/AutorizacionComprobantesOffline?wsdl'

# Ambiente de PRODUCCIÓN — facturas reales, con validez tributaria.
RECEPCION_WSDL_PRODUCCION = 'https://cel.sri.gob.ec/comprobantes-electronicos-ws/RecepcionComprobantesOffline?wsdl'
AUTORIZACION_WSDL_PRODUCCION = 'https://cel.sri.gob.ec/comprobantes-electronicos-ws/AutorizacionComprobantesOffline?wsdl'


class SRIError(Exception):
    """Algo falló al hablar con los web services del SRI (red, WSDL,
    respuesta inesperada). A diferencia de shared/notifications.py, acá SÍ
    se propaga — pero facturacion_electronica/services.py la atrapa para
    que un fallo del SRI nunca tumbe la venta (ver ese módulo)."""


def _es_produccion():
    return config.SRI_AMBIENTE == 'produccion'


def _recepcion_client():
    url = RECEPCION_WSDL_PRODUCCION if _es_produccion() else RECEPCION_WSDL_PRUEBAS
    return Client(url)


def _autorizacion_client():
    url = AUTORIZACION_WSDL_PRODUCCION if _es_produccion() else AUTORIZACION_WSDL_PRUEBAS
    return Client(url)


def enviar_recepcion(xml_firmado_bytes):
    """Envía el XML ya firmado al web service de recepción. Devuelve
    (estado, mensajes): estado es 'RECIBIDA' o 'DEVUELTA'; mensajes es una
    lista de strings (vacía si RECIBIDA sin observaciones)."""
    try:
        client = _recepcion_client()
        # OJO: NO codificar en base64 acá — el WSDL declara `xml` como
        # xsd:base64Binary, así que zeep YA hace esa codificación solo al
        # serializar la llamada SOAP. Pasarle bytes ya codificados (como se
        # hacía antes) produce una doble codificación: el SRI decodifica una
        # sola vez y recibe puro texto base64 en vez del XML real, lo
        # rechaza con "35: ARCHIVO NO CUMPLE ESTRUCTURA XML" sin importar
        # qué tan válido sea el XML de origen. Confirmado con
        # zeep.xsd.Base64Binary().xmlvalue() y con un envío real de prueba.
        respuesta = client.service.validarComprobante(xml=xml_firmado_bytes)
    except (Fault, TransportError, Exception) as e:  # noqa: BLE001 - cualquier falla de red/SOAP debe quedar visible
        logger.exception('No se pudo enviar el comprobante al SRI (recepción)')
        raise SRIError(f'No se pudo enviar el comprobante al SRI: {e}') from e

    estado = getattr(respuesta, 'estado', None)
    mensajes = []
    comprobantes = getattr(respuesta, 'comprobantes', None)
    if comprobantes is not None:
        for comprobante in getattr(comprobantes, 'comprobante', []) or []:
            for mensaje in getattr(comprobante, 'mensajes', None) and comprobante.mensajes.mensaje or []:
                identificador = getattr(mensaje, 'identificador', '')
                texto = getattr(mensaje, 'mensaje', '')
                mensajes.append(f'{identificador}: {texto}'.strip(': '))
    return estado, mensajes


def consultar_autorizacion(clave_acceso):
    """Consulta el estado de autorización de un comprobante ya enviado.
    Devuelve (estado, numero_autorizacion, fecha_autorizacion, xml_autorizado,
    mensajes). estado es 'AUTORIZADO', 'NO AUTORIZADO', 'EN PROCESO', o
    'NO_ENCONTRADO' si el SRI no tiene registro de esa clave todavía."""
    try:
        client = _autorizacion_client()
        respuesta = client.service.autorizacionComprobante(claveAccesoComprobante=clave_acceso)
    except (Fault, TransportError, Exception) as e:  # noqa: BLE001
        logger.exception('No se pudo consultar la autorización en el SRI (clave=%s)', clave_acceso)
        raise SRIError(f'No se pudo consultar la autorización en el SRI: {e}') from e

    autorizaciones = getattr(respuesta, 'autorizaciones', None)
    lista = getattr(autorizaciones, 'autorizacion', None) if autorizaciones is not None else None
    if not lista:
        return 'NO_ENCONTRADO', '', None, '', []

    autorizacion = lista[0]
    estado = getattr(autorizacion, 'estado', '')
    numero_autorizacion = getattr(autorizacion, 'numeroAutorizacion', '') or ''
    fecha_autorizacion = getattr(autorizacion, 'fechaAutorizacion', None)
    xml_autorizado = getattr(autorizacion, 'comprobante', '') or ''
    mensajes = []
    for mensaje in getattr(autorizacion, 'mensajes', None) and autorizacion.mensajes.mensaje or []:
        identificador = getattr(mensaje, 'identificador', '')
        texto = getattr(mensaje, 'mensaje', '')
        mensajes.append(f'{identificador}: {texto}'.strip(': '))
    return estado, numero_autorizacion, fecha_autorizacion, xml_autorizado, mensajes
