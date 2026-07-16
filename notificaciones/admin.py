from django.contrib import admin

from .models import Notificacion


@admin.register(Notificacion)
class NotificacionAdmin(admin.ModelAdmin):
    list_display = ('tipo', 'nivel', 'mensaje', 'usuario', 'leida', 'fecha')
    list_filter = ('tipo', 'nivel', 'leida')
    search_fields = ('mensaje', 'clave')
