"""
URL configuration for config project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.0/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path, re_path, include
from django.conf import settings
from django.views.static import serve as static_serve

# Este es el "urls.py raíz": el ÚNICO archivo que Django lee primero para
# cualquier request (ROOT_URLCONF en settings.py apunta acá). Cada
# include(...) delega el resto de la URL al urls.py de esa app — ej. una
# petición a /products/create/ entra acá, ve que no matchea nada de arriba,
# cae en include('billing.urls') (prefijo '' = billing entero vive en la
# raíz), y billing/urls.py resuelve 'products/create/' con su propia lista.
#
# ORDEN IMPORTA: Django prueba cada path() de arriba hacia abajo y se queda
# con el PRIMERO que matchea. Por eso 'home.urls' va antes que 'billing.urls'
# (ambas registran '' — ver la nota en billing/urls.py sobre la ruta muerta).
urlpatterns = [
    path('admin/', admin.site.urls),                            # panel nativo de Django
    path('accounts/', include('django.contrib.auth.urls')),      # login/logout/reset que trae Django de fábrica
    path('security/', include('security.urls')),                 # /security/... usuarios, roles, permisos
    path('purchases/', include('purchasing.urls')),               # /purchases/... compras
    path('pagos/', include('pagos.urls')),                         # /pagos/... cuentas por pagar (pagos a proveedores)
    path('cobros/', include('cobros.urls')),                       # /cobros/... cuentas por cobrar (cobros a clientes)
    path('caja/', include('caja.urls')),                           # /caja/... apertura/cierre/movimientos de caja
    path('devoluciones/', include('devoluciones.urls')),           # /devoluciones/... devoluciones de ventas
    path('notificaciones/', include('notificaciones.urls')),       # /notificaciones/... campanita, historial
    path('reportes/', include('reportes.urls')),                   # /reportes/... ventas, compras, inventario, caja
    path('configuracion/', include('configuracion.urls')),         # /configuracion/... IVA, empresa, umbrales
    path('paypal/', include('paypal_pagos.urls')),                  # /paypal/... return/cancel/webhook
    path('facturacion-electronica/', include('facturacion_electronica.urls')),  # SRI: reintentar, autorización, RIDE
    path('rrhh/', include('RRHumanos.urls')),                       # RRHH / Préstamos
    path('', include('home.urls')),                                # / -> dashboard (debe ir ANTES que billing.urls)
    path('', include('billing.urls')),                             # /products/, /customers/, /invoices/, etc.
    # django.conf.urls.static.static() (el helper "de manual" de Django)
    # solo sirve MEDIA_ROOT cuando DEBUG=True; acá se sirve explícito y sin
    # esa condición para que las imágenes de producto también se vean en
    # producción (Render), donde DEBUG está en False.
    re_path(r'^media/(?P<path>.*)$', static_serve, {'document_root': settings.MEDIA_ROOT}),
]