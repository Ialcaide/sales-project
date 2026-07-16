from django.db import models
from datetime import timedelta
from decimal import Decimal
# purchasing reutiliza modelos de billing en vez de duplicarlos: una compra
# le compra Product a un Supplier, ambos ya definidos en billing/models.py.
# Así, cuando se registra una compra, se puede actualizar directamente el
# stock/last_cost del Product real (ver purchasing/views.py -> purchase_create).
from billing.models import Supplier, Product


class Bodega(models.Model):
    """Catálogo simple de bodegas/almacenes. Es solo un dato informativo en
    la compra (a cuál entró la mercadería) — el stock de Product sigue
    siendo un único número global, no se reparte por bodega."""

    nombre = models.CharField(max_length=100, unique=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name = 'Bodega'
        verbose_name_plural = 'Bodegas'
        ordering = ['nombre']

    def __str__(self):
        return self.nombre


class Purchase(models.Model):
    """Cabecera de compra (una por cada factura de compra que llega de un proveedor)."""

    # Compras al CONTADO quedan PAGADA de una (saldo 0); compras a CREDITO
    # nacen PENDIENTE con saldo = total, y el módulo 'pagos' las va abonando
    # hasta dejarlas en 0 (ver pagos/models.py -> PagoCompra.save()).
    CONTADO = 'contado'
    CREDITO = 'credito'
    TIPO_PAGO_CHOICES = [
        (CONTADO, 'Contado'),
        (CREDITO, 'Crédito'),
    ]

    PENDIENTE = 'pendiente'
    PAGADA = 'pagada'
    ESTADO_CHOICES = [
        (PENDIENTE, 'Pendiente'),
        (PAGADA, 'Pagada'),
    ]

    # `fase` es el flujo operativo de la compra (recepción de mercadería),
    # totalmente separado de `estado` (arriba, que es solo estado de PAGO,
    # manejado por pagos.PagoCompra.save()) — no confundir ni mezclar ambos.
    # La barra de progreso en la UI muestra "Pagada" como un 4to paso leyendo
    # `estado`, sin que exista un valor "pagada" acá.
    BORRADOR = 'borrador'
    CONFIRMADA = 'confirmada'
    RECIBIDA = 'recibida'
    FASE_CHOICES = [
        (BORRADOR, 'Borrador'),
        (CONFIRMADA, 'Confirmada'),
        (RECIBIDA, 'Recibida'),
    ]

    supplier = models.ForeignKey(
        Supplier, on_delete=models.PROTECT, related_name='purchases'
    )
    document_number = models.CharField(
        max_length=20, verbose_name='Supplier Invoice No.'
    )
    purchase_date = models.DateTimeField(auto_now_add=True)
    subtotal = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    tax = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    tipo_pago = models.CharField(
        max_length=10, choices=TIPO_PAGO_CHOICES, default=CONTADO,
        verbose_name='Tipo de pago'
    )
    saldo = models.DecimalField(
        max_digits=12, decimal_places=2, default=0, verbose_name='Saldo pendiente'
    )
    estado = models.CharField(
        max_length=10, choices=ESTADO_CHOICES, default=PAGADA, verbose_name='Estado'
    )
    # Solo aplica a compras a CREDITO (a cuántos meses se difiere la deuda
    # con el proveedor); en CONTADO queda en None. Validado en clean() de
    # abajo, que corre automáticamente en cada form.is_valid() (ModelForm
    # llama full_clean() del instance antes de guardar).
    meses_credito = models.PositiveSmallIntegerField(
        null=True, blank=True, verbose_name='Meses para diferir'
    )
    # Recargo financiero por diferir el pago (0 en CONTADO). Se calcula solo,
    # ver aplicar_financiamiento() más abajo — a más meses, más interés.
    interes = models.DecimalField(
        max_digits=12, decimal_places=2, default=0, verbose_name='Interés'
    )
    is_active = models.BooleanField(default=True)

    fase = models.CharField(
        max_length=10, choices=FASE_CHOICES, default=BORRADOR, verbose_name='Fase'
    )
    bodega = models.ForeignKey(
        'Bodega', on_delete=models.PROTECT, related_name='purchases',
        null=True, blank=True, verbose_name='Bodega de destino'
    )
    factura_adjunta = models.FileField(
        upload_to='purchases/facturas/', null=True, blank=True,
        verbose_name='Factura del proveedor (PDF/XML/imagen)'
    )
    retencion_porcentaje = models.DecimalField(
        max_digits=5, decimal_places=2, default=0, blank=True, verbose_name='Retención (%)'
    )
    retencion_valor = models.DecimalField(
        max_digits=12, decimal_places=2, default=0, verbose_name='Retención (valor)'
    )

    MESES_CREDITO_MAX = 36

    # A más meses de plazo, mayor la tasa de interés total sobre el valor de
    # la compra (financiamiento más largo = más riesgo/costo para la empresa).
    # Cada tupla es (meses_hasta, tasa): la primera cuyo límite alcance o
    # supere meses_credito es la que aplica.
    INTERES_TIERS = [
        (3, Decimal('0.05')),
        (6, Decimal('0.10')),
        (12, Decimal('0.15')),
        (24, Decimal('0.20')),
        (36, Decimal('0.25')),
    ]

    class Meta:
        verbose_name = 'Purchase'
        verbose_name_plural = 'Purchases'
        ordering = ['-purchase_date']
        # No se puede registrar dos veces la MISMA factura del MISMO
        # proveedor (evita cargar el mismo documento de compra por error).
        # Sí se permite repetir el document_number entre proveedores distintos.
        constraints = [
        models.UniqueConstraint(
            fields=['supplier', 'document_number'],
            name='unique_purchase_per_supplier'
        )
    ]
        # access_purchase_module: acceso al listado/reporte del módulo,
        # separado de view_purchase (botón "Ver" de una compra puntual) —
        # mismo patrón que billing.Invoice.Meta.
        permissions = [
            ('access_purchase_module', 'Acceso al módulo de compras'),
            ('export_pdf_purchase', 'Puede exportar compras a PDF'),
            ('export_excel_purchase', 'Puede exportar compras a Excel'),
        ]

    def __str__(self):
        try:
            return f'Purchase #{self.id} - {self.supplier}'
        except:
            return f'Purchase #{self.id}'

    def clean(self):
        from django.core.exceptions import ValidationError
        if self.tipo_pago == self.CREDITO:
            if not self.meses_credito or self.meses_credito < 1:
                raise ValidationError({
                    'meses_credito': 'Indica a cuántos meses se difiere una compra a crédito (mínimo 1).'
                })
            if self.meses_credito > self.MESES_CREDITO_MAX:
                raise ValidationError({
                    'meses_credito': f'El plazo máximo permitido es de {self.MESES_CREDITO_MAX} meses.'
                })
        elif self.meses_credito:
            raise ValidationError({
                'meses_credito': 'Una compra al contado no puede tener meses de crédito.'
            })

    @classmethod
    def tasa_interes(cls, meses):
        """Tasa total (no mensual) que corresponde a un plazo de `meses`."""
        for limite, tasa in cls.INTERES_TIERS:
            if meses <= limite:
                return tasa
        return cls.INTERES_TIERS[-1][1]

    def aplicar_financiamiento(self):
        """
        Calcula interés/saldo/estado a partir de tipo_pago, meses_credito y
        total (deben estar ya definidos). Se llama explícitamente desde
        purchase_create — no desde save() — porque el total de la compra
        recién se conoce después de guardar el formset de líneas.
        """
        if self.tipo_pago == self.CREDITO:
            self.interes = (self.total * self.tasa_interes(self.meses_credito)).quantize(Decimal('0.01'))
            self.saldo = self.total + self.interes
            self.estado = self.PENDIENTE if self.saldo > 0 else self.PAGADA
        else:
            self.interes = Decimal('0')
            self.saldo = Decimal('0')
            self.estado = self.PAGADA

    @property
    def total_a_pagar(self):
        """Total + interés: lo que realmente hay que cancelarle al proveedor."""
        return self.total + self.interes

    @property
    def fecha_entrega_estimada(self):
        """
        Estimación automática de entrega: 24 horas desde que se registró la
        compra. Antes era una fecha elegida a mano en el wizard; se volvió un
        cálculo automático (sin campo propio en la BD) para no pedirle al
        usuario un dato que en la práctica siempre era "mañana". None si la
        compra todavía no se guardó (purchase_date es auto_now_add).
        """
        if not self.purchase_date:
            return None
        return self.purchase_date + timedelta(hours=24)

    @property
    def cuota_minima(self):
        """
        Pago mínimo por abono para terminar de cancelar la compra dentro de
        los meses pactados (total_a_pagar / meses_credito). None si no aplica
        (compra al contado o sin meses definidos).
        """
        if self.tipo_pago != self.CREDITO or not self.meses_credito:
            return None
        return (self.total_a_pagar / self.meses_credito).quantize(Decimal('0.01'))

    @property
    def fecha_limite_pago(self):
        """
        Última fecha en la que se puede registrar un pago (fecha de la compra
        + meses_credito). None si no es a crédito. Suma de meses hecha a mano
        (sin dateutil) para no agregar una dependencia nueva solo por esto.
        """
        if self.tipo_pago != self.CREDITO or not self.meses_credito:
            return None
        import calendar
        fecha = self.purchase_date.date()
        mes_total = fecha.month - 1 + self.meses_credito
        anio = fecha.year + mes_total // 12
        mes = mes_total % 12 + 1
        dia = min(fecha.day, calendar.monthrange(anio, mes)[1])
        return fecha.replace(year=anio, month=mes, day=dia)

    @property
    def monto_neto_a_pagar(self):
        """total_a_pagar menos la retención — puramente informativo, no
        toca saldo/estado ni la integración con pagos.PagoCompra."""
        return self.total_a_pagar - self.retencion_valor


class PurchaseDetail(models.Model):
    """
    Líneas de compra (un producto comprado, con su cantidad y costo).
    Se llama 'unit_cost' (no 'unit_price' como en InvoiceDetail) porque acá
    representa lo que la empresa PAGA al proveedor, no lo que le cobra al
    cliente — son conceptos distintos aunque la estructura sea idéntica.
    """
    purchase = models.ForeignKey(
        Purchase, on_delete=models.CASCADE, related_name='details'
    )
    product = models.ForeignKey(
        Product, on_delete=models.PROTECT, related_name='purchase_details'
    )
    quantity = models.PositiveIntegerField(default=1)
    unit_cost = models.DecimalField(max_digits=12, decimal_places=2)
    subtotal = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    descuento_porcentaje = models.DecimalField(
        max_digits=5, decimal_places=2, default=0, verbose_name='Descuento (%)'
    )

    def __str__(self):
        return f'{self.product.name} x {self.quantity}'

    def save(self, *args, **kwargs):
        # Decimal('100'), no 100 (int): con default=0 el campo puede llegar
        # como int puro antes del primer full_clean() — 0 / 100 en Python
        # hace división float (0.0), y Decimal * float truena con TypeError.
        # Dividir por un Decimal fuerza que todo el cálculo quede en Decimal.
        self.subtotal = (
            self.quantity * self.unit_cost * (1 - self.descuento_porcentaje / Decimal('100'))
        ).quantize(Decimal('0.01'))
        super().save(*args, **kwargs)