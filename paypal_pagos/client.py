"""
Wrapper delgado sobre la API REST v2 de PayPal (Orders API), usando
`requests` directo en vez de un SDK oficial (evita una dependencia pesada
por 3 llamadas HTTP). Es el ÚNICO lugar del proyecto que le habla a PayPal
— paypal_pagos/services.py nunca arma una request acá adentro, siempre
llama a una de estas funciones (mismo patrón que shared/notifications.py
con Twilio/email).

A diferencia de shared/notifications.py (que nunca deja escapar una
excepción porque el correo/WhatsApp es "best effort"), acá SÍ se propaga
PayPalError cuando algo falla: un pago que no se pudo iniciar o confirmar
tiene que ser visible para quien lo dispara, no silenciarse.
"""
import logging

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

SANDBOX_BASE = 'https://api-m.sandbox.paypal.com'
LIVE_BASE = 'https://api-m.paypal.com'


class PayPalError(Exception):
    """Algo falló al hablar con la API de PayPal (red, credenciales, respuesta inesperada)."""


class PayPalNoConfiguradoError(PayPalError):
    """PAYPAL_CLIENT_ID/PAYPAL_CLIENT_SECRET no están configurados en el .env."""


def _api_base():
    return LIVE_BASE if settings.PAYPAL_MODE == 'live' else SANDBOX_BASE


def _verificar_configurado():
    if not (settings.PAYPAL_CLIENT_ID and settings.PAYPAL_CLIENT_SECRET):
        raise PayPalNoConfiguradoError(
            'PayPal no está configurado: faltan PAYPAL_CLIENT_ID/PAYPAL_CLIENT_SECRET en el .env.'
        )


def obtener_access_token():
    """OAuth2 client_credentials — no se cachea el token (tráfico bajo de
    este sistema, prioriza simplicidad sobre una capa de cache adicional)."""
    _verificar_configurado()
    try:
        response = requests.post(
            f'{_api_base()}/v1/oauth2/token',
            auth=(settings.PAYPAL_CLIENT_ID, settings.PAYPAL_CLIENT_SECRET),
            data={'grant_type': 'client_credentials'},
            timeout=15,
        )
        response.raise_for_status()
        return response.json()['access_token']
    except requests.RequestException as e:
        logger.exception('No se pudo obtener el access token de PayPal')
        raise PayPalError('No se pudo autenticar con PayPal.') from e


def crear_orden(monto, referencia, return_url, cancel_url):
    """Crea una orden en PayPal (Orders API v2) y devuelve (order_id, approval_url)."""
    token = obtener_access_token()
    body = {
        'intent': 'CAPTURE',
        'purchase_units': [{
            'reference_id': referencia,
            'amount': {'currency_code': 'USD', 'value': f'{monto:.2f}'},
        }],
        'application_context': {
            'return_url': return_url,
            'cancel_url': cancel_url,
            'user_action': 'PAY_NOW',
        },
    }
    try:
        response = requests.post(
            f'{_api_base()}/v2/checkout/orders',
            headers={'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'},
            json=body,
            timeout=15,
        )
        response.raise_for_status()
        data = response.json()
    except requests.RequestException as e:
        logger.exception('No se pudo crear la orden de PayPal (referencia=%s)', referencia)
        raise PayPalError('No se pudo crear la orden de pago en PayPal.') from e

    approval_url = next((link['href'] for link in data.get('links', []) if link.get('rel') == 'approve'), None)
    if not approval_url:
        raise PayPalError('PayPal no devolvió un link de aprobación para la orden.')
    return data['id'], approval_url


def capturar_orden(order_id):
    """Captura (cobra de verdad) una orden ya aprobada por el comprador.
    Devuelve el status devuelto por PayPal (ej. 'COMPLETED')."""
    token = obtener_access_token()
    try:
        response = requests.post(
            f'{_api_base()}/v2/checkout/orders/{order_id}/capture',
            headers={'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'},
            timeout=15,
        )
        response.raise_for_status()
        return response.json().get('status')
    except requests.RequestException as e:
        logger.exception('No se pudo capturar la orden de PayPal %s', order_id)
        raise PayPalError('No se pudo confirmar el pago con PayPal.') from e


def crear_payout(monto, referencia, receiver_email, nota=''):
    """Payouts API v1 — dinero SALIENDO del negocio hacia un tercero (ej.
    pagarle a un proveedor). A diferencia de crear_orden()/capturar_orden()
    (Orders API, dinero ENTRANDO, con un paso de aprobación del comprador
    en paypal.com), acá no hay checkout ni redirect: PayPal resuelve el
    envío en esta misma llamada (normalmente queda 'PENDING' de inmediato
    y se termina de procesar del lado de PayPal, sin que este sistema
    necesite esperar más). Devuelve (payout_batch_id, batch_status)."""
    if not receiver_email:
        raise PayPalError('Falta el correo del destinatario para enviar el pago por PayPal.')
    token = obtener_access_token()
    body = {
        'sender_batch_header': {
            'sender_batch_id': referencia,
            'email_subject': 'Pago recibido',
            'email_message': nota or 'Pago registrado desde TecnoStock S.A.',
        },
        'items': [{
            'recipient_type': 'EMAIL',
            'amount': {'value': f'{monto:.2f}', 'currency': 'USD'},
            'receiver': receiver_email,
            'note': nota,
            'sender_item_id': referencia,
        }],
    }
    try:
        response = requests.post(
            f'{_api_base()}/v1/payments/payouts',
            headers={'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'},
            json=body,
            timeout=15,
        )
        response.raise_for_status()
        data = response.json()
    except requests.RequestException as e:
        logger.exception('No se pudo crear el payout de PayPal (referencia=%s)', referencia)
        raise PayPalError('No se pudo enviar el pago por PayPal.') from e

    batch_header = data.get('batch_header', {})
    batch_id = batch_header.get('payout_batch_id')
    if not batch_id:
        raise PayPalError('PayPal no devolvió un ID de lote para el pago.')
    return batch_id, batch_header.get('batch_status')


def verificar_firma_webhook(headers, body_parsed):
    """Verifica que una notificación de webhook realmente viene de PayPal
    (no de cualquiera que le pegue un POST a la URL). `headers` es un dict
    con los headers HTTP tal como llegaron (case-insensitive), `body_parsed`
    es el JSON ya parseado del body."""
    if not settings.PAYPAL_WEBHOOK_ID:
        logger.warning('PAYPAL_WEBHOOK_ID no configurado: no se puede verificar la firma del webhook.')
        return False
    token = obtener_access_token()
    payload = {
        'transmission_id': headers.get('Paypal-Transmission-Id'),
        'transmission_time': headers.get('Paypal-Transmission-Time'),
        'cert_url': headers.get('Paypal-Cert-Url'),
        'auth_algo': headers.get('Paypal-Auth-Algo'),
        'transmission_sig': headers.get('Paypal-Transmission-Sig'),
        'webhook_id': settings.PAYPAL_WEBHOOK_ID,
        'webhook_event': body_parsed,
    }
    try:
        response = requests.post(
            f'{_api_base()}/v1/notifications/verify-webhook-signature',
            headers={'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'},
            json=payload,
            timeout=15,
        )
        response.raise_for_status()
        return response.json().get('verification_status') == 'SUCCESS'
    except requests.RequestException:
        logger.exception('No se pudo verificar la firma del webhook de PayPal')
        return False
