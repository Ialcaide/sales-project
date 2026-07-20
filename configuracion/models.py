from decimal import Decimal

from django.db import models


class ConfiguracionSistema(models.Model):
    """Configuración única del sistema (singleton: siempre pk=1, ver save()).
    Reemplaza valores que antes estaban hardcodeados en Python — IVA, nombre
    de la empresa, % de crédito por compras, umbrales por defecto — para que
    un administrador los pueda ajustar desde la UI sin tocar código."""

    AMBIENTE_PRUEBAS = '1'
    AMBIENTE_PRODUCCION = '2'
    AMBIENTE_CHOICES = [
        (AMBIENTE_PRUEBAS, 'Pruebas'),
        (AMBIENTE_PRODUCCION, 'Producción'),
    ]

    empresa_nombre = models.CharField(max_length=200, default='TecnoStock S.A.', verbose_name='Nombre de la empresa')
    empresa_ruc = models.CharField(max_length=13, blank=True, verbose_name='RUC')
    empresa_direccion = models.CharField(max_length=255, blank=True, verbose_name='Dirección')
    empresa_telefono = models.CharField(max_length=20, blank=True, verbose_name='Teléfono')

    iva_porcentaje = models.DecimalField(
        max_digits=5, decimal_places=2, default=Decimal('15.00'), verbose_name='IVA (%)'
    )
    # Solo se guarda: las plantillas existentes siguen mostrando '$' fijo (ver
    # el plan — reescribir los ~138 usos en templates queda fuera de alcance).
    moneda_simbolo = models.CharField(max_length=5, default='$', verbose_name='Símbolo de moneda')

    stock_minimo_default = models.PositiveIntegerField(
        default=5, verbose_name='Stock mínimo por defecto (productos nuevos)'
    )
    credito_porcentaje_por_compras = models.DecimalField(
        max_digits=5, decimal_places=2, default=Decimal('30.00'),
        verbose_name='% de crédito por compras históricas',
    )
    dias_aviso_vencimiento_producto = models.PositiveIntegerField(
        default=30, verbose_name='Días de aviso: producto por vencer'
    )
    dias_aviso_pago_compra = models.PositiveIntegerField(
        default=5, verbose_name='Días de aviso: pago de compra pendiente'
    )
    dias_credito_factura_default = models.PositiveIntegerField(
        default=30, verbose_name='Días de plazo por defecto (facturas a crédito sin perfil)'
    )

    # === Facturación electrónica (SRI) ===
    # Datos NO secretos de la numeración/identificación del emisor ante el
    # SRI — el certificado de firma (.p12) y su contraseña sí son secretos,
    # y NUNCA se guardan acá: viajan una sola vez al conectar/renovar (ver
    # configuracion/views.py -> conectar_facturacion_electronica) y se
    # descartan. empresa_ruc/empresa_direccion (arriba) ya cubren el RUC y
    # la dirección matriz que exige el XML de factura.
    sri_establecimiento = models.CharField(
        max_length=3, default='001', verbose_name='Código de establecimiento (SRI)'
    )
    sri_punto_emision = models.CharField(
        max_length=3, default='001', verbose_name='Código de punto de emisión (SRI)'
    )
    sri_obligado_contabilidad = models.BooleanField(
        default=False, verbose_name='Obligado a llevar contabilidad'
    )
    sri_nombre_comercial = models.CharField(
        max_length=200, blank=True, verbose_name='Nombre comercial (si difiere de la razón social)'
    )
    sri_ambiente = models.CharField(
        max_length=1, choices=AMBIENTE_CHOICES, default=AMBIENTE_PRUEBAS, verbose_name='Ambiente (SRI)',
    )
    # El id/api_key de la conexión con el microservicio ya NO viven acá:
    # ahora puede haber VARIAS empresas conectadas (ver
    # EmpresaFacturacionElectronica más abajo), cada una con su propio id/
    # api_key, y una marcada activa=True — esa es la que
    # facturacion_electronica/services.py usa en cada venta.

    # === Compras ===
    retencion_porcentaje_default = models.DecimalField(
        max_digits=5, decimal_places=2, default=Decimal('0.00'),
        verbose_name='% de retención por defecto (compras)',
    )

    class Meta:
        verbose_name = 'Configuración del sistema'
        verbose_name_plural = 'Configuración del sistema'

    def __str__(self):
        return 'Configuración del sistema'

    @property
    def iva_fraccion(self):
        return self.iva_porcentaje / Decimal('100')

    @property
    def credito_fraccion(self):
        return self.credito_porcentaje_por_compras / Decimal('100')

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def get_solo(cls):
        return cls.objects.get_or_create(pk=1)[0]


class EmpresaFacturacionElectronica(models.Model):
    """Una empresa/RUC conectada al microservicio de facturación
    electrónica. A diferencia de ConfiguracionSistema (singleton), acá puede
    haber varias — pero solo UNA con activa=True a la vez (ver save()): es
    la que facturacion_electronica/services.py usa para autenticarse contra
    el microservicio en cada venta. El cambio de "cuál es la activa" lo hace
    un administrador a mano desde Configuración, nunca automático por venta."""

    ruc = models.CharField(max_length=13, verbose_name='RUC')
    razon_social = models.CharField(max_length=200, verbose_name='Razón social')
    direccion_matriz = models.CharField(max_length=255, verbose_name='Dirección matriz')
    codigo_establecimiento = models.CharField(max_length=3, verbose_name='Código de establecimiento')
    codigo_punto_emision = models.CharField(max_length=3, verbose_name='Código de punto de emisión')
    ambiente = models.CharField(
        max_length=1, choices=ConfiguracionSistema.AMBIENTE_CHOICES,
        default=ConfiguracionSistema.AMBIENTE_PRUEBAS, verbose_name='Ambiente',
    )
    empresa_id_microservicio = models.CharField(
        max_length=50, verbose_name='ID de empresa en el microservicio',
    )
    api_key = models.CharField(max_length=255, verbose_name='API key')
    activa = models.BooleanField(default=False, verbose_name='Activa')
    fecha_conexion = models.DateTimeField(auto_now_add=True, verbose_name='Fecha de conexión')

    class Meta:
        verbose_name = 'Empresa de facturación electrónica'
        verbose_name_plural = 'Empresas de facturación electrónica'
        ordering = ['-activa', '-fecha_conexion']

    def __str__(self):
        return f'{self.razon_social} ({self.ruc})'

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if self.activa:
            EmpresaFacturacionElectronica.objects.exclude(pk=self.pk).update(activa=False)

    @classmethod
    def get_activa(cls):
        return cls.objects.filter(activa=True).first()
