from django.contrib import admin
from .models import TipoPrestamo, Empleado, Prestamo, PrestamoDetalle

class PrestamoDetalleInline(admin.TabularInline):
    model = PrestamoDetalle
    extra = 0
    max_num = 0
    readonly_fields = ['numero_cuota', 'fecha_vencimiento', 'valor_cuota', 'saldo_cuota']
    can_delete = False


@admin.register(TipoPrestamo)
class TipoPrestamoAdmin(admin.ModelAdmin):
    list_display = ['descripcion', 'tasa_interes', 'monto_maximo']
    search_fields = ['descripcion']


@admin.register(Empleado)
class EmpleadoAdmin(admin.ModelAdmin):
    list_display = ['nombres', 'user', 'sueldo', 'limite_credito']
    search_fields = ['nombres', 'user__username']


@admin.register(Prestamo)
class PrestamoAdmin(admin.ModelAdmin):
    list_display = ['id', 'empleado', 'tipo_prestamo', 'fecha_prestamo', 'monto', 'monto_pagar', 'saldo', 'estado']
    list_filter = ['estado', 'tipo_prestamo', 'fecha_prestamo']
    search_fields = ['empleado__nombres', 'tipo_prestamo__descripcion']
    readonly_fields = ['interes', 'monto_pagar', 'saldo']
    inlines = [PrestamoDetalleInline]

    class Media:
        js = ('admin/js/simulador_prestamo.js',)


@admin.register(PrestamoDetalle)
class PrestamoDetalleAdmin(admin.ModelAdmin):
    list_display = ['prestamo', 'numero_cuota', 'fecha_vencimiento', 'valor_cuota', 'saldo_cuota']
    list_filter = ['fecha_vencimiento']
    search_fields = ['prestamo__empleado__nombres']
