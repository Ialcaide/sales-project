from django.contrib import admin
from .models import MovimientoCaja, SesionCaja


@admin.register(SesionCaja)
class SesionCajaAdmin(admin.ModelAdmin):
    list_display = ('id', 'usuario', 'fecha_apertura', 'monto_inicial', 'estado', 'fecha_cierre')
    list_filter = ('estado',)
    search_fields = ('usuario__username',)


@admin.register(MovimientoCaja)
class MovimientoCajaAdmin(admin.ModelAdmin):
    list_display = ('id', 'sesion', 'tipo', 'monto', 'concepto', 'fecha')
    list_filter = ('tipo',)
    search_fields = ('concepto',)
