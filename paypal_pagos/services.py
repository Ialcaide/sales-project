"""
Funciones que arman una orden de PayPal y, una vez capturado el pago,
aplican sus efectos reales (crear la Invoice o el CobroFactura) — mismo
espíritu que notificaciones/services.py: la lógica de negocio vive acá,
separada de las vistas (paypal_pagos/views.py) para poder llamarla tanto
desde la vista de retorno como desde el webhook.
"""
from decimal import Decimal

from django.conf import settings
from django.db import transaction
from django.urls import reverse

from .client import PayPalError, capturar_orden, crear_orden
from .models import OrdenPaypal


def _url_absoluta(request_o_none, path):
    """Arma una URL absoluta para los return_url/cancel_url que le pasamos a
    PayPal (necesita http(s)://dominio, no solo el path) — reutiliza
    SITE_URL (config/settings.py) igual que el resto del proyecto (ver
    security/views.py para el mismo patrón con los links de credenciales)."""
    return f'{settings.SITE_URL}{path}'


def crear_orden_venta(datos_venta, usuario):
    """`datos_venta`: {'customer_id', 'tipo_pago', 'lineas': [{'product_id','quantity','unit_price'}]}.
    Calcula el monto desde las líneas (mismo IVA configurado que usa
    _finalizar_venta) y crea la orden en PayPal. Devuelve la OrdenPaypal
    creada (con .approval_url disponible solo en el momento, no se guarda)."""
    from billing.models import Product
    from configuracion.models import ConfiguracionSistema

    config = ConfiguracionSistema.get_solo()
    subtotal = sum(
        Decimal(linea['unit_price']) * linea['quantity'] for linea in datos_venta['lineas']
    )
    tax = (subtotal * config.iva_fraccion).quantize(Decimal('0.01'))
    total = subtotal + tax

    referencia = f'venta:{usuario.id}:{datos_venta["customer_id"]}'
    order_id, approval_url = crear_orden(
        monto=total, referencia=referencia,
        return_url=_url_absoluta(None, reverse('paypal_pagos:paypal_return')),
        cancel_url=_url_absoluta(None, reverse('paypal_pagos:paypal_cancel')),
    )

    orden = OrdenPaypal.objects.create(
        paypal_order_id=order_id, tipo=OrdenPaypal.VENTA, monto=total,
        payload=datos_venta, creado_por=usuario,
    )
    orden.approval_url = approval_url  # no es un campo del modelo, solo para esta respuesta
    return orden


def crear_orden_cobro(factura, monto, usuario):
    """Crea una orden de PayPal para pagar (total o parcialmente) el saldo
    de una factura a crédito pendiente. `monto` ya viene validado por el
    caller (no puede superar factura.saldo — misma regla que CobroFactura.clean())."""
    referencia = f'cobro:factura:{factura.id}'
    order_id, approval_url = crear_orden(
        monto=monto, referencia=referencia,
        return_url=_url_absoluta(None, reverse('paypal_pagos:paypal_return')),
        cancel_url=_url_absoluta(None, reverse('paypal_pagos:paypal_cancel')),
    )

    orden = OrdenPaypal.objects.create(
        paypal_order_id=order_id, tipo=OrdenPaypal.COBRO, monto=monto,
        payload={'factura_id': factura.id}, creado_por=usuario,
    )
    orden.approval_url = approval_url
    return orden


def finalizar_orden(orden_o_order_id):
    """Captura el pago en PayPal y, si se completó, aplica sus efectos
    reales. Idempotente: se puede llamar más de una vez para la MISMA orden
    (tanto la vista de retorno como el webhook pueden dispararla para el
    mismo pago) sin duplicar la Invoice/CobroFactura — select_for_update()
    + el chequeo de `estado` adentro de la transacción garantizan que solo
    la primera llamada realmente hace algo.
    """
    with transaction.atomic():
        if isinstance(orden_o_order_id, OrdenPaypal):
            orden = OrdenPaypal.objects.select_for_update().get(pk=orden_o_order_id.pk)
        else:
            orden = OrdenPaypal.objects.select_for_update().get(paypal_order_id=orden_o_order_id)

        if orden.estado != OrdenPaypal.CREADA:
            return orden  # ya se procesó (por la otra vía) o ya falló/canceló

        try:
            status = capturar_orden(orden.paypal_order_id)
        except PayPalError:
            orden.estado = OrdenPaypal.FALLIDA
            orden.save(update_fields=['estado', 'actualizado_en'])
            return orden

        if status != 'COMPLETED':
            orden.estado = OrdenPaypal.FALLIDA
            orden.save(update_fields=['estado', 'actualizado_en'])
            return orden

        if orden.tipo == OrdenPaypal.VENTA:
            _aplicar_venta(orden)
        else:
            _aplicar_cobro(orden)

        orden.estado = OrdenPaypal.CAPTURADA
        orden.save(update_fields=['estado', 'invoice', 'cobro', 'actualizado_en'])
        return orden


def _aplicar_venta(orden):
    from billing.models import Customer, Product
    from billing.views import _finalizar_venta

    payload = orden.payload
    customer = Customer.objects.get(pk=payload['customer_id'])
    lineas = [
        {
            'product': Product.objects.get(pk=linea['product_id']),
            'quantity': linea['quantity'],
            'unit_price': Decimal(linea['unit_price']),
        }
        for linea in payload['lineas']
    ]
    invoice, _email_enviado = _finalizar_venta(
        customer, payload['tipo_pago'], 'paypal', lineas, orden.creado_por,
    )
    orden.invoice = invoice


def _aplicar_cobro(orden):
    from django.utils import timezone

    from cobros.models import CobroFactura

    cobro = CobroFactura(
        factura_id=orden.payload['factura_id'], valor=orden.monto, fecha=timezone.now().date(),
        forma_pago=CobroFactura.PAYPAL,
        observacion=f'Pago con PayPal (orden {orden.paypal_order_id})',
    )
    cobro.save()
    orden.cobro = cobro
