from django.urls import path
from . import views

# app_name = 'purchasing' habilita {% url 'purchasing:purchase_list' %}, etc.
app_name = 'purchasing'

urlpatterns = [
    path('', views.purchase_list, name='purchase_list'),
    path('create/', views.purchase_create, name='purchase_create'),
    path('<int:pk>/', views.purchase_detail, name='purchase_detail'),
    path('<int:pk>/pdf/', views.purchase_pdf, name='purchase_pdf'),
    path('<int:pk>/delete/', views.purchase_delete, name='purchase_delete'),
    path('report/', views.purchase_report, name='purchase_report'),
]