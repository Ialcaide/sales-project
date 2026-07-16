from django.urls import path
from . import views

app_name = 'pagos'

urlpatterns = [
    path('pendientes/', views.purchase_pending_list, name='purchase_pending_list'),
    path('crear/<int:compra_id>/', views.pago_create, name='pago_create'),
    path('historial/', views.pago_list, name='pago_list'),
    path('<int:pk>/editar/', views.pago_update, name='pago_update'),
    path('<int:pk>/eliminar/', views.pago_delete, name='pago_delete'),
    path('<int:pk>/pdf/', views.pago_pdf, name='pago_pdf'),
]
