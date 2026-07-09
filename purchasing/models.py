from django.db import models
from decimal import Decimal
# purchasing reutiliza modelos de billing en vez de duplicarlos: una compra
# le compra Product a un Supplier, ambos ya definidos en billing/models.py.
# Así, cuando se registra una compra, se puede actualizar directamente el
# stock/last_cost del Product real (ver purchasing/views.py -> purchase_create).
from billing.models import Supplier, Product

class Purchase(models.Model):
    """Cabecera de compra (una por cada factura de compra que llega de un proveedor)."""
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
    is_active = models.BooleanField(default=True)

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

    def __str__(self):
        try:
            return f'Purchase #{self.id} - {self.supplier}'
        except:
            return f'Purchase #{self.id}'


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

    def __str__(self):
        return f'{self.product.name} x {self.quantity}'

    def save(self, *args, **kwargs):
        self.subtotal = self.quantity * self.unit_cost
        super().save(*args, **kwargs)