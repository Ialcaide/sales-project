from django.urls import path
from . import views

app_name = 'caja'

urlpatterns = [
    path('abrir/', views.caja_abrir, name='caja_abrir'),
    path('historial/', views.caja_historial, name='caja_historial'),
    path('<int:pk>/', views.caja_detalle, name='caja_detalle'),
    path('<int:pk>/cerrar/', views.caja_cerrar, name='caja_cerrar'),
    path('<int:pk>/movimiento/nuevo/', views.movimiento_crear, name='movimiento_crear'),
]
