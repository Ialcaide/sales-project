from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models, transaction

from billing.models import Invoice, InvoiceDetail


class DevolucionVenta(models.Model):
    """Cabecera de una devolución (una o varias líneas) sobre una factura ya emitida."""
    factura = models.ForeignKey(Invoice, on_delete=models.PROTECT, related_name='devoluciones', verbose_name='Factura')
    fecha = models.DateTimeField(auto_now_add=True, verbose_name='Fecha')
    motivo = models.TextField(verbose_name='Motivo')
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='devoluciones', verbose_name='Usuario',
    )

    class Meta:
        verbose_name = 'Devolución de Venta'
        verbose_name_plural = 'Devoluciones de Ventas'
        ordering = ['-fecha']
        # access_devolucionventa_module: acceso al listado del módulo,
        # separado de view_devolucionventa (botón "Ver" de una devolución
        # puntual) — mismo patrón que billing.Invoice.Meta.
        permissions = [('access_devolucionventa_module', 'Acceso al módulo de devoluciones')]

    def __str__(self):
        return f'Devolución #{self.id} - Factura #{self.factura_id}'

    @property
    def subtotal(self):
        return sum((d.subtotal for d in self.detalles.all()), Decimal('0.00'))

    @property
    def total(self):
        """Subtotal devuelto + su IVA — lo mismo que se le resta a la factura.
        Usa la tasa de IVA REAL de la factura (factura.tax / factura.subtotal),
        no la configurada hoy — mismo criterio que registrar_devolucion()."""
        if self.factura.subtotal:
            tasa_iva = self.factura.tax / self.factura.subtotal
        else:
            from configuracion.models import ConfiguracionSistema
            tasa_iva = ConfiguracionSistema.get_solo().iva_fraccion
        return (self.subtotal * (1 + tasa_iva)).quantize(Decimal('0.01'))


class DevolucionDetalle(models.Model):
    """Una línea devuelta: qué producto (vía su InvoiceDetail original) y cuánta cantidad."""
    devolucion = models.ForeignKey(DevolucionVenta, on_delete=models.CASCADE, related_name='detalles', verbose_name='Devolución')
    invoice_detail = models.ForeignKey(InvoiceDetail, on_delete=models.PROTECT, related_name='devoluciones', verbose_name='Línea de factura')
    quantity = models.PositiveIntegerField(verbose_name='Cantidad devuelta')
    subtotal = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name='Subtotal')

    class Meta:
        verbose_name = 'Detalle de Devolución'
        verbose_name_plural = 'Detalles de Devolución'

    def __str__(self):
        return f'{self.invoice_detail.product.name} x {self.quantity}'

    def cantidad_ya_devuelta(self):
        """Cuánto de esta MISMA línea de factura ya se había devuelto antes (excluyéndose a sí mismo)."""
        qs = DevolucionDetalle.objects.filter(invoice_detail=self.invoice_detail).exclude(pk=self.pk)
        return qs.aggregate(total=models.Sum('quantity'))['total'] or 0

    def clean(self):
        if self.quantity is not None and self.quantity <= 0:
            raise ValidationError({'quantity': 'La cantidad devuelta debe ser mayor a 0.'})
        if self.invoice_detail_id and self.quantity:
            disponible = self.invoice_detail.quantity - self.cantidad_ya_devuelta()
            if self.quantity > disponible:
                raise ValidationError({
                    'quantity': f'Solo puedes devolver hasta {disponible} unidad(es) de "{self.invoice_detail.product.name}".'
                })

    def save(self, *args, **kwargs):
        self.subtotal = self.quantity * self.invoice_detail.unit_price
        super().save(*args, **kwargs)


def registrar_devolucion(factura, motivo, usuario, lineas, sesion_caja=None):
    """
    Crea la DevolucionVenta + sus DevolucionDetalle dentro de una transacción,
    y aplica sus efectos: aumenta stock, reduce el total/saldo de la
    factura, y si corresponde, registra un egreso en la caja abierta.
    `lineas` es una lista de tuplas (invoice_detail, quantity).
    """
    from caja.models import MovimientoCaja

    if not factura.is_active:
        raise ValidationError('No se puede registrar una devolución sobre una factura anulada.')
    if not lineas:
        raise ValidationError('Selecciona al menos un producto a devolver.')

    with transaction.atomic():
        devolucion = DevolucionVenta.objects.create(factura=factura, motivo=motivo, usuario=usuario)
        subtotal_devuelto = Decimal('0.00')

        for invoice_detail, quantity in lineas:
            detalle = DevolucionDetalle(devolucion=devolucion, invoice_detail=invoice_detail, quantity=quantity)
            detalle.full_clean()
            detalle.save()
            subtotal_devuelto += detalle.subtotal  # quantity * unit_price, SIN IVA

            product = invoice_detail.product
            product.stock += quantity
            product.save(update_fields=['stock'])

        # DevolucionDetalle.subtotal es sin IVA (igual que InvoiceDetail.subtotal);
        # hay que reducir subtotal/tax/total de la factura en la misma
        # proporción para que sigan siendo consistentes entre sí. Se usa la
        # tasa de IVA REAL con la que se facturó (factura.tax / factura.subtotal),
        # no la tasa configurada HOY — si el administrador cambió el % de IVA
        # entre la venta y la devolución, esta factura sigue teniendo el
        # subtotal/tax con los que se emitió originalmente.
        if factura.subtotal:
            tasa_iva = factura.tax / factura.subtotal
        else:
            from configuracion.models import ConfiguracionSistema
            tasa_iva = ConfiguracionSistema.get_solo().iva_fraccion
        tax_devuelto = (subtotal_devuelto * tasa_iva).quantize(Decimal('0.01'))
        total_devuelto = subtotal_devuelto + tax_devuelto

        factura.subtotal = max(factura.subtotal - subtotal_devuelto, Decimal('0.00'))
        factura.tax = max(factura.tax - tax_devuelto, Decimal('0.00'))
        factura.total = max(factura.total - total_devuelto, Decimal('0.00'))
        if factura.tipo_pago == Invoice.CREDITO:
            factura.saldo = max(factura.saldo - total_devuelto, Decimal('0.00'))
            factura.estado = Invoice.PAGADA if factura.saldo <= 0 else Invoice.PENDIENTE
        factura.save(update_fields=['subtotal', 'tax', 'total', 'saldo', 'estado'])

        if factura.forma_pago == Invoice.EFECTIVO and sesion_caja and sesion_caja.estado == sesion_caja.ABIERTA:
            MovimientoCaja.objects.create(
                sesion=sesion_caja, tipo=MovimientoCaja.EGRESO, monto=total_devuelto,
                concepto=f'Devolución #{devolucion.id:04d} - Factura #{factura.id:04d}',
                invoice=factura,
            )

    return devolucion
