from django.urls import path

from . import views

app_name = 'configuracion'

urlpatterns = [
    path('', views.configuracion_editar, name='configuracion_editar'),
    path(
        'facturacion-electronica/conectar/', views.conectar_facturacion_electronica,
        name='conectar_facturacion_electronica',
    ),
    path(
        'facturacion-electronica/vincular/', views.vincular_empresa_existente,
        name='vincular_empresa_existente',
    ),
    path(
        'facturacion-electronica/<int:pk>/activar/', views.activar_empresa_facturacion_electronica,
        name='activar_empresa_facturacion_electronica',
    ),
    path(
        'facturacion-electronica/editar/', views.editar_empresa_activa,
        name='editar_empresa_activa',
    ),
    path(
        'facturacion-electronica/cambiar-ambiente/', views.cambiar_ambiente_empresa_activa,
        name='cambiar_ambiente_empresa_activa',
    ),
]
