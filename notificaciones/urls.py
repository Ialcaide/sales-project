from django.urls import path

from . import views

app_name = 'notificaciones'

urlpatterns = [
    path('', views.notificacion_list, name='notificacion_list'),
    path('<int:pk>/marcar-leida/', views.notificacion_marcar_leida, name='notificacion_marcar_leida'),
    path('marcar-todas-leidas/', views.notificacion_marcar_todas_leidas, name='notificacion_marcar_todas_leidas'),
]
