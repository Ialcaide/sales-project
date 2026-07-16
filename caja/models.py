from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


class SesionCaja(models.Model):
    """
    Una jornada de caja de UN usuario: desde que abre (con un monto inicial
    en efectivo) hasta que cierra (contando físicamente lo que hay y
    comparándolo contra lo que el sistema esperaba encontrar).
    """
    ABIERTA = 'abierta'
    CERRADA = 'cerrada'
    ESTADO_CHOICES = [
        (ABIERTA, 'Abierta'),
        (CERRADA, 'Cerrada'),
    ]

    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='sesiones_caja',
        verbose_name='Usuario',
    )
    fecha_apertura = models.DateTimeField(auto_now_add=True, verbose_name='Fecha de apertura')
    monto_inicial = models.DecimalField(max_digits=12, decimal_places=2, verbose_name='Monto inicial')
    fecha_cierre = models.DateTimeField(null=True, blank=True, verbose_name='Fecha de cierre')
    # Lo que el cajero cuenta físicamente al cerrar (el arqueo). None
    # mientras la sesión sigue abierta.
    monto_contado_cierre = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True, verbose_name='Monto contado al cierre'
    )
    estado = models.CharField(max_length=10, choices=ESTADO_CHOICES, default=ABIERTA, verbose_name='Estado')

    class Meta:
        verbose_name = 'Sesión de Caja'
        verbose_name_plural = 'Sesiones de Caja'
        ordering = ['-fecha_apertura']
        # access_sesioncaja_module: acceso al historial/listado del módulo,
        # separado de view_sesioncaja (botón "Ver" de una sesión puntual) —
        # mismo patrón que billing.Invoice.Meta.
        permissions = [('access_sesioncaja_module', 'Acceso al módulo de caja')]

    def __str__(self):
        return f'Caja #{self.id} - {self.usuario} ({self.get_estado_display()})'

    def total_por_tipo(self, tipo):
        total = self.movimientos.filter(tipo=tipo).aggregate(total=models.Sum('monto'))['total']
        # Sum() sobre SQLite puede devolver ruido de punto flotante en
        # DecimalField (ver billing/models.py -> deuda_actual_credito para
        # el mismo problema ya documentado) — se redondea a 2 decimales.
        return total.quantize(Decimal('0.01')) if total is not None else Decimal('0.00')

    @property
    def total_ingresos(self):
        return self.total_por_tipo(MovimientoCaja.INGRESO)

    @property
    def total_egresos(self):
        return self.total_por_tipo(MovimientoCaja.EGRESO)

    @property
    def monto_esperado_cierre(self):
        """Lo que el sistema espera encontrar en caja: inicial + ingresos - egresos."""
        return self.monto_inicial + self.total_ingresos - self.total_egresos

    @property
    def diferencia(self):
        """monto_contado_cierre - monto_esperado_cierre. None si sigue abierta (aún no hay arqueo)."""
        if self.monto_contado_cierre is None:
            return None
        return self.monto_contado_cierre - self.monto_esperado_cierre


class MovimientoCaja(models.Model):
    """Un ingreso o egreso de efectivo dentro de una SesionCaja (ventas en
    efectivo, retiros, pagos de gastos menores, etc.)."""
    INGRESO = 'ingreso'
    EGRESO = 'egreso'
    TIPO_CHOICES = [
        (INGRESO, 'Ingreso'),
        (EGRESO, 'Egreso'),
    ]

    sesion = models.ForeignKey(SesionCaja, on_delete=models.PROTECT, related_name='movimientos', verbose_name='Sesión')
    tipo = models.CharField(max_length=10, choices=TIPO_CHOICES, verbose_name='Tipo')
    monto = models.DecimalField(max_digits=12, decimal_places=2, verbose_name='Monto')
    concepto = models.CharField(max_length=200, verbose_name='Concepto')
    fecha = models.DateTimeField(auto_now_add=True, verbose_name='Fecha')
    # Liga el movimiento a la venta que lo generó (ventas en efectivo desde
    # billing/views.py -> invoice_create); null para movimientos manuales
    # (retiros, pagos de gastos menores, etc.).
    invoice = models.ForeignKey(
        'billing.Invoice', null=True, blank=True, on_delete=models.SET_NULL,
        related_name='movimientos_caja', verbose_name='Factura relacionada',
    )
    # Espejo de 'invoice' pero para el otro lado: liga el movimiento al pago
    # a un proveedor que lo generó (pagos en efectivo desde
    # pagos/views.py -> pago_create); null para movimientos manuales.
    pago_compra = models.ForeignKey(
        'pagos.PagoCompra', null=True, blank=True, on_delete=models.SET_NULL,
        related_name='movimientos_caja', verbose_name='Pago a proveedor relacionado',
    )
    # Liga el movimiento al cobro de una factura a crédito que lo generó
    # (cobros en efectivo desde cobros/views.py -> cobro_create); null para
    # movimientos manuales.
    cobro_factura = models.ForeignKey(
        'cobros.CobroFactura', null=True, blank=True, on_delete=models.SET_NULL,
        related_name='movimientos_caja', verbose_name='Cobro de factura relacionado',
    )

    class Meta:
        verbose_name = 'Movimiento de Caja'
        verbose_name_plural = 'Movimientos de Caja'
        ordering = ['-fecha']

    def __str__(self):
        return f'{self.get_tipo_display()} ${self.monto} - {self.concepto}'

    def clean(self):
        if self.monto is not None and self.monto <= 0:
            raise ValidationError({'monto': 'El monto debe ser mayor a 0.'})

    def save(self, *args, **kwargs):
        if self.sesion_id and self.sesion.estado == SesionCaja.CERRADA:
            raise ValidationError('No se pueden registrar movimientos en una caja ya cerrada.')
        super().save(*args, **kwargs)
