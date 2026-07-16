import json
import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .client import verificar_firma_webhook
from .models import OrdenPaypal
from .services import finalizar_orden

logger = logging.getLogger(__name__)


@login_required
def paypal_return(request):
    """PayPal redirige acá (?token=<order_id>) cuando el comprador aprobó el
    pago en su sitio — se captura de verdad y recién ahí se crea la
    Invoice/CobroFactura real (ver paypal_pagos/services.py -> finalizar_orden)."""
    order_id = request.GET.get('token')
    orden = get_object_or_404(OrdenPaypal, paypal_order_id=order_id)

    orden = finalizar_orden(orden)

    if orden.estado == OrdenPaypal.CAPTURADA:
        if orden.tipo == OrdenPaypal.VENTA and orden.invoice_id:
            messages.success(request, f'¡Pago con PayPal confirmado! Factura #{orden.invoice_id} creada.')
            return redirect('billing:invoice_detail', pk=orden.invoice_id)
        messages.success(request, '¡Pago con PayPal confirmado! El cobro quedó registrado.')
        return redirect('cobros:invoice_pending_list')

    messages.error(request, 'No se pudo confirmar el pago con PayPal. Intenta de nuevo.')
    if orden.tipo == OrdenPaypal.VENTA:
        return redirect('billing:invoice_create')
    return redirect('cobros:invoice_pending_list')


@login_required
def paypal_cancel(request):
    """PayPal redirige acá cuando el comprador cancela el checkout. Como la
    Invoice/CobroFactura real nunca se crea hasta la captura, no hay nada
    que revertir — solo se marca la orden como cancelada."""
    order_id = request.GET.get('token')
    orden = get_object_or_404(OrdenPaypal, paypal_order_id=order_id)

    if orden.estado == OrdenPaypal.CREADA:
        orden.estado = OrdenPaypal.CANCELADA
        orden.save(update_fields=['estado', 'actualizado_en'])

    messages.info(request, 'Pago con PayPal cancelado.')
    if orden.tipo == OrdenPaypal.VENTA:
        return redirect('billing:invoice_create')
    return redirect('cobros:invoice_pending_list')


@csrf_exempt
@require_POST
def paypal_webhook(request):
    """Notificación server-to-server de PayPal — no tiene cookie de sesión
    (por eso @csrf_exempt), su autenticidad depende ENTERAMENTE de
    verificar_firma_webhook(). Es el respaldo del retorno síncrono
    (paypal_return): si el comprador cierra la pestaña justo después de
    pagar y nunca vuelve, esta es la única confirmación que llega."""
    try:
        body_parsed = json.loads(request.body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return HttpResponseBadRequest('JSON inválido')

    if not verificar_firma_webhook(request.headers, body_parsed):
        logger.warning('Webhook de PayPal con firma inválida, se rechaza.')
        return HttpResponseBadRequest('Firma inválida')

    event_type = body_parsed.get('event_type', '')
    if event_type not in ('CHECKOUT.ORDER.APPROVED', 'PAYMENT.CAPTURE.COMPLETED'):
        return HttpResponse(status=200)  # evento que no nos interesa, pero la firma era válida

    resource = body_parsed.get('resource', {})
    # PAYMENT.CAPTURE.COMPLETED: resource.id es el ID de la CAPTURA, no de la
    # orden — el order_id real vive en supplementary_data.related_ids. Para
    # CHECKOUT.ORDER.APPROVED, en cambio, resource SÍ es la orden y resource.id
    # ya es el order_id — por eso se prueba primero el campo específico de
    # capturas y se cae al genérico solo si no está.
    order_id = resource.get('supplementary_data', {}).get('related_ids', {}).get('order_id') or resource.get('id')
    if not order_id:
        return HttpResponse(status=200)

    try:
        orden = OrdenPaypal.objects.get(paypal_order_id=order_id)
    except OrdenPaypal.DoesNotExist:
        logger.warning('Webhook de PayPal para una orden desconocida: %s', order_id)
        return HttpResponse(status=200)

    finalizar_orden(orden)
    return HttpResponse(status=200)
