from django.urls import path

from . import views

app_name = 'reportes'

urlpatterns = [
    path('', views.reporte_index, name='reporte_index'),
    path('ventas/', views.reporte_ventas, name='reporte_ventas'),
    path('compras/', views.reporte_compras, name='reporte_compras'),
    path('inventario/', views.reporte_inventario, name='reporte_inventario'),
    path('caja/', views.reporte_caja, name='reporte_caja'),
]
