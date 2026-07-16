from django.contrib import admin
from .models import CobroFactura


@admin.register(CobroFactura)
class CobroFacturaAdmin(admin.ModelAdmin):
    list_display = ('id', 'factura', 'fecha', 'valor')
    list_filter = ('fecha',)
    search_fields = ('factura__customer__last_name', 'factura__customer__first_name')
    date_hierarchy = 'fecha'
