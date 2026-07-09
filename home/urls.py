from django.urls import path
from . import views

# Sin app_name: esta app no usa namespace, así que sus URLs se referencian
# directo como {% url 'home' %} (no 'home:home'). Se incluye SIN prefijo en
# config/urls.py (path('', include('home.urls'))), por eso 'home' cae justo
# en la raíz del sitio '/'.
urlpatterns = [
    path('', views.home, name='home'),
    path('home/', views.home, name='home_alias'),  # mismo dashboard, accesible también en /home/
]