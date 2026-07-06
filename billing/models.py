from django.db import models
from shared.validators import validate_cedula_ec

class Brand(models.Model):
    """Marcas de productos."""
    name = models.CharField(max_length=100, unique=True, verbose_name='Nombre')
    description = models.TextField(blank=True, null=True, verbose_name='Descripción')
    is_active = models.BooleanField(default=True, verbose_name='Activo')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    class Meta:
        verbose_name = 'Marca'
        verbose_name_plural = 'Marcas'
        ordering = ['name']
    def __str__(self): return self.name

class ProductGroup(models.Model):
    """Grupos/categorías de productos."""
    name = models.CharField(max_length=100, unique=True, verbose_name='Nombre')
    is_active = models.BooleanField(default=True, verbose_name='Activo')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    class Meta:
        verbose_name = 'Grupo de Producto'
        verbose_name_plural = 'Grupos de Productos'
        ordering = ['name']
    def __str__(self): return self.name

class Supplier(models.Model):
    """Proveedores. M2M con Product."""
    name = models.CharField(max_length=200, verbose_name='Nombre de la empresa')
    contact_name = models.CharField(max_length=200, blank=True, null=True, verbose_name='Persona de contacto')
    email = models.EmailField(blank=True, null=True, verbose_name='Correo electrónico')
    phone = models.CharField(max_length=20, blank=True, null=True, verbose_name='Teléfono')
    address = models.TextField(blank=True, null=True, verbose_name='Dirección')
    is_active = models.BooleanField(default=True, verbose_name='Activo')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    class Meta:
        verbose_name = 'Proveedor'
        verbose_name_plural = 'Proveedores'
        ordering = ['name']
    def __str__(self): return self.name

class Product(models.Model):
    """Productos. FK a Brand/Group, M2M a Supplier."""
    name = models.CharField(max_length=200, verbose_name='Nombre')
    description = models.TextField(blank=True, null=True, verbose_name='Descripción')
    brand = models.ForeignKey(Brand, on_delete=models.PROTECT, related_name='products', verbose_name='Marca')
    group = models.ForeignKey(ProductGroup, on_delete=models.PROTECT, related_name='products', verbose_name='Grupo')
    suppliers = models.ManyToManyField(Supplier, related_name='products', blank=True, verbose_name='Proveedores')
    unit_price = models.DecimalField(max_digits=12, decimal_places=2, verbose_name='Precio unitario')
    last_cost = models.DecimalField(max_digits=12, decimal_places=2, default=0, null=True, blank=True, verbose_name='Último costo de compra')
    stock = models.IntegerField(default=0, verbose_name='Stock')
    is_active = models.BooleanField(default=True, verbose_name='Activo')
    image = models.ImageField(upload_to='products/', blank=True, null=True, verbose_name='Imagen')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Producto'
        verbose_name_plural = 'Productos'
        ordering = ['name']

    @property
    def inventory_value(self):
        return self.stock * self.unit_price

    @property
    def margin(self):
        if self.last_cost and self.last_cost > 0:
            return round((self.unit_price - self.last_cost) / self.last_cost * 100, 2)
        return None

    def __str__(self): return f'{self.name} ({self.brand.name})'


class Customer(models.Model):
    """Clientes. OneToOne con CustomerProfile."""
    dni = models.CharField(max_length=13, unique=True, verbose_name='Cédula / RUC', validators=[validate_cedula_ec])
    first_name = models.CharField(max_length=100, verbose_name='Nombres')
    last_name = models.CharField(max_length=100, verbose_name='Apellidos')
    email = models.EmailField(blank=True, null=True, verbose_name='Correo electrónico')
    phone = models.CharField(max_length=20, blank=True, null=True, verbose_name='Teléfono')
    address = models.TextField(blank=True, null=True, verbose_name='Dirección')
    is_active = models.BooleanField(default=True, verbose_name='Activo')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    class Meta:
        verbose_name = 'Cliente'
        verbose_name_plural = 'Clientes'
        ordering = ['last_name', 'first_name']
    def __str__(self): return f'{self.last_name}, {self.first_name}'
    @property
    def full_name(self): return f'{self.first_name} {self.last_name}'

class CustomerProfile(models.Model):
    """Perfil extendido. OneToOne con Customer."""
    TAXPAYER = [('final', 'Consumidor Final'), ('ruc', 'RUC'), ('rise', 'RISE')]
    PAYMENT = [('cash', 'Contado'), ('credit_15', '15 días'), ('credit_30', '30 días'), ('credit_60', '60 días')]
    customer = models.OneToOneField(Customer, on_delete=models.CASCADE, related_name='profile', verbose_name='Cliente')
    taxpayer_type = models.CharField(max_length=10, choices=TAXPAYER, default='final', verbose_name='Tipo de contribuyente')
    payment_terms = models.CharField(max_length=15, choices=PAYMENT, default='cash', verbose_name='Términos de pago')
    credit_limit = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name='Límite de crédito')
    notes = models.TextField(blank=True, null=True, verbose_name='Notas')
    class Meta:
        verbose_name = 'Perfil de Cliente'
        verbose_name_plural = 'Perfiles de Clientes'
    def __str__(self): return f'Perfil: {self.customer}'

class Invoice(models.Model):
    """Cabecera de factura."""
    customer = models.ForeignKey(Customer, on_delete=models.PROTECT, related_name='invoices', verbose_name='Cliente')
    invoice_date = models.DateTimeField(auto_now_add=True, verbose_name='Fecha')
    subtotal = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name='Subtotal')
    tax = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name='IVA')
    total = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name='Total')
    is_active = models.BooleanField(default=True, verbose_name='Activo')
    class Meta:
        verbose_name = 'Factura'
        verbose_name_plural = 'Facturas'
        ordering = ['-invoice_date']
    def __str__(self): return f'Factura #{self.id} - {self.customer}'

class InvoiceDetail(models.Model):
    """Líneas de factura."""
    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name='details', verbose_name='Factura')
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name='invoice_details', verbose_name='Producto')
    quantity = models.IntegerField(default=1, verbose_name='Cantidad')
    unit_price = models.DecimalField(max_digits=12, decimal_places=2, verbose_name='Precio unitario')
    subtotal = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name='Subtotal')
    def __str__(self): return f'{self.product.name} x {self.quantity}'
    def save(self, *args, **kwargs):
        self.subtotal = self.quantity * self.unit_price
        super().save(*args, **kwargs)