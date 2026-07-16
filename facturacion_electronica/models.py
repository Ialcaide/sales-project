from django.db import models, transaction


class SecuencialSRI(models.Model):
    """
    Contador estrictamente incremental por (establecimiento, punto_emision,
    tipo_comprobante) — el que exige el SRI para numerar comprobantes
    (001-001-000000001, 002, 003...), DISTINTO del Invoice.id interno de
    Django (que puede tener huecos por facturas eliminadas, o mezclarse con
    otros tipos de comprobante). Nunca se resetea ni se salta un número: si
    un envío falla después de reservarlo, ese número queda "quemado" (así
    lo exige el SRI, no se reutiliza).
    """
    establecimiento = models.CharField(max_length=3)
    punto_emision = models.CharField(max_length=3)
    tipo_comprobante = models.CharField(max_length=2, default='01')
    ultimo_secuencial = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name = 'Secuencial SRI'
        verbose_name_plural = 'Secuenciales SRI'
        constraints = [
            models.UniqueConstraint(
                fields=['establecimiento', 'punto_emision', 'tipo_comprobante'],
                name='unique_secuencial_sri_por_serie',
            )
        ]

    def __str__(self):
        return f'{self.establecimiento}-{self.punto_emision}-{self.tipo_comprobante}: {self.ultimo_secuencial}'

    @classmethod
    def siguiente(cls, establecimiento, punto_emision, tipo_comprobante='01'):
        """Reserva y devuelve el próximo número de la serie, de forma segura
        ante llamadas concurrentes (select_for_update dentro de una
        transacción) — mismo cuidado de concurrencia que CobroFactura.save()."""
        with transaction.atomic():
            contador, _ = cls.objects.select_for_update().get_or_create(
                establecimiento=establecimiento, punto_emision=punto_emision, tipo_comprobante=tipo_comprobante,
            )
            contador.ultimo_secuencial += 1
            contador.save(update_fields=['ultimo_secuencial'])
            return contador.ultimo_secuencial


class ComprobanteElectronico(models.Model):
    """
    Estado de la factura electrónica de una Invoice ante el SRI. Se crea
    (best-effort, nunca bloquea la venta) desde
    billing/views.py -> _finalizar_venta, vía
    facturacion_electronica/services.py -> generar_y_enviar_comprobante().
    """
    GENERADO = 'generado'
    FIRMADO = 'firmado'
    ENVIADO = 'enviado'
    RECIBIDA = 'recibida'
    DEVUELTA = 'devuelta'
    EN_PROCESO = 'en_proceso'
    AUTORIZADO = 'autorizado'
    NO_AUTORIZADO = 'no_autorizado'
    ERROR = 'error'
    ESTADO_CHOICES = [
        (GENERADO, 'XML generado'),
        (FIRMADO, 'XML firmado'),
        (ENVIADO, 'Enviado al SRI'),
        (RECIBIDA, 'Recibida por el SRI'),
        (DEVUELTA, 'Devuelta por el SRI'),
        (EN_PROCESO, 'En procesamiento'),
        (AUTORIZADO, 'Autorizado'),
        (NO_AUTORIZADO, 'No autorizado'),
        (ERROR, 'Error'),
    ]

    AMBIENTE_PRUEBAS = '1'
    AMBIENTE_PRODUCCION = '2'
    AMBIENTE_CHOICES = [
        (AMBIENTE_PRUEBAS, 'Pruebas'),
        (AMBIENTE_PRODUCCION, 'Producción'),
    ]

    invoice = models.OneToOneField(
        'billing.Invoice', on_delete=models.PROTECT, related_name='comprobante_electronico', verbose_name='Factura',
    )
    tipo_comprobante = models.CharField(max_length=2, default='01', verbose_name='Tipo de comprobante')
    ambiente = models.CharField(max_length=1, choices=AMBIENTE_CHOICES, default=AMBIENTE_PRUEBAS, verbose_name='Ambiente')
    establecimiento = models.CharField(max_length=3, verbose_name='Establecimiento')
    punto_emision = models.CharField(max_length=3, verbose_name='Punto de emisión')
    secuencial = models.CharField(max_length=9, verbose_name='Secuencial')
    clave_acceso = models.CharField(max_length=49, unique=True, verbose_name='Clave de acceso')
    estado = models.CharField(max_length=15, choices=ESTADO_CHOICES, default=GENERADO, verbose_name='Estado')

    xml_generado = models.TextField(blank=True, verbose_name='XML sin firmar')
    xml_firmado = models.TextField(blank=True, verbose_name='XML firmado')
    xml_autorizado = models.TextField(blank=True, verbose_name='XML autorizado (con el comprobante del SRI)')

    numero_autorizacion = models.CharField(max_length=49, blank=True, verbose_name='Número de autorización')
    fecha_autorizacion = models.DateTimeField(null=True, blank=True, verbose_name='Fecha de autorización')
    # Mensajes de error/advertencia que devuelve el SRI en recepción o
    # autorización (o el traceback resumido si falló algo antes de llegar a
    # hablar con el SRI, ej. el certificado no carga) — lista de strings.
    mensajes = models.JSONField(default=list, blank=True, verbose_name='Mensajes')

    creado_en = models.DateTimeField(auto_now_add=True, verbose_name='Creado en')
    actualizado_en = models.DateTimeField(auto_now=True, verbose_name='Última actualización')

    class Meta:
        verbose_name = 'Comprobante Electrónico'
        verbose_name_plural = 'Comprobantes Electrónicos'
        ordering = ['-creado_en']

    def __str__(self):
        return f'Comprobante {self.clave_acceso} ({self.get_estado_display()})'
