from django.conf import settings
from django.db import models


class Notificacion(models.Model):
    """
    Alerta interna del sistema (stock bajo, producto por vencer, pago
    pendiente, alerta de caja). Se crea desde notificaciones/services.py,
    nunca directo desde una vista — ver ese archivo para el porqué de cada tipo.
    """
    STOCK_BAJO = 'stock_bajo'
    PRODUCTO_VENCE = 'producto_vence'
    PAGO_PENDIENTE = 'pago_pendiente'
    CAJA_ALERTA = 'caja_alerta'
    TIPO_CHOICES = [
        (STOCK_BAJO, 'Stock bajo'),
        (PRODUCTO_VENCE, 'Producto por vencer'),
        (PAGO_PENDIENTE, 'Pago pendiente'),
        (CAJA_ALERTA, 'Alerta de caja'),
    ]

    INFO = 'info'
    WARNING = 'warning'
    DANGER = 'danger'
    NIVEL_CHOICES = [
        (INFO, 'Info'),
        (WARNING, 'Advertencia'),
        (DANGER, 'Crítico'),
    ]

    tipo = models.CharField(max_length=20, choices=TIPO_CHOICES, verbose_name='Tipo')
    nivel = models.CharField(max_length=10, choices=NIVEL_CHOICES, default=WARNING, verbose_name='Nivel')
    mensaje = models.CharField(max_length=255, verbose_name='Mensaje')
    # None = visible para cualquiera con permiso de ver notificaciones (stock
    # bajo, pagos pendientes, vencimientos: son asuntos del negocio, no de
    # una persona). Con usuario = alerta dirigida (ej. la diferencia de caja
    # le corresponde al cajero que la cerró).
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.CASCADE,
        related_name='notificaciones', verbose_name='Usuario',
    )
    url = models.CharField(max_length=200, blank=True, verbose_name='Enlace')
    leida = models.BooleanField(default=False, verbose_name='Leída')
    fecha = models.DateTimeField(auto_now_add=True, verbose_name='Fecha')
    # Clave de deduplicación (ej. "stock_bajo:producto:42"): mientras exista
    # una notificación CON ESTA CLAVE sin leer, no se crea una nueva — ver el
    # constraint de abajo y _crear_si_no_existe() en services.py.
    clave = models.CharField(max_length=100, verbose_name='Clave')

    class Meta:
        verbose_name = 'Notificación'
        verbose_name_plural = 'Notificaciones'
        ordering = ['-fecha']
        constraints = [
            models.UniqueConstraint(
                fields=['clave'], condition=models.Q(leida=False),
                name='unica_no_leida_por_clave',
            )
        ]

    def __str__(self):
        return f'[{self.get_tipo_display()}] {self.mensaje}'
