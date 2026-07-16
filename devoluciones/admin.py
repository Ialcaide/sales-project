from django.contrib import admin
from .models import DevolucionDetalle, DevolucionVenta


class DevolucionDetalleInline(admin.TabularInline):
    model = DevolucionDetalle
    extra = 0
    readonly_fields = ('subtotal',)


@admin.register(DevolucionVenta)
class DevolucionVentaAdmin(admin.ModelAdmin):
    list_display = ('id', 'factura', 'fecha', 'usuario')
    search_fields = ('factura__customer__last_name',)
    inlines = [DevolucionDetalleInline]
