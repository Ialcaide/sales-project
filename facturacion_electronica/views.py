import hmac

from django.conf import settings
from django.contrib import messages
from django.core.cache import cache
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.csrf import csrf_exempt

from billing.models import Invoice
from shared.decorators import permission_required_redirect

from .models import ComprobanteElectronico
from .services import SRIError, consultar_autorizacion_manual, consultar_autorizacion_publica, reintentar


# Botón "Reintentar generación" en invoice_detail.html — para el caso borde
# en que la generación automática (billing/views.py -> _finalizar_venta)
# falló (SRI caído, certificado mal configurado) o la factura no tiene
# comprobante todavía.
@permission_required_redirect('facturacion_electronica.add_comprobanteelectronico', '/invoices/')
def comprobante_reintentar(request, invoice_id):
    invoice = get_object_or_404(Invoice, pk=invoice_id)
    comprobante = reintentar(invoice)
    if comprobante is None:
        messages.error(
            request,
            'No se pudo generar el comprobante: revisa la configuración de SRI en Configuración del Sistema.'
        )
    elif comprobante.estado == ComprobanteElectronico.AUTORIZADO:
        messages.success(request, f'Comprobante autorizado por el SRI (N° {comprobante.numero_autorizacion}).')
    elif comprobante.estado == ComprobanteElectronico.ERROR:
        mensaje = comprobante.mensajes[-1] if comprobante.mensajes else 'Error desconocido.'
        messages.error(request, f'No se pudo generar/enviar el comprobante: {mensaje}')
    else:
        messages.info(request, f'Comprobante en estado: {comprobante.get_estado_display()}.')
    return redirect('billing:invoice_detail', pk=invoice_id)


# Botón "Consultar autorización" — para cuando el SRI quedó EN_PROCESO (o
# RECIBIDA sin haber podido consultar en el momento) en el intento
# automático o en un reintento.
@permission_required_redirect('facturacion_electronica.view_comprobanteelectronico', '/invoices/')
def comprobante_consultar_autorizacion(request, pk):
    comprobante = get_object_or_404(ComprobanteElectronico, pk=pk)
    comprobante = consultar_autorizacion_manual(comprobante)
    if comprobante.estado == ComprobanteElectronico.AUTORIZADO:
        messages.success(request, f'Comprobante autorizado por el SRI (N° {comprobante.numero_autorizacion}).')
    elif comprobante.estado == ComprobanteElectronico.NO_AUTORIZADO:
        mensaje = comprobante.mensajes[-1] if comprobante.mensajes else ''
        messages.error(request, f'El SRI no autorizó el comprobante. {mensaje}')
    elif comprobante.estado == ComprobanteElectronico.ERROR:
        mensaje = comprobante.mensajes[-1] if comprobante.mensajes else 'Error desconocido.'
        messages.error(request, f'No se pudo consultar la autorización: {mensaje}')
    else:
        messages.info(request, f'El SRI todavía no autoriza el comprobante (estado: {comprobante.get_estado_display()}).')
    return redirect('billing:invoice_detail', pk=comprobante.invoice_id)


@permission_required_redirect('facturacion_electronica.view_comprobanteelectronico', '/invoices/')
def comprobante_xml_download(request, pk):
    comprobante = get_object_or_404(ComprobanteElectronico, pk=pk)
    xml = comprobante.xml_autorizado or comprobante.xml_firmado or comprobante.xml_generado
    if not xml:
        messages.error(request, 'Este comprobante todavía no tiene un XML generado.')
        return redirect('billing:invoice_detail', pk=comprobante.invoice_id)
    response = HttpResponse(xml, content_type='application/xml')
    response['Content-Disposition'] = f'attachment; filename="{comprobante.clave_acceso}.xml"'
    return response


@permission_required_redirect('facturacion_electronica.view_comprobanteelectronico', '/invoices/')
def comprobante_ride_pdf(request, pk):
    from .ride import build_ride_pdf

    comprobante = get_object_or_404(ComprobanteElectronico, pk=pk)
    try:
        pdf_bytes = build_ride_pdf(comprobante)
    except SRIError as e:
        messages.error(request, f'No se pudo generar el RIDE: {e}')
        return redirect('billing:invoice_detail', pk=comprobante.invoice_id)
    response = HttpResponse(pdf_bytes, content_type='application/pdf')
    response['Content-Disposition'] = f'inline; filename="ride_{comprobante.clave_acceso}.pdf"'
    return response


# ---------------------------------------------------------------------------
# API de verificación de facturas ante el SRI — a diferencia de las vistas de
# arriba (atadas a una factura/comprobante puntual de nuestra base, sesión +
# permiso solamente), esta es reutilizable desde cualquier parte del sistema
# O desde un cliente externo con API key, y funciona para CUALQUIER clave de
# acceso (nuestra o no) — ver consultar_autorizacion_publica() en services.py.
# ---------------------------------------------------------------------------

RATE_LIMIT_MAX = 20
RATE_LIMIT_WINDOW = 60


def _autenticado(request):
    """True si el caller es una sesión Django con el permiso de siempre, O
    trae la API key correcta en el header X-API-Key. Comparación en tiempo
    constante (hmac.compare_digest) para no filtrar la key por timing —
    un solo secreto compartido en .env, mismo criterio que
    SRI_CERTIFICADO_PASSWORD (ver settings.SRI_VERIFICACION_API_KEY)."""
    if request.user.is_authenticated and request.user.has_perm('facturacion_electronica.view_comprobanteelectronico'):
        return True, 'session'
    api_key = request.headers.get('X-API-Key', '')
    if settings.SRI_VERIFICACION_API_KEY and hmac.compare_digest(api_key, settings.SRI_VERIFICACION_API_KEY):
        return True, 'api_key'
    return False, None


def _rate_limit_excedido(identificador):
    """Contador simple en el cache de Django — no hay django-ratelimit ni
    Celery en este proyecto, esto alcanza para el volumen de esta API.
    Con el cache por defecto (LocMemCache) el contador es por proceso; si
    el deploy corre varios workers gunicorn el límite real efectivo es
    RATE_LIMIT_MAX * (número de workers), aceptable para esta escala."""
    key = f'sri_verificacion_rate:{identificador}'
    intentos = cache.get(key, 0)
    if intentos >= RATE_LIMIT_MAX:
        return True
    cache.set(key, intentos + 1, timeout=RATE_LIMIT_WINDOW)
    return False


@csrf_exempt
def verificar_autorizacion_api(request):
    """Verifica el estado de autorización de un comprobante ante el SRI,
    EN VIVO, exista o no un ComprobanteElectronico local para esa clave.
    Acepta `clave_acceso` (49 dígitos) o `invoice_id` (resuelve la clave
    desde el comprobante de esa factura, solo para llamadas internas).

    @csrf_exempt: es de solo lectura desde la perspectiva del caller (a lo
    sumo sincroniza un comprobante ya existente con su propio estado real
    del SRI, nada que un CSRF pudiera usar para escalar privilegios ni
    mover dinero/inventario) — mismo criterio que
    paypal_pagos/views.py -> paypal_webhook."""
    ok, modo = _autenticado(request)
    if not ok:
        return JsonResponse({'ok': False, 'error': 'No autenticado.'}, status=401)

    identificador = request.user.pk if modo == 'session' else request.headers.get('X-API-Key', '')[:8]
    if _rate_limit_excedido(identificador):
        return JsonResponse({'ok': False, 'error': 'Demasiadas solicitudes, intenta más tarde.'}, status=429)

    clave_acceso = request.GET.get('clave_acceso') or request.POST.get('clave_acceso')
    invoice_id = request.GET.get('invoice_id') or request.POST.get('invoice_id')

    if not clave_acceso and invoice_id:
        try:
            invoice = Invoice.objects.get(pk=invoice_id)
        except Invoice.DoesNotExist:
            return JsonResponse({'ok': False, 'error': 'invoice_id inválido.'}, status=400)
        comprobante = getattr(invoice, 'comprobante_electronico', None)
        if comprobante is None:
            return JsonResponse({'ok': False, 'error': 'Esa factura no tiene comprobante electrónico.'}, status=400)
        clave_acceso = comprobante.clave_acceso

    if not clave_acceso or len(clave_acceso) != 49 or not clave_acceso.isdigit():
        return JsonResponse({'ok': False, 'error': 'clave_acceso inválida: debe tener 49 dígitos.'}, status=400)

    try:
        estado, numero_autorizacion, fecha_autorizacion, mensajes = consultar_autorizacion_publica(clave_acceso)
    except SRIError as e:
        return JsonResponse({'ok': False, 'error': str(e)}, status=502)

    return JsonResponse({
        'ok': True,
        'clave_acceso': clave_acceso,
        'estado_sri': estado,
        'autorizado': estado == 'AUTORIZADO',
        'numero_autorizacion': numero_autorizacion,
        'fecha_autorizacion': fecha_autorizacion.isoformat() if fecha_autorizacion else None,
        'mensajes': mensajes,
    })
