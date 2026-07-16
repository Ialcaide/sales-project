from decimal import Decimal
from django.core.exceptions import ValidationError
from django.db import models, transaction
from purchasing.models import Purchase


class PagoCompra(models.Model):
    """
    Abono a una Purchase (Compra) a crédito. Cada save()/delete() recalcula
    el saldo y estado de la compra asociada dentro de una transacción (con
    select_for_update para evitar que dos pagos concurrentes descuadren el
    saldo) — así el saldo de la Purchase nunca se actualiza "a mano" desde
    las vistas, siempre pasa por acá.
    """
    # Solo informativo (con qué medio se le pagó de verdad al proveedor,
    # fuera del sistema) — a diferencia de billing.Invoice.forma_pago=PAYPAL,
    # acá no dispara ninguna integración real: pagarle a un proveedor por
    # PayPal es un ENVÍO de dinero (API de Payouts), no una recepción de pago
    # (API de Checkout, la que sí usa paypal_pagos), así que queda fuera de
    # alcance — esto solo deja constancia de cómo se pagó.
    EFECTIVO = 'efectivo'
    PAYPAL = 'paypal'
    FORMA_PAGO_CHOICES = [
        (EFECTIVO, 'Efectivo'),
        (PAYPAL, 'PayPal'),
    ]

    compra = models.ForeignKey(
        Purchase, on_delete=models.PROTECT, related_name='pagos', verbose_name='Compra'
    )
    fecha = models.DateField(verbose_name='Fecha de pago')
    valor = models.DecimalField(max_digits=10, decimal_places=2, verbose_name='Valor')
    forma_pago = models.CharField(
        max_length=15, choices=FORMA_PAGO_CHOICES, default=EFECTIVO, verbose_name='Forma de pago'
    )
    observacion = models.TextField(blank=True, verbose_name='Observación')

    class Meta:
        verbose_name = 'Pago de Compra'
        verbose_name_plural = 'Pagos de Compras'
        ordering = ['-fecha', '-id']
        # access_pagocompra_module: acceso al listado del módulo (historial
        # de pagos y compras pendientes de pago), separado de view_pagocompra
        # (botón "Ver"/PDF de un pago puntual) — mismo patrón que billing.Invoice.Meta.
        permissions = [('access_pagocompra_module', 'Acceso al módulo de pagos a proveedores')]

    def __str__(self):
        return f'Pago #{self.id} - Compra #{self.compra_id} - ${self.valor}'

    def clean(self):
        if self.valor is not None and self.valor <= 0:
            raise ValidationError({'valor': 'El valor del pago debe ser mayor a 0.'})

    def save(self, *args, **kwargs):
        with transaction.atomic():
            compra = Purchase.objects.select_for_update().get(pk=self.compra_id)
            # anterior = lo que este mismo pago ya había descontado del saldo
            # (0 si es un pago nuevo); delta = cuánto hay que descontar ahora.
            anterior = Decimal('0')
            if self.pk:
                anterior = PagoCompra.objects.get(pk=self.pk).valor
            delta = self.valor - anterior

            if delta > compra.saldo:
                raise ValidationError({'valor': 'El pago no puede ser mayor al saldo pendiente de la compra.'})

            super().save(*args, **kwargs)

            compra.saldo -= delta
            compra.estado = Purchase.PAGADA if compra.saldo <= 0 else Purchase.PENDIENTE
            compra.save(update_fields=['saldo', 'estado'])

    def delete(self, *args, **kwargs):
        with transaction.atomic():
            compra = Purchase.objects.select_for_update().get(pk=self.compra_id)
            if compra.estado == Purchase.PAGADA:
                raise ValidationError('No se puede eliminar un pago de una compra ya cancelada.')

            super().delete(*args, **kwargs)

            compra.saldo += self.valor
            compra.estado = Purchase.PENDIENTE
            compra.save(update_fields=['saldo', 'estado'])
