from django.apps import AppConfig


class NotificacionesConfig(AppConfig):
    name = 'notificaciones'

    def ready(self):
        from . import signals  # noqa: F401 - solo registra los receivers de Telegram
