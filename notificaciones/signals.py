"""
Aviso amplio de actividad a Telegram: a diferencia de services.py (que
crea Notificacion para 4 alertas de negocio curadas — stock bajo, caja,
vencimientos — y esas SÍ aparecen en la campanita), este módulo escucha
CUALQUIER alta/edición/borrado de las apps de negocio del sistema, más
cada inicio de sesión, y los manda SOLO a Telegram (no ensucian la
campanita, que es para alertas accionables, no un log de auditoría).

Se conecta una sola vez desde NotificacionesConfig.ready().
"""
from django.conf import settings
from django.contrib.auth.signals import user_logged_in
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from shared.notifications import send_telegram_message

# Apps de negocio a rastrear. 'auth' se incluye SOLO para User/Group (ver
# _MODELOS_EXCLUIDOS más abajo) — Permission no se rastrea: Django la
# reescribe en cada migrate y no es un cambio de negocio.
_APPS_RASTREADAS = {
    'billing', 'purchasing', 'security', 'pagos', 'cobros', 'caja',
    'devoluciones', 'configuracion', 'paypal_pagos', 'facturacion_electronica',
    'auth',
}

_MODELOS_EXCLUIDOS = {
    ('auth', 'permission'),
}

_NOMBRES_AMIGABLES = {
    ('auth', 'user'): 'Usuario',
    ('auth', 'group'): 'Rol',
}


def _telegram_configurado():
    return bool(settings.TELEGRAM_BOT_TOKEN and settings.TELEGRAM_CHAT_ID)


def _debe_rastrear(sender):
    app_label = sender._meta.app_label
    if app_label not in _APPS_RASTREADAS:
        return False
    return (app_label, sender._meta.model_name) not in _MODELOS_EXCLUIDOS


def _nombre_modelo(sender):
    clave = (sender._meta.app_label, sender._meta.model_name)
    if clave in _NOMBRES_AMIGABLES:
        return _NOMBRES_AMIGABLES[clave]
    return str(sender._meta.verbose_name).capitalize()


def _es_solo_actualizacion_de_last_login(update_fields):
    # Cada login real de Django guarda user.last_login con
    # save(update_fields=['last_login']) — eso ya lo cubre el aviso de
    # user_logged_in de abajo con más detalle; avisar acá también sería
    # el mismo evento duplicado.
    return update_fields is not None and set(update_fields) == {'last_login'}


@receiver(post_save, dispatch_uid='notificaciones_avisar_alta_o_edicion')
def _avisar_alta_o_edicion(sender, instance, created, raw, update_fields, **kwargs):
    # `raw=True` = carga de fixtures/loaddata, no un cambio real de negocio.
    if raw or not _telegram_configurado() or not _debe_rastrear(sender):
        return
    if not created and _es_solo_actualizacion_de_last_login(update_fields):
        return
    emoji, accion = ('🆕', 'creó') if created else ('✏️', 'editó')
    send_telegram_message(f'{emoji} Se {accion} {_nombre_modelo(sender)}: {instance}')


@receiver(post_delete, dispatch_uid='notificaciones_avisar_borrado')
def _avisar_borrado(sender, instance, **kwargs):
    if not _telegram_configurado() or not _debe_rastrear(sender):
        return
    send_telegram_message(f'🗑️ Se eliminó {_nombre_modelo(sender)}: {instance}')


@receiver(user_logged_in, dispatch_uid='notificaciones_avisar_login')
def _avisar_login(sender, request, user, **kwargs):
    if not _telegram_configurado():
        return
    nombre = f'{user.first_name} {user.last_name}'.strip() or user.username
    send_telegram_message(f'🔓 Inicio de sesión: {nombre} ({user.username})')
