from django.conf import settings
from django.db import models


class OrdenPaypal(models.Model):
    """Puente entre crear una orden en PayPal y confirmar el pago después
    (la aprobación es asíncrona: el navegador sale del sitio a paypal.com y
    vuelve). No se crea la Invoice/CobroFactura real hasta que el pago se
    captura de verdad — así nunca queda una venta/cobro a medias si el
    cliente cancela o cierra la pestaña antes de pagar. Ver
    paypal_pagos/services.py -> finalizar_orden()."""

    VENTA = 'venta'
    COBRO = 'cobro'
    TIPO_CHOICES = [
        (VENTA, 'Venta'),
        (COBRO, 'Cobro de factura'),
    ]

    CREADA = 'creada'
    CAPTURADA = 'capturada'
    CANCELADA = 'cancelada'
    FALLIDA = 'fallida'
    ESTADO_CHOICES = [
        (CREADA, 'Creada'),
        (CAPTURADA, 'Capturada'),
        (CANCELADA, 'Cancelada'),
        (FALLIDA, 'Fallida'),
    ]

    paypal_order_id = models.CharField(max_length=50, unique=True, verbose_name='ID de orden PayPal')
    tipo = models.CharField(max_length=10, choices=TIPO_CHOICES, verbose_name='Tipo')
    estado = models.CharField(max_length=10, choices=ESTADO_CHOICES, default=CREADA, verbose_name='Estado')
    monto = models.DecimalField(max_digits=12, decimal_places=2, verbose_name='Monto')
    # Datos para reconstruir la operación al capturar el pago — ver
    # paypal_pagos/services.py para la forma exacta según `tipo`.
    payload = models.JSONField(verbose_name='Datos de la operación')
    creado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='ordenes_paypal', verbose_name='Creado por',
    )
    invoice = models.ForeignKey(
        'billing.Invoice', null=True, blank=True, on_delete=models.SET_NULL,
        related_name='ordenes_paypal', verbose_name='Factura generada',
    )
    cobro = models.ForeignKey(
        'cobros.CobroFactura', null=True, blank=True, on_delete=models.SET_NULL,
        related_name='ordenes_paypal', verbose_name='Cobro generado',
    )
    creado_en = models.DateTimeField(auto_now_add=True, verbose_name='Fecha de creación')
    actualizado_en = models.DateTimeField(auto_now=True, verbose_name='Última actualización')

    class Meta:
        verbose_name = 'Orden de PayPal'
        verbose_name_plural = 'Órdenes de PayPal'
        ordering = ['-creado_en']

    def __str__(self):
        return f'Orden PayPal {self.paypal_order_id} ({self.get_estado_display()})'
