from django.core.management.base import BaseCommand

from notificaciones.services import sincronizar_pagos_pendientes, sincronizar_productos_por_vencer


class Command(BaseCommand):
    help = (
        'Genera notificaciones de productos por vencer y pagos pendientes '
        '(compras y facturas a crédito). Correr periódicamente — en '
        'producción se agendaría con un cron diario (ej. Render Cron Jobs); '
        'este proyecto no tiene Celery ni scheduler, así que por ahora se '
        'corre a mano: python manage.py generar_notificaciones. '
        'Las alertas de stock bajo y de diferencia de caja NO se generan acá '
        '— esas se disparan solas en tiempo real (ver notificaciones/services.py).'
    )

    def handle(self, *args, **kwargs):
        vencimientos = sincronizar_productos_por_vencer()
        pagos = sincronizar_pagos_pendientes()
        self.stdout.write(self.style.SUCCESS(
            f'{len(vencimientos)} notificación(es) de productos por vencer y '
            f'{len(pagos)} de pagos pendientes creadas.'
        ))
