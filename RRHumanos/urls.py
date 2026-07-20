from django.urls import path
from . import views

app_name = 'RRHumanos'

urlpatterns = [
    path('prestamos/', views.PrestamoListView.as_view(), name='prestamo_list'),
    path('prestamos/<int:pk>/', views.PrestamoDetailView.as_view(), name='prestamo_detail'),
    path('prestamos/create/', views.PrestamoCreateView.as_view(), name='prestamo_create'),
    path('prestamos/<int:pk>/update/', views.PrestamoUpdateView.as_view(), name='prestamo_update'),
    path('prestamos/<int:pk>/anular/', views.prestamo_anular, name='prestamo_anular'),
    path('prestamos/cuota/<int:cuota_id>/pagar/', views.registrar_pago_cuota, name='registrar_pago_cuota'),
    path('prestamos/exportar/excel/', views.exportar_prestamos_excel, name='exportar_prestamos_excel'),
    path('prestamos/<int:prestamo_id>/exportar/pdf/', views.exportar_cronograma_pdf, name='exportar_cronograma_pdf'),
    path('prestamos/api/empleado/<int:pk>/', views.api_empleado_sueldo, name='api_empleado_sueldo'),
    path('prestamos/api/tipo-prestamo/<int:pk>/', views.api_tipo_prestamo_tasa, name='api_tipo_prestamo_tasa'),
]

