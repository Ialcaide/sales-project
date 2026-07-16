from django.urls import path

from . import views

app_name = 'paypal_pagos'

urlpatterns = [
    path('return/', views.paypal_return, name='paypal_return'),
    path('cancel/', views.paypal_cancel, name='paypal_cancel'),
    path('webhook/', views.paypal_webhook, name='paypal_webhook'),
]
