from django.urls import path
from . import views

app_name = 'cobros'

urlpatterns = [
    path('pendientes/', views.invoice_pending_list, name='invoice_pending_list'),
    path('crear/<int:factura_id>/', views.cobro_create, name='cobro_create'),
    path('crear/<int:factura_id>/paypal/', views.cobro_paypal_iniciar, name='cobro_paypal_iniciar'),
    path('historial/', views.cobro_list, name='cobro_list'),
    path('<int:pk>/editar/', views.cobro_update, name='cobro_update'),
    path('<int:pk>/eliminar/', views.cobro_delete, name='cobro_delete'),
    path('<int:pk>/pdf/', views.cobro_pdf, name='cobro_pdf'),
]
