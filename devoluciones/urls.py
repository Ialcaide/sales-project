from django.urls import path
from . import views

app_name = 'devoluciones'

urlpatterns = [
    path('crear/<int:factura_id>/', views.devolucion_create, name='devolucion_create'),
    path('historial/', views.devolucion_list, name='devolucion_list'),
    path('<int:pk>/', views.devolucion_detail, name='devolucion_detail'),
]
