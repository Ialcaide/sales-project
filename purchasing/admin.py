from django.contrib import admin
from .models import Bodega, Purchase, PurchaseDetail

class PurchaseDetailInline(admin.TabularInline):
    model = PurchaseDetail
    extra = 3
    fields = ['product', 'quantity', 'unit_cost', 'subtotal']
    readonly_fields = ['subtotal']

@admin.register(Purchase)
class PurchaseAdmin(admin.ModelAdmin):
    list_display = ['id', 'supplier', 'document_number', 'purchase_date', 'total']
    inlines = [PurchaseDetailInline]

@admin.register(Bodega)
class BodegaAdmin(admin.ModelAdmin):
    list_display = ['nombre', 'is_active']
    search_fields = ['nombre']