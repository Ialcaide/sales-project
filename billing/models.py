from decimal import Decimal
from django.db import models
from shared.validators import normalize_phone, validate_cedula_ec, validate_pasaporte, validate_phone

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
        # access_brand_module: permiso aparte de view_brand — view_brand
        # controla el botón/acceso "Ver" a UNA marca puntual; este otro
        # controla si el listado completo del módulo carga. Ver la nota
        # general sobre este patrón en billing.Invoice.Meta más abajo.
        permissions = [
            ('access_brand_module', 'Acceso al módulo de marcas'),
            ('export_pdf_brand', 'Puede exportar marcas a PDF'),
            ('export_excel_brand', 'Puede exportar marcas a Excel'),
        ]
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
        permissions = [
            ('access_productgroup_module', 'Acceso al módulo de grupos de productos'),
            ('export_pdf_productgroup', 'Puede exportar grupos de productos a PDF'),
            ('export_excel_productgroup', 'Puede exportar grupos de productos a Excel'),
        ]
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
        permissions = [
            ('access_supplier_module', 'Acceso al módulo de proveedores'),
            ('export_pdf_supplier', 'Puede exportar proveedores a PDF'),
            ('export_excel_supplier', 'Puede exportar proveedores a Excel'),
        ]
    def __str__(self): return self.name

    def clean(self):
        from django.core.exceptions import ValidationError
        if self.phone:
            # normalize_phone antepone +593 si no trae código de país (ej.
            # "0987654321" -> "+593987654321") para que quede listo tal cual
            # lo necesita send_whatsapp_message (shared/notifications.py).
            self.phone = normalize_phone(self.phone)
            try:
                validate_phone(self.phone)
            except ValidationError as e:
                raise ValidationError({'phone': e.messages})

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
    # Habilita la búsqueda rápida en el POS (invoice_create): un lector de
    # código de barras USB solo "escribe" el código + Enter en el input que
    # esté enfocado, así que no hace falta hardware especial para probarlo.
    barcode = models.CharField(max_length=50, blank=True, null=True, unique=True, verbose_name='Código de barras')
    # Umbral para la notificación de "stock bajo" (ver notificaciones/services.py).
    # 5 replica el umbral fijo que ya usaba el dashboard (home/views.py) antes
    # de que esto fuera configurable por producto.
    stock_minimo = models.PositiveIntegerField(default=5, verbose_name='Stock mínimo')
    # Fecha de vencimiento única y opcional — NO es un sistema de lotes (eso
    # es un módulo de Inventario más grande); solo alcanza para poder avisar
    # "este producto vence pronto" (ver notificaciones/services.py).
    fecha_vencimiento = models.DateField(null=True, blank=True, verbose_name='Fecha de vencimiento')
    is_active = models.BooleanField(default=True, verbose_name='Activo')
    image = models.ImageField(upload_to='products/', blank=True, null=True, verbose_name='Imagen')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Producto'
        verbose_name_plural = 'Productos'
        ordering = ['name']
        permissions = [
            ('access_product_module', 'Acceso al módulo de productos'),
            ('export_pdf_product', 'Puede exportar productos a PDF'),
            ('export_excel_product', 'Puede exportar productos a Excel'),
        ]

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
        # '' -> None: si no, dos productos sin código de barras chocarían
        # contra el unique=True (NULL sí puede repetirse, '' no).
        if self.barcode == '':
            self.barcode = None

    def _generar_barcode(self):
        """EAN-13 interno: prefijo '200' (rango 200-299, reservado por el
        estándar GS1 para uso interno/circulación restringida dentro de una
        empresa — no colisiona con un EAN real de fábrica) + el pk a 9
        dígitos (único por construcción) + dígito verificador EAN-13 estándar."""
        base = f'200{self.pk:09d}'  # 12 dígitos
        pesos = sum(int(d) * (3 if i % 2 else 1) for i, d in enumerate(base))
        digito_verificador = (10 - (pesos % 10)) % 10
        return f'{base}{digito_verificador}'

    def save(self, *args, **kwargs):
        # El código depende del pk (para garantizar que sea único), así que
        # hace falta guardar primero — si barcode sigue vacío después de eso,
        # recién ahí se genera y se guarda de nuevo (un producto con barcode
        # manual, ej. un EAN real de fábrica, nunca pasa por acá).
        super().save(*args, **kwargs)
        if not self.barcode:
            self.barcode = self._generar_barcode()
            super().save(update_fields=['barcode'])


class Customer(models.Model):
    """Clientes. OneToOne con CustomerProfile."""

    # DNI "sentinel" para el cliente genérico de mostrador (ver
    # get_or_create_consumidor_final más abajo). Se eligió un valor que SÍ
    # pasa validate_cedula_ec (provincia 17, dígito verificador real) para
    # que este registro se comporte como cualquier Customer normal si algún
    # día alguien lo abre en el formulario de edición.
    CONSUMIDOR_FINAL_DNI = '1700000001'

    CEDULA = 'cedula'
    RUC = 'ruc'
    PASAPORTE = 'pasaporte'
    TIPO_IDENTIFICACION_CHOICES = [
        (CEDULA, 'Cédula'),
        (RUC, 'RUC'),
        (PASAPORTE, 'Pasaporte'),
    ]

    # Determina qué validador corre sobre `dni` en clean() (más abajo) — ya
    # no se infiere por longitud (10 vs 13 dígitos), porque un pasaporte
    # también puede tener cualquier longitud entre 5 y 20. También decide el
    # código tipoIdentificacionComprador que se manda al SRI (04/05/06, ver
    # facturacion_electronica/xml_builder.py).
    tipo_identificacion = models.CharField(
        max_length=10, choices=TIPO_IDENTIFICACION_CHOICES, default=CEDULA, verbose_name='Tipo de identificación',
    )
    # max_length=20 (no 13): un pasaporte extranjero puede ser más largo que
    # una cédula/RUC ecuatoriana. La validación de FORMA real (checksum de
    # cédula/RUC, o solo forma para pasaporte) vive en clean(), no acá — ya
    # no depende de un único validador fijo por campo.
    dni = models.CharField(max_length=20, unique=True, verbose_name='Cédula / RUC / Pasaporte')
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
        permissions = [
            ('access_customer_module', 'Acceso al módulo de clientes'),
            ('export_pdf_customer', 'Puede exportar clientes a PDF'),
            ('export_excel_customer', 'Puede exportar clientes a Excel'),
        ]
    def __str__(self): return f'{self.last_name}, {self.first_name}'
    @property
    def full_name(self): return f'{self.first_name} {self.last_name}'

    @property
    def es_consumidor_final(self):
        return self.dni == self.CONSUMIDOR_FINAL_DNI

    @classmethod
    def get_or_create_consumidor_final(cls):
        """
        Cliente genérico para ventas de mostrador sin registrar datos reales.
        Sin correo (invoice_create nunca le envía el PDF) y sin crédito
        (ver InvoiceForm.clean() en billing/forms.py).
        """
        customer, _ = cls.objects.get_or_create(
            dni=cls.CONSUMIDOR_FINAL_DNI,
            defaults={'first_name': 'Consumidor', 'last_name': 'Final'},
        )
        return customer

    @property
    def limite_credito(self):
        """
        Límite de crédito = base manual (CustomerProfile.credit_limit; 0 si
        no tiene perfil) + un % configurable (ConfiguracionSistema
        .credito_porcentaje_por_compras, ver configuracion/models.py) del
        total histórico que ha comprado (ver total_comprado_historico) —
        así el crédito crece solo a medida que el cliente compra más, sin
        tener que ajustarlo a mano.
        """
        from configuracion.models import ConfiguracionSistema
        profile = getattr(self, 'profile', None)
        base = profile.credit_limit if profile else Decimal('0')
        # Multiplicar dos Decimal suma sus decimales (2 + 2 = 4), por eso se
        # redondea explícito a 2 — igual que Purchase.aplicar_financiamiento()
        # en purchasing/models.py, para que el precio/crédito nunca se vea
        # con más de 2 decimales en pantalla.
        porcentaje = ConfiguracionSistema.get_solo().credito_fraccion
        crecimiento = (self.total_comprado_historico() * porcentaje).quantize(Decimal('0.01'))
        return base + crecimiento

    def total_comprado_historico(self):
        """Suma del total de TODAS sus facturas activas (no anuladas), sin importar tipo de pago."""
        # SQLite no tiene tipo DECIMAL nativo: Sum() sobre un DecimalField lo
        # calcula internamente como float y devuelve ruido tipo
        # "53.3200000000000" — quantize lo redondea de vuelta a 2 decimales.
        total = self.invoices.filter(is_active=True).aggregate(total=models.Sum('total'))['total']
        return total.quantize(Decimal('0.01')) if total is not None else Decimal('0.00')

    def deuda_actual_credito(self):
        """Suma de saldo en todas sus facturas a crédito todavía PENDIENTES (lo que ya debe)."""
        total = self.invoices.filter(
            tipo_pago=Invoice.CREDITO, estado=Invoice.PENDIENTE
        ).aggregate(total=models.Sum('saldo'))['total']
        return total.quantize(Decimal('0.01')) if total is not None else Decimal('0.00')

    def credito_disponible(self):
        """Cuánto puede comprar a crédito este cliente ahora mismo: límite menos deuda actual."""
        return self.limite_credito - self.deuda_actual_credito()

    def clean(self):
        from django.core.exceptions import ValidationError
        if not self.first_name or not self.first_name.strip():
            raise ValidationError({'first_name': 'El nombre es obligatorio.'})
        if not self.last_name or not self.last_name.strip():
            raise ValidationError({'last_name': 'El apellido es obligatorio.'})
        if self.dni:
            # Qué validador corre depende de tipo_identificacion — ya no se
            # infiere por longitud (ver comentario junto al campo arriba).
            validador = validate_pasaporte if self.tipo_identificacion == self.PASAPORTE else validate_cedula_ec
            try:
                validador(self.dni)
            except ValidationError as e:
                raise ValidationError({'dni': e.messages})
        if self.phone:
            # normalize_phone antepone +593 si no trae código de país (ej.
            # "0987654321" -> "+593987654321") para que quede listo tal cual
            # lo necesita send_whatsapp_message (shared/notifications.py).
            self.phone = normalize_phone(self.phone)
            try:
                validate_phone(self.phone)
            except ValidationError as e:
                raise ValidationError({'phone': e.messages})

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

    # Facturas al CONTADO quedan PAGADA de una (saldo 0); a CREDITO nacen
    # PENDIENTE con saldo = total, y el módulo 'cobros' las va abonando hasta
    # dejarlas en 0 (ver cobros/models.py -> CobroFactura.save()).
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

    # Solo aplica cuando tipo_pago == CONTADO (a crédito todavía no hay
    # movimiento de dinero real que clasificar). EFECTIVO y TARJETA exigen
    # una SesionCaja abierta del usuario (venta de mostrador), pero solo
    # EFECTIVO genera un MovimientoCaja automático (ver billing/views.py ->
    # invoice_create / _finalizar_venta) y exige registrar monto_recibido/
    # cambio (ver más abajo) — con tarjeta el dinero no entra físicamente a
    # la caja, va a un datáfono externo.
    # TARJETA es una captura puramente informativa: no hay pasarela de pago
    # real integrada (no Stripe ni similar), así que solo se registran
    # titular/últimos 4 dígitos/expiración como constancia de que se cobró
    # por un datáfono aparte — nunca se guarda el número completo de tarjeta.
    # PAYPAL es distinto a las otras: el pago se confirma de forma
    # asíncrona (el navegador sale a paypal.com y vuelve), así que la Invoice
    # NO se crea en el momento del POST — ver paypal_pagos/services.py.
    EFECTIVO = 'efectivo'
    TARJETA = 'tarjeta'
    PAYPAL = 'paypal'
    FORMA_PAGO_CHOICES = [
        (EFECTIVO, 'Efectivo'),
        (TARJETA, 'Tarjeta'),
        (PAYPAL, 'PayPal'),
    ]

    customer = models.ForeignKey(Customer, on_delete=models.PROTECT, related_name='invoices', verbose_name='Cliente')
    invoice_date = models.DateTimeField(auto_now_add=True, verbose_name='Fecha')
    subtotal = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name='Subtotal')
    tax = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name='IVA')
    total = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name='Total')
    tipo_pago = models.CharField(
        max_length=10, choices=TIPO_PAGO_CHOICES, default=CONTADO, verbose_name='Tipo de pago'
    )
    forma_pago = models.CharField(
        max_length=15, choices=FORMA_PAGO_CHOICES, blank=True, null=True, verbose_name='Forma de pago'
    )
    saldo = models.DecimalField(
        max_digits=12, decimal_places=2, default=0, verbose_name='Saldo pendiente'
    )
    estado = models.CharField(
        max_length=10, choices=ESTADO_CHOICES, default=PAGADA, verbose_name='Estado'
    )
    # is_active representa si la factura está "anulada" (False) o vigente
    # (True) — una factura anulada no puede recibir cobros (ver cobros/models.py)
    # ni devoluciones (ver devoluciones/models.py).
    is_active = models.BooleanField(default=True, verbose_name='Activo')
    # meses_credito/interes: mismo sistema de financiamiento que
    # Purchase.meses_credito/interes (purchasing/models.py) — duplicado acá
    # en vez de compartido porque ventas y compras son dominios de negocio
    # distintos en este proyecto, y ya es el estilo (ver Purchase para el
    # espejo exacto de cada pieza de abajo).
    meses_credito = models.PositiveSmallIntegerField(
        null=True, blank=True, verbose_name='Meses para diferir'
    )
    interes = models.DecimalField(
        max_digits=12, decimal_places=2, default=0, verbose_name='Interés'
    )
    # Solo aplica a ventas al CONTADO en EFECTIVO: cuánto dinero entregó el
    # cliente físicamente (para calcular el cambio, ver la property abajo).
    monto_recibido = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True, verbose_name='Monto recibido en efectivo'
    )
    # Solo aplican a ventas al CONTADO en TARJETA — informativos, nunca se
    # guarda el número completo de la tarjeta (ver comentario junto a
    # FORMA_PAGO_CHOICES arriba).
    tarjeta_titular = models.CharField(
        max_length=150, null=True, blank=True, verbose_name='Titular de la tarjeta'
    )
    # OJO: guardar el CVV/CVC es una decisión explícita del usuario pese a
    # que va contra PCI-DSS (que prohíbe retener el CVV bajo cualquier
    # circunstancia, incluso "informativa") — se documenta acá para que
    # quede claro que no es un descuido sino algo que se decidió a
    # sabiendas, no para replicar en un sistema que procese tarjetas reales.
    tarjeta_cvv = models.CharField(
        max_length=4, null=True, blank=True, verbose_name='CVV/CVC'
    )
    tarjeta_expiracion = models.DateField(
        null=True, blank=True, verbose_name='Fecha de expiración de la tarjeta'
    )
    class Meta:
        verbose_name = 'Factura'
        verbose_name_plural = 'Facturas'
        ordering = ['-invoice_date']
        # Django ya trae view_invoice/add_invoice/change_invoice/delete_invoice
        # automáticos, pero solo esos 4 — antes, view_invoice controlaba a la
        # vez si el listado completo de facturas cargaba Y si el botón "Ver"
        # de una factura puntual funcionaba, todo con el mismo permiso. Ahora
        # se separan: access_invoice_module = entrar al listado (el módulo
        # completo); view_invoice = solo el botón/acceso a una factura
        # puntual (detalle, PDF). Mismo patrón replicado en el resto de
        # modelos con lista+detalle (Brand, ProductGroup, Supplier, Product,
        # Customer acá arriba; Purchase, PagoCompra, CobroFactura, SesionCaja,
        # DevolucionVenta en sus respectivas apps).
        permissions = [
            ('access_invoice_module', 'Acceso al módulo de facturas'),
            ('export_pdf_invoice', 'Puede exportar facturas a PDF'),
            ('export_excel_invoice', 'Puede exportar facturas a Excel'),
            # Botón "Recordar" en Facturas Pendientes de Cobro (cobros app) —
            # abre un link wa.me con un recordatorio de pago ya redactado,
            # no envía nada automático (ver Invoice.whatsapp_recordatorio_url).
            ('send_whatsapp_invoice', 'Puede enviar recordatorio de pago por WhatsApp'),
        ]
    def __str__(self): return f'Factura #{self.id} - {self.customer}'

    MESES_CREDITO_MAX = 36

    # Mismos tramos que Purchase.INTERES_TIERS — a más meses de plazo, mayor
    # la tasa de interés total sobre el valor de la factura.
    INTERES_TIERS = [
        (3, Decimal('0.05')),
        (6, Decimal('0.10')),
        (12, Decimal('0.15')),
        (24, Decimal('0.20')),
        (36, Decimal('0.25')),
    ]

    def clean(self):
        from django.core.exceptions import ValidationError
        if self.tipo_pago == self.CONTADO:
            if not self.forma_pago:
                raise ValidationError({'forma_pago': 'Indica la forma de pago (efectivo, tarjeta o PayPal).'})
            if self.meses_credito:
                raise ValidationError({'meses_credito': 'Una factura al contado no puede tener meses de crédito.'})
        else:
            if self.forma_pago:
                raise ValidationError({'forma_pago': 'Una factura a crédito no debe tener forma de pago.'})
            if not self.meses_credito or self.meses_credito < 1:
                raise ValidationError({
                    'meses_credito': 'Indica a cuántos meses se difiere una factura a crédito (mínimo 1).'
                })
            if self.meses_credito > self.MESES_CREDITO_MAX:
                raise ValidationError({
                    'meses_credito': f'El plazo máximo permitido es de {self.MESES_CREDITO_MAX} meses.'
                })

    @classmethod
    def tasa_interes(cls, meses):
        """Tasa total (no mensual) que corresponde a un plazo de `meses` — copia exacta de Purchase.tasa_interes."""
        for limite, tasa in cls.INTERES_TIERS:
            if meses <= limite:
                return tasa
        return cls.INTERES_TIERS[-1][1]

    def aplicar_tipo_pago(self):
        """
        Fija interés/saldo/estado a partir de tipo_pago, meses_credito y
        total (total ya debe estar calculado). Se llama explícitamente desde
        invoice_create (_finalizar_venta), igual que
        Purchase.aplicar_financiamiento() en purchasing/models.py.

        Si es CREDITO sin meses_credito (facturas creadas antes de este
        cambio, o cualquier camino que no pase por full_clean()) el
        comportamiento queda igual que antes: sin interés, saldo = total —
        no rompe nada existente.
        """
        if self.tipo_pago == self.CREDITO:
            if self.meses_credito:
                self.interes = (self.total * self.tasa_interes(self.meses_credito)).quantize(Decimal('0.01'))
            else:
                self.interes = Decimal('0')
            self.saldo = self.total + self.interes
            self.estado = self.PENDIENTE if self.saldo > 0 else self.PAGADA
        else:
            self.interes = Decimal('0')
            self.saldo = 0
            self.estado = self.PAGADA

    @property
    def total_a_pagar(self):
        """Total + interés: lo que realmente hay que cobrarle al cliente."""
        return self.total + self.interes

    @property
    def cambio(self):
        """Vuelto a devolver en una venta al contado en efectivo. None si no aplica."""
        if self.forma_pago != self.EFECTIVO or self.monto_recibido is None:
            return None
        return (self.monto_recibido - self.total).quantize(Decimal('0.01'))

    @property
    def cuota_minima(self):
        """
        Cobro mínimo por abono para terminar de cancelar la factura dentro de
        los meses pactados (total_a_pagar / meses_credito). None si no aplica
        (factura al contado o sin meses definidos).
        """
        if self.tipo_pago != self.CREDITO or not self.meses_credito:
            return None
        return (self.total_a_pagar / self.meses_credito).quantize(Decimal('0.01'))

    @property
    def whatsapp_recordatorio_url(self):
        """
        Link "wa.me" con un mensaje de recordatorio de pago pendiente ya
        redactado — al tocarlo se abre WhatsApp (Web o app) con el chat del
        cliente y el mensaje listo para enviar (el usuario solo presiona
        "Enviar"). No manda nada automáticamente: es deliberadamente simple,
        sin depender de una API de WhatsApp (Twilio, etc.). None si el
        cliente no tiene teléfono registrado.
        """
        if not self.customer.phone:
            return None
        from urllib.parse import quote
        from configuracion.models import ConfiguracionSistema
        empresa = ConfiguracionSistema.get_solo().empresa_nombre
        mensaje = (
            f'Hola {self.customer.full_name}, te recordamos que tienes un pago pendiente '
            f'de ${self.saldo} correspondiente a la factura #{self.id:04d} de {empresa}. '
            f'Por favor realiza tu pago a la brevedad. ¡Gracias!'
        )
        return f'https://wa.me/{self.customer.phone.lstrip("+")}?text={quote(mensaje)}'

    @property
    def fecha_limite_pago(self):
        """
        Última fecha en la que se puede registrar un cobro (fecha de la
        factura + meses_credito). None si no es a crédito. Copia exacta de
        Purchase.fecha_limite_pago, usando invoice_date en vez de purchase_date.
        """
        if self.tipo_pago != self.CREDITO or not self.meses_credito:
            return None
        import calendar
        fecha = self.invoice_date.date()
        mes_total = fecha.month - 1 + self.meses_credito
        anio = fecha.year + mes_total // 12
        mes = mes_total % 12 + 1
        dia = min(fecha.day, calendar.monthrange(anio, mes)[1])
        return fecha.replace(year=anio, month=mes, day=dia)

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