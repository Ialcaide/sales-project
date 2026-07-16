from django.urls import path

from . import views

app_name = 'facturacion_electronica'

urlpatterns = [
    path('facturas/<int:invoice_id>/reintentar/', views.comprobante_reintentar, name='comprobante_reintentar'),
    path('<int:pk>/consultar-autorizacion/', views.comprobante_consultar_autorizacion, name='comprobante_consultar_autorizacion'),
    path('<int:pk>/xml/', views.comprobante_xml_download, name='comprobante_xml_download'),
    path('<int:pk>/ride/', views.comprobante_ride_pdf, name='comprobante_ride_pdf'),
    path('api/verificar/', views.verificar_autorizacion_api, name='verificar_autorizacion_api'),
]
