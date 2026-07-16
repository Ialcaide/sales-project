from decimal import Decimal
from django.core.exceptions import ValidationError
from django.db import models, transaction
from billing.models import Invoice


class CobroFactura(models.Model):
    """
    Abono a una Invoice (Factura de venta) a crédito. Cada save()/delete()
    recalcula el saldo y estado de la factura asociada dentro de una
    transacción (con select_for_update para evitar que dos cobros
    concurrentes descuadren el saldo) — mismo patrón que
    pagos/models.py -> PagoCompra, pero del lado de cuentas por COBRAR.
    """
    # A diferencia de pagos.PagoCompra (proveedores), acá PAYPAL sí puede
    # corresponder a un pago real capturado por paypal_pagos/services.py
    # (el negocio SÍ recibe dinero de un cliente) — pero el campo también
    # se puede elegir a mano para un cobro registrado manualmente que de
    # hecho se pagó por PayPal fuera de este flujo.
    EFECTIVO = 'efectivo'
    PAYPAL = 'paypal'
    FORMA_PAGO_CHOICES = [
        (EFECTIVO, 'Efectivo'),
        (PAYPAL, 'PayPal'),
    ]

    factura = models.ForeignKey(
        Invoice, on_delete=models.PROTECT, related_name='cobros', verbose_name='Factura'
    )
    fecha = models.DateField(verbose_name='Fecha de cobro')
    valor = models.DecimalField(max_digits=10, decimal_places=2, verbose_name='Valor')
    forma_pago = models.CharField(
        max_length=15, choices=FORMA_PAGO_CHOICES, default=EFECTIVO, verbose_name='Forma de pago'
    )
    # Solo aplica cuando forma_pago == EFECTIVO: cuánto dinero entregó el
    # cliente físicamente (para calcular el cambio, ver la property abajo).
    monto_recibido = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True, verbose_name='Monto recibido en efectivo'
    )
    observacion = models.TextField(blank=True, verbose_name='Observación')

    class Meta:
        verbose_name = 'Cobro de Factura'
        verbose_name_plural = 'Cobros de Facturas'
        ordering = ['-fecha', '-id']
        # access_cobrofactura_module: acceso al listado del módulo (historial
        # de cobros y facturas pendientes de cobro), separado de
        # view_cobrofactura (botón "Ver"/PDF de un cobro puntual) — mismo
        # patrón que billing.Invoice.Meta.
        permissions = [('access_cobrofactura_module', 'Acceso al módulo de cobros a clientes')]

    def __str__(self):
        return f'Cobro #{self.id} - Factura #{self.factura_id} - ${self.valor}'

    @property
    def cambio(self):
        """Vuelto a devolver cuando el cobro es en efectivo. None si no aplica."""
        if self.forma_pago != self.EFECTIVO or self.monto_recibido is None:
            return None
        return (self.monto_recibido - self.valor).quantize(Decimal('0.01'))

    def clean(self):
        if self.valor is not None and self.valor <= 0:
            raise ValidationError({'valor': 'El valor del cobro debe ser mayor a 0.'})
        if self.factura_id and not self.factura.is_active:
            raise ValidationError('No se puede registrar un cobro sobre una factura anulada.')

    def save(self, *args, **kwargs):
        with transaction.atomic():
            factura = Invoice.objects.select_for_update().get(pk=self.factura_id)
            if not factura.is_active:
                raise ValidationError('No se puede registrar un cobro sobre una factura anulada.')

            # anterior = lo que este mismo cobro ya había descontado del saldo
            # (0 si es un cobro nuevo); delta = cuánto hay que descontar ahora.
            anterior = Decimal('0')
            if self.pk:
                anterior = CobroFactura.objects.get(pk=self.pk).valor
            delta = self.valor - anterior

            if delta > factura.saldo:
                raise ValidationError({'valor': 'El cobro no puede ser mayor al saldo pendiente de la factura.'})

            super().save(*args, **kwargs)

            factura.saldo -= delta
            factura.estado = Invoice.PAGADA if factura.saldo <= 0 else Invoice.PENDIENTE
            factura.save(update_fields=['saldo', 'estado'])

    def delete(self, *args, **kwargs):
        with transaction.atomic():
            factura = Invoice.objects.select_for_update().get(pk=self.factura_id)
            if factura.estado == Invoice.PAGADA:
                # Eliminar este cobro dejaría el saldo inconsistente: la
                # factura ya se dio por cancelada con este cobro incluido.
                raise ValidationError('No se puede eliminar un cobro de una factura ya cancelada.')

            super().delete(*args, **kwargs)

            factura.saldo += self.valor
            factura.estado = Invoice.PENDIENTE
            factura.save(update_fields=['saldo', 'estado'])
