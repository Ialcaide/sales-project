from django.db import models
from shared.validators import validate_cedula_ec

# Cada clase de este archivo = una tabla en la base de datos (Django genera
# el SQL solo). Al agregar o cambiar un modelo, SIEMPRE hay que correr:
#   python manage.py makemigrations billing
#   python manage.py migrate
# para que el cambio se refleje en dbventas.sqlite3.
#
# on_delete=PROTECT (lo vas a ver en varias FK de este archivo) significa:
# "no dejes borrar este registro si todavía hay otro que depende de él" —
# ej. no se puede borrar una Marca si tiene Productos asociados.


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
    
    def clean(self):
        from django.core.exceptions import ValidationError
        if not self.name or not self.name.strip():
            raise ValidationError({'name': 'El nombre de la marca es obligatorio.'})

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
    # ManyToManyField (más abajo, 'suppliers') es distinto de ForeignKey:
    # un producto puede tener VARIOS proveedores, y un proveedor puede
    # vender VARIOS productos. Django crea una tabla intermedia solo para
    # guardar esa relación (no hace falta modelarla a mano).
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

    # @property convierte un método en algo que se lee como si fuera un
    # campo más: product.inventory_value, SIN paréntesis. Estos valores NO
    # se guardan en la base de datos, se calculan al vuelo cada vez que se
    # piden (por eso no aparecen en las migraciones).
    @property
    def inventory_value(self):
        return self.stock * self.unit_price

    @property
    def placeholder_image(self):
        """
        Genera una imagen SVG "al vuelo" (sin guardar ningún archivo en disco)
        para productos que no tienen foto subida: un cuadrado de color con la
        inicial del nombre. El color sale de un hash del nombre, así el MISMO
        producto siempre recibe el MISMO color (no cambia en cada visita).
        Se devuelve como "data URI" (data:image/svg+xml;...) — un <img src="...">
        puede usar esto directamente, como si fuera la URL de un archivo real.
        """
        import hashlib
        from urllib.parse import quote
        palette = ['#4f46e5', '#0891b2', '#059669', '#d97706', '#dc2626', '#7c3aed', '#db2777']
        seed = int(hashlib.md5(self.name.encode('utf-8')).hexdigest(), 16)
        color = palette[seed % len(palette)]
        initial = (self.name[:1] or '?').upper()
        svg = (
            '<svg xmlns="http://www.w3.org/2000/svg" width="200" height="200">'
            f'<rect width="100%" height="100%" fill="{color}"/>'
            '<text x="50%" y="50%" font-family="sans-serif" font-size="90" fill="#ffffff" '
            f'text-anchor="middle" dominant-baseline="central">{initial}</text>'
            '</svg>'
        )
        return f'data:image/svg+xml;utf8,{quote(svg)}'

    def __str__(self): return f'{self.name} ({self.brand.name})'

    # clean() es la validación a nivel de MODELO (corre siempre que se llama
    # full_clean(), y Django la llama automáticamente al validar un ModelForm).
    # Es la última línea de defensa: aunque alguien intente crear un Product
    # sin pasar por el formulario (ej. desde el shell o un script), estas
    # reglas se siguen aplicando.
    def clean(self):
        from django.core.exceptions import ValidationError
        if self.unit_price is not None and self.unit_price <= 0:
            raise ValidationError({'unit_price': 'El precio debe ser mayor a 0.'})
        if self.stock is not None and self.stock < 0:
            raise ValidationError({'stock': 'El stock no puede ser negativo.'})


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
    
    def clean(self):
        from django.core.exceptions import ValidationError
        if not self.first_name or not self.first_name.strip():
            raise ValidationError({'first_name': 'El nombre es obligatorio.'})
        if not self.last_name or not self.last_name.strip():
            raise ValidationError({'last_name': 'El apellido es obligatorio.'})

class CustomerProfile(models.Model):
    """
    Perfil extendido. OneToOne con Customer: en vez de agregar estos campos
    directamente a Customer, se separan en una tabla aparte porque son datos
    "opcionales/avanzados" (facturación) que no todos los clientes necesitan
    llenar de una — mismo patrón que UserProfile en security/models.py.
    """
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
    """
    Líneas de factura (una por cada producto vendido en esa factura).
    related_name='details' es lo que permite escribir invoice.details.all()
    desde una Invoice para obtener todas sus líneas (se usa mucho en
    billing/views.py e billing/templates/billing/invoice_detail.html).
    on_delete=CASCADE en 'invoice' (a diferencia de PROTECT en 'product'):
    si se borra la factura, sus líneas se borran con ella; pero no se puede
    borrar un producto que ya fue facturado alguna vez.
    """
    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name='details', verbose_name='Factura')
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name='invoice_details', verbose_name='Producto')
    quantity = models.IntegerField(default=1, verbose_name='Cantidad')
    unit_price = models.DecimalField(max_digits=12, decimal_places=2, verbose_name='Precio unitario')
    subtotal = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name='Subtotal')
    def __str__(self): return f'{self.product.name} x {self.quantity}'

    # save() sobreescrito: cada vez que se guarda una línea, se recalcula el
    # subtotal automáticamente ANTES de escribir en la base de datos — así
    # nunca puede quedar desincronizado con quantity/unit_price.
    def save(self, *args, **kwargs):
        self.subtotal = self.quantity * self.unit_price
        super().save(*args, **kwargs)