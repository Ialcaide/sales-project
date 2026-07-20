"""
Funciones puras (sin vistas) que crean Notificacion — se llaman tanto desde
EVENTOS en tiempo real (justo cuando una venta baja el stock, justo cuando
se cierra una caja) como desde el comando periódico `generar_notificaciones`
para lo que depende del paso del tiempo (vencimientos, pagos atrasados).

No hay Celery ni cron configurado en este proyecto: en producción,
`generar_notificaciones` se agendaría con un cron diario (ej. Render Cron
Jobs) — ver notificaciones/management/commands/generar_notificaciones.py.
"""
from datetime import timedelta

from django.conf import settings
from django.urls import reverse
from django.utils import timezone

from shared.notifications import send_credentials_email, get_admin_recipients, send_telegram_message

from .models import Notificacion

DIAS_POR_TERMINO = {
    'credit_15': 15,
    'credit_30': 30,
    'credit_60': 60,
}
# DIAS_CREDITO_FACTURA_DEFAULT, DIAS_AVISO_VENCIMIENTO_PRODUCTO y
# DIAS_AVISO_PAGO_COMPRA ahora son configurables — ver
# ConfiguracionSistema.get_solo() en configuracion/models.py.


def _crear_si_no_existe(tipo, nivel, mensaje, clave, usuario=None, url=''):
    if Notificacion.objects.filter(clave=clave, leida=False).exists():
        return None
    notificacion = Notificacion.objects.create(
        tipo=tipo, nivel=nivel, mensaje=mensaje, clave=clave, usuario=usuario, url=url,
    )
    # Todas las alertas internas (campanita) pasan por acá — es el único
    # punto de integración necesario para que las 4 (stock bajo, caja,
    # productos por vencer, pagos pendientes) también lleguen a Telegram,
    # sin repetir esta llamada en cada función de arriba.
    texto = f'{mensaje}\n{settings.SITE_URL}{url}' if url else mensaje
    send_telegram_message(texto)
    return notificacion


def notificar_stock_bajo(product):
    """Se llama justo después de bajar el stock de una venta (billing/views.py -> invoice_create)."""
    if product.stock > product.stock_minimo:
        return None
    nivel = Notificacion.DANGER if product.stock <= 0 else Notificacion.WARNING
    url_relativa = reverse('billing:product_detail', args=[product.id])
    notificacion = _crear_si_no_existe(
        tipo=Notificacion.STOCK_BAJO, nivel=nivel,
        mensaje=f'Stock bajo: "{product.name}" tiene {product.stock} unidad(es) (mínimo {product.stock_minimo}).',
        clave=f'stock_bajo:producto:{product.id}',
        url=url_relativa,
    )
    # Correo a administradores: solo cuando de verdad se creó una
    # notificación nueva (no en cada venta mientras la anterior siga sin
    # leerse) — mismo criterio de "no repetir aviso" que ya aplica
    # _crear_si_no_existe() para la campanita.
    if notificacion is not None:
        for admin_nombre, admin_email in get_admin_recipients():
            send_credentials_email(
                admin_email, f'Stock bajo — {product.name}',
                (
                    f'Hola {admin_nombre},\n\n'
                    f'El producto "{product.name}" llegó a su stock mínimo: quedan {product.stock} '
                    f'unidad(es) (mínimo {product.stock_minimo}).\n\n'
                    f'Atentamente,\n'
                    f'Sistema de Ventas TecnoStock'
                ),
                html_template='inventario_bajo.html',
                html_context={
                    'usuario': admin_nombre, 'producto_nombre': product.name,
                    'stock_actual': product.stock, 'stock_minimo': product.stock_minimo,
                    'producto_url': f'{settings.SITE_URL}{url_relativa}',
                },
            )
    return notificacion


def notificar_caja_diferencia(sesion):
    """Se llama justo al cerrar una caja (caja/views.py -> caja_cerrar)."""
    diferencia = sesion.diferencia
    if not diferencia:
        return None
    nivel = Notificacion.DANGER if abs(diferencia) > 5 else Notificacion.WARNING
    palabra = 'sobra' if diferencia > 0 else 'falta'
    return _crear_si_no_existe(
        tipo=Notificacion.CAJA_ALERTA, nivel=nivel,
        mensaje=f'Caja #{sesion.id:04d} cerrada con diferencia: {palabra} ${abs(diferencia)}.',
        clave=f'caja_alerta:sesion:{sesion.id}',
        usuario=sesion.usuario,
        url=reverse('caja:caja_detalle', args=[sesion.id]),
    )


def sincronizar_productos_por_vencer(dias=None):
    """Productos activos con fecha_vencimiento dentro de `dias` (incluye ya vencidos).
    `dias=None` (default) toma el valor configurado — NO se puede usar
    `ConfiguracionSistema.get_solo()` como default del parámetro porque los
    defaults se evalúan una sola vez al importar el módulo, antes de que
    exista la fila de configuración."""
    from billing.models import Product
    from configuracion.models import ConfiguracionSistema

    if dias is None:
        dias = ConfiguracionSistema.get_solo().dias_aviso_vencimiento_producto

    limite = timezone.now().date() + timedelta(days=dias)
    creadas = []
    for product in Product.objects.filter(is_active=True, fecha_vencimiento__isnull=False, fecha_vencimiento__lte=limite):
        vencido = product.fecha_vencimiento < timezone.now().date()
        nivel = Notificacion.DANGER if vencido else Notificacion.WARNING
        estado = 'ya venció' if vencido else f'vence el {product.fecha_vencimiento:%d/%m/%Y}'
        n = _crear_si_no_existe(
            tipo=Notificacion.PRODUCTO_VENCE, nivel=nivel,
            mensaje=f'"{product.name}" {estado}.',
            clave=f'producto_vence:producto:{product.id}',
            url=reverse('billing:product_detail', args=[product.id]),
        )
        if n:
            creadas.append(n)
    return creadas


def sincronizar_pagos_pendientes():
    """Compras y facturas a crédito pendientes que están por vencer o ya vencieron."""
    from billing.models import Invoice
    from configuracion.models import ConfiguracionSistema
    from purchasing.models import Purchase

    config = ConfiguracionSistema.get_solo()
    creadas = []
    hoy = timezone.now().date()

    for purchase in Purchase.objects.select_related('supplier').filter(
        tipo_pago=Purchase.CREDITO, estado=Purchase.PENDIENTE
    ):
        limite = purchase.fecha_limite_pago
        if not limite or (limite - hoy).days > config.dias_aviso_pago_compra:
            continue
        vencida = limite < hoy
        nivel = Notificacion.DANGER if vencida else Notificacion.WARNING
        estado = f'venció el {limite:%d/%m/%Y}' if vencida else f'vence el {limite:%d/%m/%Y}'
        n = _crear_si_no_existe(
            tipo=Notificacion.PAGO_PENDIENTE, nivel=nivel,
            mensaje=f'Compra #{purchase.id:04d} ({purchase.supplier.name}) {estado} — saldo ${purchase.saldo}.',
            clave=f'pago_pendiente:compra:{purchase.id}',
            url=reverse('pagos:purchase_pending_list'),
        )
        if n:
            creadas.append(n)

    for invoice in Invoice.objects.select_related('customer', 'customer__profile').filter(
        tipo_pago=Invoice.CREDITO, estado=Invoice.PENDIENTE, is_active=True
    ):
        # Si la factura tiene meses_credito (plazo en meses, igual que
        # Purchase), se usa fecha_limite_pago — más preciso que los días
        # fijos de CustomerProfile.payment_terms. Si no (facturas viejas o
        # sin plazo definido), se cae al criterio anterior de días.
        if invoice.meses_credito:
            limite = invoice.fecha_limite_pago
            if (limite - hoy).days > config.dias_aviso_pago_compra:
                continue
            vencida = limite < hoy
            nivel = Notificacion.DANGER if vencida else Notificacion.WARNING
            estado = f'venció el {limite:%d/%m/%Y}' if vencida else f'vence el {limite:%d/%m/%Y}'
            mensaje = f'Factura #{invoice.id:04d} ({invoice.customer}) {estado} — saldo ${invoice.saldo}.'
        else:
            profile = getattr(invoice.customer, 'profile', None)
            dias_plazo = DIAS_POR_TERMINO.get(
                profile.payment_terms if profile else None, config.dias_credito_factura_default
            )
            dias_transcurridos = (timezone.now() - invoice.invoice_date).days
            if dias_transcurridos < dias_plazo:
                continue
            nivel = Notificacion.DANGER
            mensaje = (
                f'Factura #{invoice.id:04d} ({invoice.customer}) lleva {dias_transcurridos} días pendiente '
                f'(plazo: {dias_plazo}) — saldo ${invoice.saldo}.'
            )
        n = _crear_si_no_existe(
            tipo=Notificacion.PAGO_PENDIENTE, nivel=nivel,
            mensaje=mensaje,
            clave=f'pago_pendiente:factura:{invoice.id}',
            url=reverse('cobros:invoice_pending_list'),
        )
        if n:
            creadas.append(n)

    return creadas
