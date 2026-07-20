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
    # PayPal acá SÍ es real: paga de verdad al proveedor vía la API de
    # Payouts de PayPal (dinero SALIENDO del negocio) — distinta de la API
    # de Checkout/Orders que usan billing/cobros para RECIBIR pagos (ver
    # paypal_pagos/client.py -> crear_payout(), paypal_pagos/services.py ->
    # crear_pago_proveedor()). A diferencia de esas, Payouts no tiene un
    # paso de aprobación del receptor: se resuelve en la misma llamada, sin
    # redirect ni caja abierta. TARJETA sigue siendo la misma captura
    # informativa que billing.Invoice (ver tarjeta_titular/cvv/expiracion
    # más abajo) — no hay ninguna pasarela real integrada para tarjeta.
    EFECTIVO = 'efectivo'
    TARJETA = 'tarjeta'
    PAYPAL = 'paypal'
    FORMA_PAGO_CHOICES = [
        (EFECTIVO, 'Efectivo'),
        (TARJETA, 'Tarjeta'),
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
    # Solo aplican a TARJETA — informativos, nunca se guarda el número
    # completo de la tarjeta (mismo criterio que billing.Invoice). Guardar
    # el CVV/CVC es una decisión consciente pese a ir contra PCI-DSS,
    # documentada igual que en billing/models.py — no es un descuido.
    tarjeta_titular = models.CharField(
        max_length=150, null=True, blank=True, verbose_name='Titular de la tarjeta'
    )
    tarjeta_cvv = models.CharField(
        max_length=4, null=True, blank=True, verbose_name='CVV/CVC'
    )
    tarjeta_expiracion = models.DateField(
        null=True, blank=True, verbose_name='Fecha de expiración de la tarjeta'
    )
    # Solo aplica a PAYPAL — el ID del lote (payout_batch_id) que devuelve
    # la API de Payouts al enviar el pago, para poder rastrearlo del lado
    # de PayPal si hiciera falta.
    paypal_payout_id = models.CharField(
        max_length=50, null=True, blank=True, verbose_name='ID de payout de PayPal'
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
