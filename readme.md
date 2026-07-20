# Sistema de Ventas y Facturación — TecnoStock S.A.
activar entorno de sri..\venvsales\Scripts\uvicorn main:app --host 127.0.0.1 --port 8002 --reload


Sistema web desarrollado con **Django 6.0** para gestionar el ciclo completo de ventas de una empresa: marcas, grupos de productos, proveedores, productos, clientes, facturación (con pago en efectivo, tarjeta o **PayPal real**), compras, cuentas por cobrar/pagar, caja, devoluciones, **facturación electrónica ante el SRI (Ecuador)**, notificaciones internas, reportes, y un módulo completo de **seguridad** (usuarios, roles y permisos reales, recuperación de credenciales, notificaciones por correo y WhatsApp).

Desde la versión actual, el sistema son **dos servidores separados que corren al mismo tiempo**:

1. **El proyecto Django principal** (esta carpeta) — todo el negocio: ventas, compras, caja, usuarios, etc.
2. **`sri_facturacion_service/`** — un microservicio **FastAPI independiente** (carpeta hermana, propio venv/BD/`.env`) que se encarga SOLO de hablar con el SRI (generar, firmar y enviar comprobantes electrónicos). El proyecto principal le pide todo por HTTP; si este servicio está apagado, el sistema principal sigue funcionando igual (la venta no se bloquea, solo no se genera el comprobante SRI en ese momento).

Este documento está pensado para que puedas **entender y activar cada parte del sistema** siguiendo el mismo patrón que ya usa el proyecto.

---

## Tabla de contenidos

- [Requisitos previos](#requisitos-previos)
- [Instalación paso a paso (proyecto principal)](#instalación-paso-a-paso-proyecto-principal)
- [Instalación del microservicio de facturación electrónica (SRI)](#instalación-del-microservicio-de-facturación-electrónica-sri)
- [Cómo arrancar todo el sistema](#cómo-arrancar-todo-el-sistema)
- [Variables de entorno (.env)](#variables-de-entorno-env)
- [Estructura del proyecto](#estructura-del-proyecto)
- [Cómo funciona el sistema (arquitectura general)](#cómo-funciona-el-sistema-arquitectura-general)
- [Apps del proyecto](#apps-del-proyecto)
- [Sistema de Roles y Permisos](#sistema-de-roles-y-permisos)
- [Notificaciones (Email y WhatsApp)](#notificaciones-email-y-whatsapp)
- [Facturación electrónica (SRI — Ecuador)](#facturación-electrónica-sri--ecuador)
- [Pagos con PayPal](#pagos-con-paypal)
- [Formas de pago del sistema](#formas-de-pago-del-sistema)
- [Modelos de datos](#modelos-de-datos)
- [Funcionalidades](#funcionalidades)
- [URLs del sistema](#urls-del-sistema)
- [Carpeta shared](#carpeta-shared)
- [Cómo crear un CRUD desde cero (guía para principiantes)](#cómo-crear-un-crud-desde-cero-guía-para-principiantes)
- [Guía de métodos y campos útiles en Forms](#guía-de-métodos-y-campos-útiles-en-forms)
- [Exportación PDF y Excel](#exportación-pdf-y-excel)
- [Django ORM](#django-orm)
- [Credenciales de acceso](#credenciales-de-acceso)
- [Tecnologías utilizadas](#tecnologías-utilizadas)

---

## Requisitos previos

Antes de instalar el proyecto necesitas tener instalado:

- **Python 3.10 o superior** — descargar desde https://www.python.org/downloads/
  - Durante la instalación marcar la opción **"Add Python to PATH"**
- **Git** (opcional) — https://git-scm.com/

Verificar que Python esté instalado:
```
python --version
```

---

## Instalación paso a paso (proyecto principal)

### Paso 1 — Copiar el proyecto

Copia la carpeta del proyecto a tu computadora. La estructura debe verse así (resumida — ver [Estructura del proyecto](#estructura-del-proyecto) para el detalle completo):

```
sales_project/                        ← raíz del repositorio
    manage.py                         ← proyecto Django principal
    requirements.txt
    billing/  purchasing/  security/  home/  shared/  config/
    pagos/  cobros/  caja/  devoluciones/  notificaciones/  reportes/
    configuracion/  paypal_pagos/  facturacion_electronica/
    templates/  media/
    sri_facturacion_service/          ← microservicio FastAPI (proyecto aparte, ver más abajo)
```

### Paso 2 — Abrir terminal en la carpeta del proyecto

```
cd ruta\a\tu\proyecto\sales_project
```

Verificar que estás en la carpeta correcta (debe aparecer `manage.py`):
```
dir
```

### Paso 3 — Crear el entorno virtual

El entorno virtual aísla las dependencias del proyecto de las del sistema. **Este mismo entorno (`venvsales`) se reutiliza también para el microservicio de facturación electrónica** — no hace falta crear uno segundo.

```
python -m venv venvsales
```

> ⚠️ **Un entorno virtual no es "movible".** Si más adelante copiás o movés toda la carpeta del proyecto a otra ubicación (ej. de `Descargas` a `Documentos`), **no muevas `venvsales` con él pensando que va a seguir funcionando** — los scripts `activate` quedan con la ruta vieja grabada adentro y activan un Python que apunta al lugar original. Si eso pasa, lo más simple es borrar esa carpeta `venvsales` y crearla de nuevo (Paso 3) en la ubicación definitiva.

### Paso 4 — Activar el entorno virtual

**En CMD (Windows):**
```
venvsales\Scripts\activate
```

**En PowerShell (Windows):**
```
.\venvsales\Scripts\Activate.ps1
```

Si PowerShell da error de permisos, ejecutar primero:
```
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

Cuando el entorno está activo, verás `(venvsales)` al inicio del prompt.

> **IMPORTANTE:** El entorno virtual debe estar activo en cada sesión nueva de terminal. Si activaste correctamente pero un comando como `python` o `uvicorn` sigue sin reconocerse, corré `where python` y confirmá que la ruta que te devuelve es la de **este** `venvsales` (no una copia vieja en otra carpeta) — ver la advertencia del Paso 3.

### Paso 5 — Instalar dependencias

```
pip install -r requirements.txt
```

| Paquete | Para qué sirve |
|---|---|
| Django | Framework principal |
| Pillow | Manejo de imágenes en productos |
| openpyxl | Exportación a Excel |
| reportlab | Exportación a PDF |
| python-barcode | Códigos de barra en productos y comprobantes |
| requests | Cliente HTTP — habla con PayPal y con el microservicio de facturación SRI |
| PyJWT | Tokens usados por el flujo de seguridad |
| twilio | Envío de WhatsApp |
| whitenoise | Sirve archivos estáticos/media en producción |
| django-extensions | Shell plus con SQL |
| gunicorn | Servidor WSGI para producción (Render) |

> Nota: `cryptography`, `lxml`, `zeep` y `signxml` (firma electrónica y SOAP con el SRI) **ya no son dependencias de este proyecto** — esa lógica vive ahora en `sri_facturacion_service/`, que tiene su propio `requirements.txt` (ver la sección siguiente).

### Paso 6 — Configurar el archivo `.env`

Ver la sección [Variables de entorno](#variables-de-entorno-env) más abajo. Sin esto, el sistema funciona igual, pero **no podrá enviar correos, WhatsApp, cobrar con PayPal, ni hablarle al microservicio de facturación SRI**.

### Paso 7 — Aplicar migraciones

```
python manage.py migrate
```

### Paso 8 — Crear los roles del sistema

El sistema viene con un comando que crea automáticamente los 3 roles (Administrador, Vendedor, Analista de Compras) con sus permisos correctos:

```
python manage.py setup_roles
```

> Puedes volver a correr este comando cuando quieras "resetear" los permisos de los roles a su configuración original — es seguro, no borra usuarios ni datos, solo sincroniza permisos.

### Paso 9 — Crear superusuario (administrador)

```
python manage.py createsuperuser
```

### Paso 10 — Ejecutar el servidor

```
python manage.py runserver
```

Abrir en el navegador: `http://127.0.0.1:8000/`

Para detener el servidor: `Ctrl + C`

> Esto arranca **solo** el proyecto principal. Para que la facturación electrónica SRI funcione también necesitás el microservicio corriendo al mismo tiempo — ver la sección siguiente.

---

## Instalación del microservicio de facturación electrónica (SRI)

`sri_facturacion_service/` es un proyecto **FastAPI independiente**, hermano de este (mismo repositorio, carpeta aparte). No es una app Django: no tiene `manage.py`, no usa el ORM de Django, y no comparte base de datos con el proyecto principal — se comunican únicamente por HTTP.

### Paso 1 — Instalar sus dependencias propias

Con el mismo `venvsales` ya activado (ver instalación del proyecto principal):

```
cd sri_facturacion_service
pip install -r requirements.txt
```

| Paquete | Para qué sirve |
|---|---|
| fastapi | Framework del microservicio |
| uvicorn | Servidor que ejecuta la app FastAPI |
| sqlmodel | ORM (SQLAlchemy + Pydantic) — guarda el estado de cada comprobante |
| pydantic / pydantic-settings | Validación del payload que manda el proyecto Django, y carga tipada del `.env` propio |
| lxml | Construcción y firma del XML del comprobante |
| cryptography | Lee el certificado `.p12` y firma criptográficamente el XML (XAdES-BES) |
| zeep | Cliente SOAP — envía el XML firmado a los web services del SRI |
| reportlab / python-barcode / Pillow | Generan el PDF del RIDE (representación impresa de la factura) al vuelo |
| python-dotenv | Carga el `.env` propio de este microservicio |
| pytest / httpx | Tests propios de este servicio |

### Paso 2 — Conseguir un certificado de firma electrónica (.p12)

Esto es responsabilidad del emisor real de las facturas (una empresa ecuatoriana), no del código:

1. Comprar/obtener un certificado de firma electrónica válido para facturación (ej. Security Data, Banco Central del Ecuador, u otra entidad certificadora autorizada por el SRI), en formato `.p12`/`.pfx`.
2. Copiar ese archivo a `sri_facturacion_service/certificados/` (la carpeta ya existe en el repo, vacía por seguridad).
3. Anotar la contraseña del certificado — la vas a necesitar en el `.env` de este servicio (Paso 3).

> Sin un certificado real configurado, el microservicio sigue arrancando y respondiendo normalmente — simplemente cada comprobante que se intente generar queda en estado `error` con el mensaje "No hay certificado configurado..." (ver [Facturación electrónica](#facturación-electrónica-sri--ecuador)).

### Paso 3 — Configurar su `.env` propio

Este `.env` es **distinto y separado** del `.env` del proyecto Django (vive dentro de `sri_facturacion_service/`, no en la raíz del repo):

```env
# Ruta al certificado (relativa a esta carpeta) y su contraseña.
SRI_CERTIFICADO_PATH=certificados/tu_certificado.p12
SRI_CERTIFICADO_PASSWORD=la-contraseña-del-certificado

# 'pruebas' = ambiente de certificación del SRI (celcer.sri.gob.ec), sin
# validez tributaria. 'produccion' = ambiente real (cel.sri.gob.ec).
SRI_AMBIENTE=pruebas

# Secreto compartido: debe ser EXACTAMENTE igual al valor de
# FACTURACION_ELECTRONICA_SERVICE_API_KEY en el .env del proyecto Django
# (ver la sección de variables de entorno más abajo).
API_KEY=elegí-una-cadena-larga-y-aleatoria

# Opcional — por defecto usa SQLite local, no hace falta tocarlo.
# DATABASE_URL=sqlite:///./db.sqlite3

DEBUG=True
```

### Paso 4 — Arrancar el microservicio

No usa `migrate` — las tablas se crean solas al arrancar (`init_db()` corre automáticamente). Desde dentro de `sri_facturacion_service/`, con el venv activo:

```
uvicorn main:app --reload --port 8002
```

> El puerto **8002** es el que el proyecto Django principal ya espera por defecto (`FACTURACION_ELECTRONICA_SERVICE_URL` en su `.env`, ver más abajo) — si arrancás el microservicio en otro puerto, tenés que actualizar esa variable para que coincidan.

Para confirmar que arrancó bien, abrí en el navegador `http://127.0.0.1:8002/` — debería responder algo como:
```json
{"servicio": "sri_facturacion_service", "estado": "ok", "ambiente_sri": "pruebas", "recepcion_wsdl": "...", "autorizacion_wsdl": "...", "debug": true}
```

### Correr sus tests

Desde dentro de `sri_facturacion_service/`:
```
pytest
```

---

## Cómo arrancar todo el sistema

Necesitás **dos terminales abiertas al mismo tiempo**, ambas con el mismo `venvsales` activado:

**Terminal 1 — proyecto principal (puerto 8000):**
```
cd sales_project
venvsales\Scripts\activate
python manage.py runserver
```

**Terminal 2 — microservicio de facturación SRI (puerto 8002):**
```
cd sales_project\sri_facturacion_service
..\venvsales\Scripts\activate
uvicorn main:app --reload --port 8002
```

Si el microservicio (Terminal 2) no está corriendo, el proyecto principal **sigue funcionando sin problema**: las ventas, compras, pagos, etc. se completan igual — solo que la factura queda sin comprobante electrónico SRI hasta que vuelvas a intentarlo con el microservicio activo (botón "Reintentar Generación" en el detalle de la factura).

---

## Variables de entorno (.env)

Hay **dos archivos `.env` distintos**, uno por proyecto — no se comparten ni se leen entre sí.

### `.env` del proyecto principal (en la raíz, junto a `manage.py`)

El proyecto lee automáticamente este archivo al arrancar (lo hace `config/settings.py`), **sin sobrescribir** variables reales del sistema operativo (así en Render, por ejemplo, siguen mandando las variables configuradas en su dashboard).

```env
# --- Gmail — envío de correos ---
# Debe ser una "Contraseña de aplicación" de Gmail (16 caracteres), no tu
# contraseña normal de la cuenta (se genera desde la configuración de
# seguridad de tu cuenta de Google, con la verificación en 2 pasos activada).
EMAIL_HOST_USER=tucorreo@gmail.com
EMAIL_HOST_PASSWORD=xxxxxxxxxxxxxxxx

# --- Twilio — envío de WhatsApp ---
# Se obtienen creando una cuenta gratuita en https://www.twilio.com/ y
# activando el "WhatsApp Sandbox".
TWILIO_ACCOUNT_SID=ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TWILIO_AUTH_TOKEN=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TWILIO_WHATSAPP_FROM=whatsapp:+14155238886

# --- Telegram — alertas internas del sistema (stock bajo, caja, vencimientos) ---
# TELEGRAM_BOT_TOKEN: lo da @BotFather en Telegram (hablale y usa /newbot).
# TELEGRAM_CHAT_ID: el ID del chat/grupo de administradores donde el bot
# debe avisar — se obtiene agregando el bot a ese chat, mandándole un
# mensaje cualquiera ahí, y visitando
# https://api.telegram.org/bot<TU_TOKEN>/getUpdates (el "chat":{"id":...}
# de la respuesta es el que va acá).
TELEGRAM_BOT_TOKEN=xxxxxxxxxx:xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TELEGRAM_CHAT_ID=-100xxxxxxxxxx

# --- PayPal — cobro real con PayPal ---
# Se obtienen creando una app en https://developer.paypal.com/ (dashboard
# de desarrolladores). Hay credenciales de Sandbox (pruebas) y de Live
# (dinero real) — usá las de Sandbox mientras estés probando.
PAYPAL_CLIENT_ID=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
PAYPAL_CLIENT_SECRET=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
PAYPAL_MODE=sandbox
# Opcional pero recomendado: se obtiene al registrar el webhook (apuntando
# a https://tu-dominio/paypal/webhook/) en el mismo dashboard de PayPal.
# Sin esto, las notificaciones automáticas de PayPal se rechazan (el pago
# igual se confirma por el retorno normal del navegador).
PAYPAL_WEBHOOK_ID=

# --- Facturación electrónica SRI — cómo hablarle al microservicio ---
# El certificado .p12 y su contraseña YA NO se configuran acá — viven en
# sri_facturacion_service/.env (ver la sección de instalación de ese
# servicio). Acá solo se configura cómo contactarlo:
FACTURACION_ELECTRONICA_SERVICE_URL=http://localhost:8002
# Debe coincidir EXACTO con el API_KEY del .env de sri_facturacion_service/.
FACTURACION_ELECTRONICA_SERVICE_API_KEY=elegí-una-cadena-larga-y-aleatoria
# Opcional (default 10 segundos).
FACTURACION_ELECTRONICA_SERVICE_TIMEOUT=10
# Clave que un sistema EXTERNO debe mandar en el header X-API-Key para
# consultar la API pública de verificación de comprobantes de este
# proyecto (/facturacion-electronica/api/verificar/). No confundir con la
# de arriba: esta protege a este proyecto, la de arriba es la que este
# proyecto manda hacia el microservicio.
SRI_VERIFICACION_API_KEY=otra-cadena-larga-y-aleatoria-distinta

# --- URL pública real del sistema ---
# Para que los links de los correos/WhatsApp, y las URLs de retorno de
# PayPal, funcionen sin importar si estás corriendo en tu PC o en producción.
SITE_URL=https://sales-project-dxoy.onrender.com
```

Este archivo **nunca se sube a git** (ya está en `.gitignore`). Si no lo creas, el sistema sigue funcionando normalmente — solo que se omiten silenciosamente el envío de correo/WhatsApp, el cobro con PayPal, y la consulta al microservicio SRI (quedan registrados como advertencia en la consola del servidor en vez de fallar).

### `.env` del microservicio (`sri_facturacion_service/.env`)

Ver el detalle completo en [Instalación del microservicio — Paso 3](#instalación-del-microservicio-de-facturación-electrónica-sri). Resumen de sus variables: `SRI_CERTIFICADO_PATH`, `SRI_CERTIFICADO_PASSWORD`, `SRI_AMBIENTE` (`pruebas`/`produccion`), `API_KEY` (debe coincidir con `FACTURACION_ELECTRONICA_SERVICE_API_KEY` de arriba), `DATABASE_URL` (opcional), `DEBUG`. Este archivo también está cubierto por el `.gitignore` de la raíz (el patrón `.env` sin `/` se aplica a cualquier subcarpeta), igual que cualquier `.p12`/`.pfx` que copies en `certificados/`.

---

## Estructura del proyecto

```
sales_project/
│
├── manage.py                     # Script principal de administración Django
├── requirements.txt               # Dependencias del proyecto principal
├── dbventas.sqlite3               # Base de datos SQLite (se genera automáticamente)
├── .env                           # Variables de entorno del proyecto principal (no versionado)
│
├── config/                        # Configuración principal del proyecto Django
│   ├── settings.py                # BD, apps, middleware, email, twilio, paypal, microservicio SRI
│   ├── urls.py                    # URLs raíz: reparte tráfico a cada app
│   └── asgi.py / wsgi.py          # Puntos de entrada del servidor
│
├── billing/                       # Catálogo, clientes y facturación (venta + 3 formas de pago)
├── purchasing/                    # Compras a proveedores (sube inventario)
├── pagos/                         # Cuentas por pagar — abonos a compras a crédito
├── cobros/                        # Cuentas por cobrar — abonos a facturas a crédito (incl. PayPal)
├── caja/                          # Apertura/cierre/arqueo de caja por usuario
├── devoluciones/                  # Devoluciones de ventas (repone stock, ajusta factura)
├── paypal_pagos/                  # Integración real con la API de PayPal (Sandbox/Live)
├── facturacion_electronica/       # Cliente HTTP hacia sri_facturacion_service (ver más abajo)
├── notificaciones/                # Alertas internas del sistema (campanita)
├── reportes/                      # Reportes de ventas/compras/inventario/caja (sin modelos propios)
├── configuracion/                 # Configuración global del sistema (singleton: IVA, empresa, SRI...)
├── security/                      # Usuarios, roles, permisos, recuperación de acceso
├── home/                          # Dashboard según el rol del usuario
├── shared/                        # Código reutilizable entre todas las apps (no es una app Django)
│
├── templates/                     # Plantillas globales (fuera de cada app)
│   ├── registration/               # login.html, password_reset_confirm.html, etc.
│   └── emails/                     # Plantillas HTML de todos los correos (ver Notificaciones)
│
└── media/                         # Archivos subidos por usuarios (imágenes, adjuntos)

sri_facturacion_service/           # ← proyecto FastAPI INDEPENDIENTE, hermano del anterior
├── main.py                        # Rutas HTTP + autenticación por X-API-Key
├── services.py                    # Orquesta todo el flujo (reservar → armar → firmar → enviar → consultar)
├── models.py                      # SQLModel: ComprobanteElectronico, SecuencialSRI
├── schemas.py                     # Validación del payload de entrada (Pydantic)
├── config.py                      # Carga el .env propio (pydantic-settings)
├── database.py                    # Motor y sesión SQLite (o Postgres vía DATABASE_URL)
├── claveacceso.py                 # Genera la clave de acceso de 49 dígitos (aritmética pura)
├── firma.py                       # Firma XAdES-BES del XML con el certificado .p12
├── client.py                      # Cliente SOAP (zeep) contra los web services del SRI
├── xml_builder.py                 # Arma el XML del comprobante (esquema factura v2.1.0)
├── ride.py                        # Genera el PDF del RIDE al vuelo (reportlab + barcode)
├── requirements.txt                # Dependencias propias (FastAPI, no Django)
├── .env                            # Variables de entorno propias (no versionado)
├── certificados/                   # Certificado .p12 (no versionado)
├── db.sqlite3                      # Base de datos propia (no versionado)
└── test_*.py                       # Tests propios (pytest)
```

---

## Cómo funciona el sistema (arquitectura general)

Django organiza el código en **apps** (módulos independientes). Cada request HTTP sigue siempre el mismo camino:

```
Navegador → urls.py (¿qué vista corresponde a esta URL?)
          → views.py (lógica: lee/guarda datos, decide qué mostrar)
          → forms.py (valida los datos que envía el usuario, si aplica)
          → models.py (representa las tablas de la base de datos)
          → templates/*.html (arma el HTML que se envía de vuelta)
```

En este proyecto, `config/urls.py` es el punto de entrada: reparte cada URL a la app que corresponde:

```python
urlpatterns = [
    path('admin/', admin.site.urls),
    path('accounts/', include('django.contrib.auth.urls')),
    path('security/', include('security.urls')),
    path('purchases/', include('purchasing.urls')),
    path('pagos/', include('pagos.urls')),
    path('cobros/', include('cobros.urls')),
    path('caja/', include('caja.urls')),
    path('devoluciones/', include('devoluciones.urls')),
    path('notificaciones/', include('notificaciones.urls')),
    path('reportes/', include('reportes.urls')),
    path('configuracion/', include('configuracion.urls')),
    path('paypal/', include('paypal_pagos.urls')),
    path('facturacion-electronica/', include('facturacion_electronica.urls')),
    path('', include('home.urls')),
    path('', include('billing.urls')),
]
```

Cada app sigue el mismo patrón interno: **Modelo → Formulario → Vista → URL → Plantilla** (ver la guía completa en [Cómo crear un CRUD desde cero](#cómo-crear-un-crud-desde-cero-guía-para-principiantes)). Todo el acceso a la base de datos pasa por el **ORM** de Django — nunca se escribe SQL a mano en este proyecto.

### La segunda pieza: el microservicio

`sri_facturacion_service/` NO sigue este patrón — es FastAPI, no Django, y no tiene templates ni ORM de Django. Su única razón de ser es aislar la firma electrónica y la comunicación con el SRI en un servicio separado, reutilizable desde cualquier otro proyecto (no solo este), y que pueda desplegarse/reiniciarse/actualizarse de forma independiente. La comunicación entre ambos es siempre HTTP síncrono con autenticación por header `X-API-Key` — ver el detalle completo en [Facturación electrónica](#facturación-electrónica-sri--ecuador).

---

## Apps del proyecto

### config/
Carpeta de configuración principal (no es una app en sí misma).

- **`settings.py`** — base de datos, apps instaladas, middleware, templates, archivos media/estáticos, email (Gmail), WhatsApp (Twilio), PayPal, microservicio de facturación SRI, idioma (`es-ec`).
- **`urls.py`** — reparte las URLs raíz a cada app, y sirve `/media/` explícitamente (funciona en desarrollo **y** en producción).

### billing/
App principal del sistema. Gestiona catálogo, clientes y facturación.

- **`models.py`** — `Brand`, `ProductGroup`, `Supplier`, `Product`, `Customer`, `CustomerProfile`, `Invoice` (con `tipo_pago` contado/crédito, `forma_pago` efectivo/tarjeta/paypal, `estado` pendiente/pagada, `saldo`, datos de tarjeta informativos), `InvoiceDetail`.
- **`views.py`** — mezcla de FBV y CBV, todas protegidas con permisos reales. `_finalizar_venta()` es la función central que crea la factura, descuenta stock, dispara el comprobante SRI, registra el movimiento de caja y envía el correo de confirmación — la reutilizan tanto la venta de mostrador como el flujo de PayPal.
- **`export_mixins.py`** — `ExportMixin`, reutilizable para exportar cualquier queryset a Excel o PDF.

### purchasing/
App del módulo de compras. Reutiliza modelos de `billing` (`Supplier`, `Product`).

- **`models.py`** — `Purchase` (cabecera) y `PurchaseDetail` (líneas). Al confirmar una compra, sube el stock del producto y actualiza `last_cost`.

### pagos/ — cuentas por pagar (a proveedores)
Registra abonos a compras a crédito. Cada pago recalcula, dentro de una transacción (`select_for_update`), el saldo y estado de la `Purchase` asociada.

- **`PagoCompra`** — abono a una compra; `forma_pago` (efectivo/**tarjeta**/paypal — tarjeta y paypal son ambos informativos acá, sin ninguna integración real: pagarle a un proveedor de verdad por PayPal necesitaría la API de *Payouts*, distinta a la que ya usa el resto del sistema, y quedó fuera de alcance a propósito), `valor`, `observacion`, más `tarjeta_titular`/`tarjeta_cvv`/`tarjeta_expiracion` cuando la forma de pago es tarjeta. Efectivo y tarjeta exigen una `SesionCaja` abierta (solo efectivo genera `MovimientoCaja`). Al registrarse, envía un comprobante PDF por correo/WhatsApp al proveedor.
- **URLs** (`/pagos/`): `pendientes/`, `crear/<compra_id>/`, `historial/`, `<pk>/editar/`, `<pk>/eliminar/`, `<pk>/pdf/`.

### cobros/ — cuentas por cobrar (a clientes)
Espejo de `pagos` del lado de ventas: abonos a facturas a crédito, con el mismo patrón transaccional. Acá `forma_pago = paypal` sí puede corresponder a un cobro real capturado por `paypal_pagos`.

- **`CobroFactura`** — abono a una factura; `forma_pago` (efectivo/**tarjeta**/paypal — tarjeta se elige en este mismo formulario, igual que efectivo; paypal sigue siendo un botón/formulario separado que sí cobra de verdad, ver `cobro_paypal_iniciar`), `monto_recibido`, property `cambio` para cobros en efectivo, más `tarjeta_titular`/`tarjeta_cvv`/`tarjeta_expiracion` cuando la forma de pago es tarjeta. Efectivo y tarjeta exigen una `SesionCaja` abierta (solo efectivo genera `MovimientoCaja`).
- **URLs** (`/cobros/`): `pendientes/`, `crear/<factura_id>/`, `crear/<factura_id>/paypal/`, `historial/`, `<pk>/editar/`, `<pk>/eliminar/`, `<pk>/pdf/`.

### caja/ — control de caja
Maneja jornadas de caja por usuario: apertura con monto inicial, movimientos de ingreso/egreso, cierre con arqueo (comparación de lo contado contra lo esperado por el sistema).

- **`SesionCaja`** — jornada de un usuario; properties `total_ingresos`, `total_egresos`, `monto_esperado_cierre`, `diferencia`.
- **`MovimientoCaja`** — ingreso/egreso, opcionalmente ligado a la `Invoice`/`PagoCompra`/`CobroFactura` que lo generó.
- **URLs** (`/caja/`): `abrir/`, `historial/`, `<pk>/`, `<pk>/cerrar/`, `<pk>/movimiento/nuevo/`.

### devoluciones/ — devoluciones de ventas
Registra devoluciones (totales o parciales) sobre facturas ya emitidas: repone stock, reduce subtotal/tax/total/saldo de la factura, y genera un egreso en caja si la venta original fue en efectivo. **No envía ningún correo/WhatsApp al procesar una devolución** (a diferencia de la mayoría de las otras operaciones de dinero del sistema).

- **`DevolucionVenta`** (cabecera) + **`DevolucionDetalle`** (línea devuelta, valida no exceder lo disponible). Función `registrar_devolucion()` orquesta el efecto transaccional completo.
- **URLs** (`/devoluciones/`): `crear/<factura_id>/`, `historial/`, `<pk>/`.

### paypal_pagos/ — cobro real con PayPal
Ver la sección dedicada [Pagos con PayPal](#pagos-con-paypal).

### facturacion_electronica/ — cliente de la facturación SRI
Ver la sección dedicada [Facturación electrónica](#facturación-electrónica-sri--ecuador).

### notificaciones/ — alertas internas (campanita + Telegram)
Sistema de notificaciones **internas** dentro de la interfaz — no son correos ni WhatsApp. Cubre: stock bajo (también dispara un correo, ver la tabla en [Notificaciones](#notificaciones-email-y-whatsapp)), diferencia de caja al cierre, productos por vencer, y pagos pendientes por vencer. Las 4 además se mandan a un chat de Telegram, si está configurado (ver más abajo) — antes solo quedaban visibles adentro del sistema.

- **`Notificacion`** — tipo/nivel/mensaje/usuario (`null` = visible para todos con permiso)/url/leída/clave (evita duplicar la misma alerta mientras siga sin leerse).
- **`notificaciones/services.py`** — funciones que crean cada tipo de alerta, todas a través del helper interno `_crear_si_no_existe()`, que es el único punto donde se llama a `send_telegram_message()` (así las 4 alertas quedan cubiertas sin repetir esa llamada en cada una). `sincronizar_productos_por_vencer`/`sincronizar_pagos_pendientes` se ejecutan con el comando `python manage.py generar_notificaciones` (no hay cron/Celery configurado — hay que programarlo o correrlo a mano periódicamente).
- **URLs** (`/notificaciones/`): `` (lista), `<pk>/marcar-leida/`, `marcar-todas-leidas/`.

### reportes/ — reportes del negocio
Sin modelos propios: solo vistas que consultan datos de otras apps.

- **URLs** (`/reportes/`): `` (índice), `ventas/`, `compras/`, `inventario/`, `caja/`.

### configuracion/ — configuración global del sistema
Panel de configuración única (singleton, siempre `pk=1`, `ConfiguracionSistema.get_solo()`) para no tener valores hardcodeados: IVA, datos de la empresa, umbrales de stock/vencimiento, % de crédito, y los datos de numeración SRI que **no son secretos** (`sri_establecimiento`, `sri_punto_emision`, `sri_obligado_contabilidad`, `sri_nombre_comercial` — el certificado y su contraseña sí son secretos y viven en el `.env` del microservicio, nunca acá).

- **URLs** (`/configuracion/`): `` (editar).

### security/
App de seguridad: usuarios, roles, permisos y recuperación de acceso.

- **`models.py`** — `UserProfile`: perfil 1-a-1 con el `User` de Django, agrega `phone`.
- **`views.py`** — login personalizado, alta/edición/borrado de usuarios (solo administradores), gestión de roles y permisos, recuperación de credenciales por correo o WhatsApp, cambio de contraseña con código de verificación.
- **`management/commands/setup_roles.py`** — crea/sincroniza los 3 roles del sistema.

### home/
App pequeña que solo decide qué dashboard mostrar según el rol del usuario logueado.

### shared/
Código transversal reutilizado por cualquier app (no es una app Django registrada en `INSTALLED_APPS`, es un paquete de utilidades) — ver la sección dedicada más abajo.

---

## Sistema de Roles y Permisos

Este es el corazón de la seguridad del sistema. Usa el sistema de **permisos nativo de Django** (`django.contrib.auth`), no algo inventado desde cero.

### Los 3 conceptos clave

1. **`Permission`** — Django crea automáticamente 4 permisos por cada modelo: `add_x`, `change_x`, `delete_x`, `view_x` (ej. `billing.add_product`). Son las "casillas" que se marcan en Gestión de Permisos.
2. **`Group`** (= "Rol" en la interfaz) — un conjunto de permisos con un nombre (`Administrador`, `Vendedor`, `Analista de Compras`). Un usuario puede pertenecer a uno o varios grupos.
3. **`User`** — además de heredar los permisos de sus grupos, puede tener permisos **directos** asignados solo a él (`user.user_permissions`).

Django ya trae `user.has_perm('billing.add_product')`, que revisa automáticamente: ¿es superusuario? ¿tiene el permiso directo? ¿alguno de sus grupos lo tiene? Este proyecto se apoya 100% en ese método — **nunca hay que reinventar la comprobación de permisos**.

### Cómo se protege una vista

En vez de revisar el nombre del rol a mano (`if user.groups.filter(name='Administrador')`), las vistas usan permisos reales de `shared/mixins.py` y `shared/decorators.py`:

```python
# Vista basada en clase (CBV)
class ProductDeleteView(LoginRequiredMixin, PermissionRequiredRedirectMixin, DeleteView):
    model = Product
    permission_required = 'billing.delete_product'
    permission_redirect_url = '/products/'

# Vista basada en función (FBV)
@permission_required_redirect('billing.delete_brand', '/brands/')
def brand_delete(request, pk):
    ...
```

Si el usuario no tiene el permiso, se le redirige con un mensaje de error — nunca ve una pantalla de error cruda de Django.

### `setup_roles`: el punto de partida de los roles

`security/management/commands/setup_roles.py` define, en un diccionario `ROLES`, qué codenames de permiso tiene cada rol al crearse:

```python
ROLES = {
    'Administrador': '__all__',   # todos los permisos del sistema
    'Vendedor': ['view_customer', 'add_customer', ..., 'view_product'],
    'Analista de Compras': ['view_brand', 'add_brand', ..., 'add_purchase', ...],
}
```

Correr `python manage.py setup_roles` crea los grupos si no existen y sincroniza sus permisos. **Esto es solo el punto de partida** — después, un administrador puede ajustar los permisos de cada rol libremente desde la pantalla de Gestión de Permisos, y esos cambios se aplican de inmediato a todos los usuarios de ese rol.

### La pantalla de Gestión de Permisos (`/security/permissions/`)

- **Izquierda:** lista de Roles y buscador de Usuarios — se elige a quién se le va a editar los permisos.
- **Derecha:** un cuadro por cada modelo (Producto, Cliente, Factura, etc.) con casillas **Ver / Agregar / Editar / Eliminar**.
- Si estás viendo un **usuario**, los permisos que ya tiene por su rol aparecen marcados y bloqueados (🔒 *vía rol*) — no se pueden quitar ahí (para eso se edita el rol). Puedes marcar casillas **extra** para darle permisos individuales solo a él.
- El botón **"Dar acceso a todos los permisos"** (solo visible con un usuario seleccionado) le otorga de una vez todos los permisos del sistema de forma directa.
- Cualquier cambio se aplica de inmediato: si le quitas `delete_product` a un rol, todos sus usuarios pierden esa capacidad al instante, sin reiniciar el servidor ni tocar código.

---

## Notificaciones (Email y WhatsApp)

`shared/notifications.py` centraliza **todo** el envío — ninguna vista arma un correo o WhatsApp por su cuenta. Todas sus funciones son *best-effort*: si el envío falla (o si no configuraste el `.env`), registran una advertencia en la consola y devuelven `False`, para que el resto de la operación (crear la factura, el usuario, etc.) se complete igual.

### Funciones disponibles

| Función | Qué hace |
|---|---|
| `get_admin_recipients()` | Lista `(nombre, email)` de todos los usuarios activos con correo que son administradores — la usan todos los correos que avisan a un admin de un evento. |
| `send_credentials_email(to_email, subject, body, html_template=None, html_context=None)` | Correo simple. Sin `html_template` manda solo texto plano (comportamiento clásico); con `html_template` arma un correo con versión HTML + texto. |
| `send_email_with_attachment(...)` | Igual, con **un** archivo adjunto (ej. comprobante de pago). |
| `send_email_with_attachments(...)` | Igual, con **varios** adjuntos (ej. factura + RIDE + XML del SRI). |
| `send_whatsapp_message(phone, body)` | Envía WhatsApp vía Twilio. Sin credenciales configuradas, no intenta enviar. |

Cada correo con `html_template` recibe automáticamente (sin que cada llamado lo repita) el nombre de la empresa, la URL pública del sitio, el año actual y el correo de soporte — ver `_contexto_base()` dentro del mismo archivo.

### Plantillas HTML (`templates/emails/`)

Un layout compartido (`base_email.html`, con header degradado, tarjeta central y footer, todo con `<table>` y estilos inline para que se vea bien también en Outlook) más 5 partials reutilizables (`_button.html`, `_alert.html`, `_data_row.html`, `_divider.html`, `_pedido_stepper.html`) y **24 plantillas concretas**, una por tipo de correo.

### Qué evento dispara qué correo

| Evento | Plantilla | ¿WhatsApp también? |
|---|---|---|
| Se crea un usuario nuevo | `bienvenida.html` (al usuario, con sus credenciales) | Sí |
| Se crea un usuario nuevo | `nuevo_usuario_registrado.html` (aviso a cada admin) | No |
| Recuperar credenciales (canal correo) | `recuperar_password.html` | Alternativa por WhatsApp si se elige ese canal |
| Código para cambiar contraseña (Mi Perfil) | Solo texto plano, sin plantilla HTML | No |
| Contraseña actualizada (Mi Perfil) | `password_cambiada.html` | No |
| Se bloquea una cuenta | `cuenta_bloqueada.html` | Sí |
| Se desbloquea una cuenta | `cuenta_desbloqueada.html` | Sí |
| Cambia el rol de un usuario | `cambio_rol_usuario.html` | Sí |
| Otra edición de cuenta (datos/reseteo de contraseña por admin) | `actualizacion_cuenta.html` | Sí |
| Se registra un proveedor nuevo | `nuevo_proveedor_registrado.html` (a cada admin) | No |
| Se registra un cliente nuevo | `nuevo_cliente_registrado.html` (a cada admin) | No |
| Se finaliza una venta/factura | `confirmacion_compra.html` (factura + RIDE + XML SRI adjuntos si están listos) | Sí |
| Stock por debajo del mínimo | `inventario_bajo.html` (a cada admin, solo la primera vez) | No — pero sí a Telegram |
| Se registra una compra a proveedor | `compra_proveedor_registrada.html` (a cada admin) | No |
| Se paga a un proveedor | `pago_proveedor_realizado.html` (comprobante PDF al proveedor) | Sí |
| Se cobra/abona una factura | `confirmacion_pago.html` (comprobante PDF al cliente) | Sí |
| Diferencia de caja al cierre | — (solo notificación interna + Telegram, **sin correo**) | No — pero sí a Telegram |
| Producto por vencer / pago pendiente por vencer | — (solo notificación interna + Telegram, **sin correo**) | No — pero sí a Telegram |

### Plantillas ya diseñadas pero sin ningún evento conectado todavía

Estas 9 plantillas existen y se ven bien, pero **ningún código las dispara hoy** — quedaron listas para cuando se construya la funcionalidad que les corresponde:

- `verificacion_correo.html` — no hay auto-registro público de cuentas todavía.
- `nuevo_dispositivo.html` — no hay detección de dispositivo/IP nuevo en el login.
- `factura_disponible.html` — la factura ya se manda adjunta en `confirmacion_compra.html`, no hay un aviso separado.
- `pedido_recibido.html` / `pedido_enviado.html` / `pedido_entregado.html` — no existe todavía un flujo de "pedido" con esos 3 estados.
- `notificacion_general.html` — plantilla comodín para futuros avisos genéricos.
- `error_sistema.html` — no hay un manejador de errores que dispare un aviso a soporte.
- `reembolso_realizado.html` — `devoluciones/` no envía ningún correo todavía al procesar una devolución.

### WhatsApp (Twilio)

`send_whatsapp_message(phone, body)` usa el SDK de Twilio para mandar un mensaje de texto simple a `whatsapp:{phone}`. Sin adjuntos (la API simple de Twilio no soporta archivos sin alojarlos antes en una URL pública). Se obtienen credenciales gratuitas de prueba en https://www.twilio.com/ activando el "WhatsApp Sandbox".

El link que reciben los correos/WhatsApp siempre apunta a `settings.SITE_URL` (la URL pública real), nunca a `localhost`, sin importar desde dónde el administrador esté operando.

### Telegram (alertas internas del sistema)

A diferencia de correo/WhatsApp (que van a la persona específica del evento — un cliente, un proveedor, un usuario), Telegram acá se usa para **un solo chat fijo de administradores**: `send_telegram_message(body)` en `shared/notifications.py` manda el mensaje a un único `TELEGRAM_CHAT_ID` configurado en el `.env`, usando la API HTTP de bots de Telegram (`https://api.telegram.org/bot<token>/sendMessage`) — no hace falta ninguna librería nueva, se usa `requests` (que el proyecto ya tenía).

Está conectado a dos niveles distintos de aviso:

1. **Las 4 alertas internas curadas** que antes solo se veían en la campanita del sistema (`notificaciones/services.py`): stock bajo, diferencia de caja al cierre, producto por vencer, y pago pendiente por vencer — las 4 pasan por el mismo helper interno `_crear_si_no_existe()`.
2. **Un registro de actividad amplio** (`notificaciones/signals.py`), conectado una sola vez en `NotificacionesConfig.ready()`, que escucha los signals `post_save`/`post_delete` de Django para **cualquier alta, edición o borrado** en las apps de negocio del sistema (`billing`, `purchasing`, `security`, `pagos`, `cobros`, `caja`, `devoluciones`, `configuracion`, `paypal_pagos`, `facturacion_electronica`, más `User`/`Group` de `auth`), y el signal `user_logged_in` para avisar quién inició sesión y cuándo. Esto es intencionalmente amplio ("factura creada", "nuevo usuario", "se editó un proveedor", etc.) — **no** crea entradas en la campanita (esa sigue siendo solo para las 4 alertas accionables de arriba), solo manda a Telegram. Se excluyen `auth.Permission` (Django la reescribe en cada `migrate`, es ruido) y el propio modelo `Notificacion` (para no generar un aviso de "se creó una notificación" por cada alerta ya avisada).

> Con esto activado vas a recibir bastantes mensajes — cada venta, cada compra, cada alta de cliente/proveedor, cada login, etc. Si en algún momento resulta demasiado, la lista de apps rastreadas está en `notificaciones/signals.py -> _APPS_RASTREADAS` (quitar una app de ahí deja de avisar sus cambios).

**Cómo activarlo:**
1. Hablar con [@BotFather](https://t.me/BotFather) en Telegram y crear un bot nuevo con `/newbot` — te da un **token**.
2. Agregar ese bot al chat o grupo donde quieras recibir los avisos (puede ser un chat personal con el bot, o un grupo con varios administradores).
3. Mandarle cualquier mensaje al bot en ese chat, y después visitar `https://api.telegram.org/bot<TU_TOKEN>/getUpdates` en el navegador — ahí aparece el **Chat ID** (`"chat":{"id": ...}`) que hay que copiar.
4. Completar `TELEGRAM_BOT_TOKEN` y `TELEGRAM_CHAT_ID` en el `.env` del proyecto principal (ver [Variables de entorno](#variables-de-entorno-env)).

Sin estas dos variables configuradas, el sistema sigue funcionando exactamente igual — `send_telegram_message` solo registra una advertencia y no manda nada (mismo criterio best-effort que el resto de este archivo).

---

## Facturación electrónica (SRI — Ecuador)

Genera, firma y envía al SRI el comprobante electrónico de cada factura, y permite descargar su XML y su RIDE (representación impresa). Es **best-effort**: un problema acá (SRI caído, certificado mal configurado, microservicio apagado) nunca revierte ni bloquea la venta ya completada — el criterio es el mismo que para correo/WhatsApp.

### Los dos lados

| | `facturacion_electronica/` (Django) | `sri_facturacion_service/` (FastAPI) |
|---|---|---|
| Rol | Cliente HTTP — traduce `Invoice` al formato genérico y llama al microservicio | Hace todo el trabajo real: arma el XML, lo firma, lo envía al SRI, consulta autorización, genera el RIDE |
| Base de datos | `ComprobanteElectronico` local, espejo de lo que devuelve el microservicio | `ComprobanteElectronico` propio, con el JSON completo del pedido y los 3 XML |
| ¿Conoce certificados/firma? | No, nunca | Sí, es el único que los toca |

### Flujo paso a paso (dentro del microservicio)

1. **Reservar secuencial y clave de acceso** — un contador (`SecuencialSRI`) estrictamente incremental por establecimiento + punto de emisión + tipo de comprobante (el SRI exige numeración correlativa sin huecos). El **ambiente** (pruebas/producción) lo decide siempre la configuración propia del microservicio (`SRI_AMBIENTE` de su `.env`), nunca el proyecto Django — así la clave de acceso nunca queda codificada con un ambiente distinto al que realmente se usó para enviarla.
2. **Armar el XML** (esquema `factura` v2.1.0 del SRI) a partir de un payload genérico (emisor, comprador, líneas, forma de pago, totales) — el microservicio no conoce el modelo `Invoice` de Django, solo este formato genérico.
3. **Firmar XAdES-BES** con el certificado `.p12` (`cryptography` + `lxml`) — si el certificado no está configurado o la contraseña es incorrecta, el comprobante queda en estado `error` con el motivo, sin romper nada más.
4. **Enviar por SOAP** (librería `zeep`) al web service de recepción del SRI (`pruebas`: `celcer.sri.gob.ec`; `producción`: `cel.sri.gob.ec`). El SRI responde `RECIBIDA` o `DEVUELTA` (con los mensajes de error si rechazó el XML).
5. **Consultar autorización** — si quedó `RECIBIDA`, se consulta automáticamente al SRI si ya lo autorizó. Puede volver `AUTORIZADO`, `NO AUTORIZADO`, o `EN PROCESO` (para reintentar la consulta más tarde con el botón "Consultar Autorización").
6. **RIDE** — no se guarda un PDF; se genera al vuelo cada vez que se pide, a partir del JSON del pedido original guardado en el comprobante.

Estados posibles de un comprobante: `generado` → `firmado` → `enviado`/`recibida` → `autorizado` / `no_autorizado` / `devuelta` / `error` / `en_proceso`.

### Dónde se dispara

`billing/views.py` → `_finalizar_venta()` llama a `generar_y_enviar_comprobante(invoice)` justo después de calcular los totales definitivos de la venta, antes de registrar el movimiento de caja y enviar el correo de confirmación (que adjunta el RIDE/XML si ya están listos en ese momento).

### Qué ve el usuario (`invoice_detail.html`)

Un badge con el estado (verde = autorizado, rojo = error/no autorizado/devuelta, gris = en trámite), la clave de acceso (con botón de copiar), el número de autorización si existe, y el último mensaje de error si lo hay. Botones: **Descargar RIDE**, **Descargar XML**, **Consultar en el SRI** (enlace externo al portal público, solo en producción), **Consultar Autorización** (mientras esté en trámite), y **Reintentar Generación** (si quedó en error/devuelta/no autorizado).

### Instalación y variables de entorno

Ver [Instalación del microservicio de facturación electrónica](#instalación-del-microservicio-de-facturación-electrónica-sri) y la sección [Variables de entorno](#variables-de-entorno-env) — ahí está el detalle completo de cómo activarlo, qué `.env` necesita cada lado, y en qué puerto corre.

### Limitaciones honestas (documentadas en el propio código)

- Solo soporta el comprobante **factura** (código SRI `01`) — no notas de crédito/débito, guías de remisión, ni retenciones.
- No soporta ICE, IRBPNR, subsidio de combustibles, ni líneas exentas/no objeto de IVA (siempre van en $0.00).
- La firma XAdES-BES se verificó criptográficamente (carga el certificado y firma con la clave correcta), pero **no se probó una aceptación real contra el ambiente de producción del SRI** en este entorno de desarrollo — antes de emitir facturas reales, hacé una prueba real en el ambiente de `pruebas` del SRI con tu propio certificado.

---

## Pagos con PayPal

`paypal_pagos/` conecta el sistema con la **API REST real de PayPal** (no un SDK oficial — un cliente propio hecho con `requests`, para evitar una dependencia pesada). Es la única forma de pago del sistema que de verdad mueve dinero a través de un tercero real.

### El modelo puente: `OrdenPaypal`

Como el pago con PayPal es asíncrono (el navegador sale del sitio hacia paypal.com y vuelve), hace falta un lugar donde guardar el estado mientras el cliente está pagando afuera. **La `Invoice` o el `CobroFactura` reales nunca se crean al iniciar el pago** — solo cuando PayPal confirma que el dinero se capturó de verdad. Si el cliente cancela o cierra la pestaña, no queda ninguna venta a medias.

Estados de una orden: `creada` → `capturada` / `cancelada` / `fallida`.

### Flujo paso a paso

1. El usuario elige "PayPal" como forma de pago (en una factura nueva, o para pagar/abonar una factura a crédito ya existente).
2. El servidor crea una orden real en PayPal (Orders API v2, `POST /v2/checkout/orders`) y guarda una `OrdenPaypal` en estado `creada`.
3. El servidor redirige al usuario al checkout real de **paypal.com** para que apruebe el pago con su cuenta.
4. Ahí pasa uno de dos caminos (no excluyentes, es un respaldo del otro):
   - **Retorno del navegador** (`/paypal/return/`): si el usuario aprueba, PayPal lo trae de vuelta al sitio; el servidor captura el pago (`POST /v2/checkout/orders/{id}/capture`) y, si quedó `COMPLETED`, recién ahí crea la `Invoice`/`CobroFactura` real.
   - **Webhook** (`/paypal/webhook/`): PayPal también manda una notificación servidor-a-servidor por si el usuario cierra la pestaña antes de volver. Esta ruta valida la firma de la notificación contra `PAYPAL_WEBHOOK_ID` antes de procesar nada.
5. **Cancelación** (`/paypal/cancel/`): si el usuario cancela en paypal.com, solo se marca la orden como `cancelada` — no hay nada que revertir porque nunca se creó nada real.

La confirmación es **idempotente**: si tanto el retorno del navegador como el webhook llegan a procesar la misma orden, solo se crea la factura/cobro una vez.

### Autenticación con PayPal

`obtener_access_token()` hace un OAuth2 `client_credentials` contra PayPal usando `PAYPAL_CLIENT_ID`/`PAYPAL_CLIENT_SECRET` como usuario/clave. El sistema apunta a `api-m.sandbox.paypal.com` o a `api-m.paypal.com` según `PAYPAL_MODE`.

### Cómo activarlo (conseguir credenciales reales)

1. Crear una cuenta en https://developer.paypal.com/ (podés usar tu cuenta normal de PayPal).
2. En el dashboard, crear una **App** — te da un `Client ID` y un `Client Secret` de **Sandbox** (para pruebas, con dinero ficticio) y otro par para **Live** (dinero real).
3. Copiar esas credenciales al `.env` del proyecto principal: `PAYPAL_CLIENT_ID`, `PAYPAL_CLIENT_SECRET`, y `PAYPAL_MODE=sandbox` (o `live` cuando el negocio esté listo para cobrar de verdad).
4. **Opcional pero recomendado** — registrar un webhook en el mismo dashboard apuntando a `https://tu-dominio-público/paypal/webhook/`, y copiar el `Webhook ID` generado a `PAYPAL_WEBHOOK_ID` en el `.env`. Sin esto, el sistema sigue funcionando con el retorno normal del navegador (paso 4 de arriba), pero pierde el respaldo del webhook si el usuario cierra la pestaña antes de volver.

> En Sandbox, PayPal te da cuentas de prueba (comprador y vendedor) con dinero ficticio para probar el flujo completo sin arriesgar dinero real — se gestionan desde el mismo dashboard de desarrolladores.

---

## Formas de pago del sistema

El sistema ofrece hasta 3 formas de pago en los 3 lugares donde de verdad se paga o se cobra dinero — crear una factura (`billing`), pagarle a un proveedor (`pagos`) y cobrar una factura a crédito (`cobros`) — es importante entender que **solo una de ellas mueve dinero de verdad a través de un tercero**:

| Forma de pago | ¿Pasarela real? | Qué pasa en el sistema |
|---|---|---|
| **Efectivo** | No aplica (dinero físico) | Se registra el monto recibido y el cambio; entra a la caja abierta del usuario. |
| **Tarjeta** | **No — es una simulación visual** | Una animación de tarjeta (con detección de marca Visa/Mastercard/Amex) y un modal de "Pasarela de Pago" simulan el cobro. El número de tarjeta **nunca se envía al servidor** (el campo no tiene `name`); se guardan titular, CVV/CVC y expiración, como constancia de que el cobro se hizo por un datáfono físico externo al sistema (guardar el CVV es una decisión consciente pese a ir contra PCI-DSS, documentada como tal en el código). No hay Stripe ni ningún procesador real integrado. Disponible en **facturas**, **pagos a proveedores** y **cobros a clientes** — en pagos/cobros exige una `SesionCaja` abierta igual que efectivo, pero nunca genera `MovimientoCaja`. |
| **PayPal** | **Solo en facturas y cobros — API real** | Ver [Pagos con PayPal](#pagos-con-paypal) arriba: se crea una orden real, el cliente paga en paypal.com, y la factura/cobro se genera solo tras la confirmación real de PayPal. **En "pagos" (pagarle a un proveedor) sigue siendo solo informativo** — pagar de verdad por PayPal a un tercero necesitaría la API de *Payouts*, distinta a la de *Orders/Checkout* que ya usa el resto del sistema, y quedó fuera de alcance a propósito. |

---

## Modelos de datos

### Brand (Marca)
| Campo | Tipo | Descripción |
|---|---|---|
| name | CharField(100, unique) | Nombre de la marca |
| description | TextField | Descripción opcional |
| is_active | BooleanField | Estado activo/inactivo |

### ProductGroup (Grupo de productos)
| Campo | Tipo | Descripción |
|---|---|---|
| name | CharField(100, unique) | Nombre del grupo |
| is_active | BooleanField | Estado |

### Supplier (Proveedor)
| Campo | Tipo | Descripción |
|---|---|---|
| name | CharField(200) | Nombre de la empresa |
| contact_name / email / phone / address | — | Datos de contacto |
| is_active | BooleanField | Estado |

### Product (Producto)
| Campo | Tipo | Descripción |
|---|---|---|
| name | CharField(200) | Nombre |
| brand | ForeignKey → Brand | Marca (PROTECT) |
| group | ForeignKey → ProductGroup | Grupo (PROTECT) |
| suppliers | ManyToManyField → Supplier | Proveedores |
| unit_price | DecimalField(12,2) | Precio de venta |
| last_cost | DecimalField(12,2) | Último costo de compra (lo actualiza el módulo de compras) |
| stock | IntegerField | Unidades en inventario |
| image | ImageField | Foto del producto (opcional) |
| is_active | BooleanField | Estado |

Propiedades: `inventory_value` (stock × precio) y `placeholder_image` (imagen SVG generada automáticamente con la inicial del producto, cuando no hay foto subida).

### Customer (Cliente)
| Campo | Tipo | Descripción |
|---|---|---|
| dni | CharField(13, unique) | Cédula/RUC validado con `validate_cedula_ec` |
| first_name / last_name | CharField | Nombres |
| email / phone / address | — | Datos de contacto |

### Invoice (Factura)
Cabecera con `subtotal`, `tax` (IVA) y `total` calculados, más `tipo_pago` (contado/crédito), `forma_pago` (efectivo/tarjeta/paypal — solo aplica a contado), `estado` (pendiente/pagada), `saldo`, `meses_credito`/`interes` (financiamiento), `monto_recibido` (efectivo), y datos informativos de tarjeta (`tarjeta_titular`, `tarjeta_cvv`, `tarjeta_expiracion` — nunca el número completo de la tarjeta). Relacionada 1-a-1 (opcional) con `ComprobanteElectronico` del SRI.

### Purchase (Compra)
Cabecera con `subtotal`/`tax`/`total`. Restricción de `document_number` único por `supplier`.

### ComprobanteElectronico (facturación SRI, lado Django)
Espejo local de lo que procesó el microservicio: `clave_acceso`, `estado`, los 3 XML, número/fecha de autorización, mensajes — ver [Facturación electrónica](#facturación-electrónica-sri--ecuador).

### OrdenPaypal
Puente entre "se creó una orden en PayPal" y "el pago se confirmó" — ver [Pagos con PayPal](#pagos-con-paypal).

### UserProfile (security)
| Campo | Tipo | Descripción |
|---|---|---|
| user | OneToOneField → User | El usuario de Django |
| phone | CharField(20) | Teléfono/WhatsApp, usado para notificaciones |

---

## Funcionalidades

### Autenticación y acceso
- Login personalizado (`/accounts/login/` o `/security/login/`), con recuperación de credenciales por correo/WhatsApp — **no hay auto-registro público**: los usuarios los crea un administrador con un rol asignado.
- Todas las vistas protegidas con `@login_required` / `LoginRequiredMixin`, y las de negocio además con permisos reales por rol.

### Dashboard
Pantalla distinta según el rol del usuario, con conteos y gráficos.

### Buscadores, filtros y paginación
Todos los listados tienen búsqueda y filtros que se mantienen al paginar (10 registros por página).

### Exportación
Botones PDF y Excel en cada listado, exportan exactamente lo que está filtrado en pantalla.

### Facturación dinámica
Precio autocompletado al elegir producto, cálculo en tiempo real de subtotal/IVA/total, validación de stock suficiente, baja de stock al confirmar, 3 formas de pago (ver arriba), y generación best-effort del comprobante electrónico SRI.

### Módulo de Compras
Productos filtrados por proveedor, sube el stock y actualiza `last_cost` al registrar la compra, reporte de costo promedio por producto.

### Cuentas por cobrar / pagar y Caja
Abonos parciales a facturas y compras a crédito (con comprobante PDF por correo/WhatsApp), y control de caja por jornada (apertura, movimientos, cierre con arqueo).

### Devoluciones
Devolución total o parcial de una venta, con reposición de stock y ajuste automático de la factura.

### Notificaciones internas
Alertas de stock bajo, productos por vencer, pagos pendientes por vencer, y diferencias de caja al cierre.

### Gestión de Usuarios, Roles y Permisos
Ver la sección [Sistema de Roles y Permisos](#sistema-de-roles-y-permisos).

---

## URLs del sistema

### Autenticación / Seguridad
| URL | Descripción |
|---|---|
| `/accounts/login/` o `/security/login/` | Iniciar sesión |
| `/accounts/logout/` | Cerrar sesión |
| `/security/recover/` | Recuperar credenciales (correo o WhatsApp) |
| `/security/users/` | Listado de usuarios (solo admin) |
| `/security/register/` | Crear usuario con rol (solo admin) |
| `/security/roles/` | Gestión de roles |
| `/security/permissions/` | Gestión de permisos por rol/usuario |
| `/admin/` | Panel nativo de Django |

### Billing
| URL | Descripción |
|---|---|
| `/` | Dashboard |
| `/brands/`, `/groups/`, `/suppliers/`, `/products/`, `/customers/`, `/invoices/` | Listado + `create/`, `<id>/`, `<id>/edit/`, `<id>/delete/` |

### Purchasing
| URL | Descripción |
|---|---|
| `/purchases/` | Listado de compras |
| `/purchases/create/` | Crear compra |
| `/purchases/<id>/` | Detalle |
| `/purchases/<id>/delete/` | Eliminar |
| `/purchases/report/` | Reporte de costos |

### Pagos y Cobros
| URL | Descripción |
|---|---|
| `/pagos/pendientes/` | Compras a crédito con saldo pendiente |
| `/pagos/crear/<compra_id>/` | Registrar abono a un proveedor |
| `/cobros/pendientes/` | Facturas a crédito con saldo pendiente |
| `/cobros/crear/<factura_id>/` | Registrar abono/cobro de un cliente |
| `/cobros/crear/<factura_id>/paypal/` | Cobrar el saldo con PayPal |

### Caja y Devoluciones
| URL | Descripción |
|---|---|
| `/caja/abrir/` | Abrir jornada de caja |
| `/caja/<pk>/cerrar/` | Cerrar con arqueo |
| `/devoluciones/crear/<factura_id>/` | Registrar devolución |

### PayPal
| URL | Descripción |
|---|---|
| `/paypal/return/` | Retorno del checkout de PayPal (confirma el pago) |
| `/paypal/cancel/` | Cancelación desde PayPal |
| `/paypal/webhook/` | Notificaciones servidor-a-servidor de PayPal |

### Facturación electrónica (SRI)
| URL | Descripción |
|---|---|
| `/facturacion-electronica/facturas/<invoice_id>/reintentar/` | Generar/reintentar el comprobante |
| `/facturacion-electronica/<pk>/consultar-autorizacion/` | Consultar autorización manualmente |
| `/facturacion-electronica/<pk>/xml/` | Descargar el XML |
| `/facturacion-electronica/<pk>/ride/` | Descargar el RIDE (PDF) |
| `/facturacion-electronica/api/verificar/` | API pública de verificación (por clave de acceso o `invoice_id`) |

### Notificaciones, Reportes y Configuración
| URL | Descripción |
|---|---|
| `/notificaciones/` | Lista de alertas internas |
| `/reportes/` | Índice de reportes (ventas, compras, inventario, caja) |
| `/configuracion/` | Configuración global del sistema |

---

## Carpeta shared

Código transversal, reutilizado por cualquier app.

### `mixins.py`
- **`StaffRequiredMixin`** — exige `is_staff=True`.
- **`GroupRequiredMixin`** — exige pertenecer a alguno de los grupos indicados (`group_required = [...]`). Los superusuarios siempre pasan.
- **`PermissionRequiredRedirectMixin`** — exige el permiso Django real (`has_perm`). Es el que deberías usar en vistas nuevas:
  ```python
  class MiModeloDeleteView(LoginRequiredMixin, PermissionRequiredRedirectMixin, DeleteView):
      model = MiModelo
      permission_required = 'app.delete_mimodelo'
      permission_redirect_url = '/mimodelo/'
  ```

### `decorators.py`
- **`@audit_action('NOMBRE')`** — registra en consola usuario, acción, método HTTP, ruta e IP.
- **`permission_required_redirect(perm, redirect_url='/')`** — versión para vistas por función:
  ```python
  @permission_required_redirect('app.add_mimodelo', '/mimodelo/')
  def mimodelo_create(request):
      ...
  ```

### `notifications.py`
Ver [Notificaciones](#notificaciones-email-y-whatsapp) para el detalle completo de sus 5 funciones.

### `validators.py`
- **`validate_cedula_ec`** — valida cédula ecuatoriana (10 dígitos) o RUC (13 dígitos) con el algoritmo oficial.
  ```python
  dni = models.CharField(max_length=13, validators=[validate_cedula_ec])
  ```

---

## Cómo crear un CRUD desde cero (guía para principiantes)

Esta guía asume que **nunca has tocado este proyecto** y explica, paso por paso y sin saltarse nada, cómo agregar un módulo nuevo completo. Vamos a construir un ejemplo real: **"Vendedores"** — una tabla para llevar el registro de cada vendedor de la empresa (nombre, comisión, zona, etc.).

> ⚠️ **Aclaración importante antes de empezar:** el sistema ya tiene un **rol** (permiso de acceso) llamado "Vendedor" que se usa para el login (ver [Sistema de Roles y Permisos](#sistema-de-roles-y-permisos)). Lo que vamos a crear acá es **otra cosa completamente distinta**: una tabla de negocio para *guardar datos sobre* los vendedores (como una ficha de empleado), no tiene nada que ver con quién puede entrar al sistema. Un "Vendedor" (rol) inicia sesión; un "Vendedor" (el modelo que vamos a crear) es un registro en una tabla, como lo es un Cliente o un Proveedor.

### ¿Qué es un CRUD?

CRUD es una sigla en inglés que resume las 4 operaciones que casi cualquier pantalla de gestión necesita:

| Letra | Significado | En español | Ejemplo con "Vendedores" |
|---|---|---|---|
| **C** | Create | Crear | Formulario para agregar un vendedor nuevo |
| **R** | Read | Leer/Ver | Listado de todos los vendedores, y el detalle de uno |
| **U** | Update | Editar | Formulario para modificar los datos de un vendedor |
| **D** | Delete | Eliminar | Botón para borrar un vendedor |

Todo el sistema (Marcas, Productos, Clientes, Facturas...) es, en el fondo, el mismo CRUD repetido una y otra vez con datos distintos. Una vez que armes uno, ya sabes armar todos.

### Repaso: las 5 piezas que vas a tocar

Antes de escribir código, es clave entender qué hace cada archivo. Usa esta analogía: imagina que quieres llevar el registro de vendedores **en papel**, en una oficina:

| Pieza | Archivo | Analogía de oficina | Qué hace en Django |
|---|---|---|---|
| **Modelo** | `models.py` | El armario y sus carpetas | Define QUÉ datos se guardan y CÓMO (una clase Python = una tabla en la base de datos) |
| **Formulario** | `forms.py` | La hoja/planilla en blanco que llenas a mano | Define qué campos se piden y valida que estén bien llenados antes de guardar |
| **Vista** | `views.py` | La persona (empleado) que atiende, recibe la hoja y decide qué hacer | Recibe la petición del navegador, usa el formulario/modelo, y decide qué mostrar |
| **URL** | `urls.py` | El letrero en la puerta de la oficina ("Oficina 302 = Vendedores") | Conecta una dirección web (ej. `/vendedores/`) con la vista que la atiende |
| **Plantilla** | `templates/*.html` | El formulario impreso que ve y llena el visitante | El HTML que el navegador realmente muestra |

El camino que sigue SIEMPRE una petición es:

```
El usuario visita una URL
   → Django busca esa URL en urls.py
   → urls.py le dice qué función/clase de views.py debe atenderla
   → la vista usa el formulario (forms.py) para validar datos
   → el formulario guarda (o lee) datos usando el modelo (models.py)
   → la vista elige una plantilla (templates/*.html) y la rellena con los datos
   → esa plantilla ya armada (HTML) es lo que el navegador muestra
```

Vamos a construir estas 5 piezas, una por una, para "Vendedores".

---

### Paso 0 — Decidir en qué app va y qué datos va a guardar

"Vendedores" es parte del negocio de ventas, así que va en la app `billing/` (la misma donde están Cliente, Producto, etc.). Si algún día necesitas una app totalmente nueva desde cero (no es el caso acá), el comando sería `python manage.py startapp mi_app` y luego agregarla a la lista `INSTALLED_APPS` en `config/settings.py`.

Antes de programar, en papel, decidimos qué datos queremos guardar de cada vendedor:

- Nombres y apellidos
- Cédula (para no repetir a la misma persona dos veces)
- Correo y teléfono
- Fecha de contratación
- Porcentaje de comisión que gana por venta
- Zona donde trabaja (Norte, Sur, Centro)
- Si está activo o ya no trabaja en la empresa

### Paso 1 — El Modelo (`models.py`)

El modelo es una clase de Python que Django convierte automáticamente en una tabla de base de datos. **Cada atributo de la clase = una columna de la tabla.**

Abre `billing/models.py` y agrega esto al final del archivo:

```python
# billing/models.py
from shared.validators import validate_cedula_ec  # ya existe, valida cédula ecuatoriana

class Salesperson(models.Model):
    """Vendedores de la empresa (ficha de datos, no tiene que ver con el login)."""

    ZONA_CHOICES = [
        ('norte', 'Norte'),
        ('sur', 'Sur'),
        ('centro', 'Centro'),
    ]

    first_name = models.CharField(max_length=100, verbose_name='Nombres')
    last_name = models.CharField(max_length=100, verbose_name='Apellidos')
    dni = models.CharField(
        max_length=13, unique=True, verbose_name='Cédula',
        validators=[validate_cedula_ec],
    )
    email = models.EmailField(blank=True, null=True, verbose_name='Correo electrónico')
    phone = models.CharField(max_length=20, blank=True, null=True, verbose_name='Teléfono')
    hire_date = models.DateField(verbose_name='Fecha de contratación')
    commission_rate = models.DecimalField(
        max_digits=5, decimal_places=2, default=0,
        verbose_name='Comisión (%)',
    )
    zone = models.CharField(
        max_length=10, choices=ZONA_CHOICES, default='centro',
        verbose_name='Zona',
    )
    is_active = models.BooleanField(default=True, verbose_name='Activo')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Vendedor'
        verbose_name_plural = 'Vendedores'
        ordering = ['last_name', 'first_name']

    def __str__(self):
        return f'{self.last_name}, {self.first_name}'
```

**Explicación de cada línea, para que no memorices sin entender:**

- **`class Salesperson(models.Model):`** — así se crea un modelo nuevo. El nombre de la clase va en inglés y en singular por convención de Django (aunque el sistema hable en español al usuario, el código interno suele ir en inglés). `models.Model` es la clase base de Django que le da a `Salesperson` todo el poder de guardarse en la base de datos.
- **`ZONA_CHOICES`** — una lista de tuplas `(valor_guardado, texto_visible)`. Django la usa para mostrar un `<select>` con esas 3 opciones en vez de un cuadro de texto libre.
- **`models.CharField(max_length=100, ...)`** — un campo de texto corto (obligatorio decir cuántos caracteres como máximo, `max_length`).
- **`unique=True`** — no puede haber dos vendedores con la misma cédula. Si alguien lo intenta, la base de datos lo rechaza.
- **`blank=True, null=True`** — el campo es **opcional**. `null=True` permite que la base de datos guarde "vacío" (`NULL`); `blank=True` permite que el formulario lo deje vacío. Casi siempre van juntos.
- **`models.EmailField`** — como CharField, pero además valida que tenga forma de correo (`algo@algo.algo`).
- **`models.DateField`** — guarda una fecha (sin hora). Existe también `DateTimeField` (fecha + hora), que ya usás en otros modelos como `Invoice.invoice_date`.
- **`models.DecimalField(max_digits=5, decimal_places=2, ...)`** — para números con decimales EXACTOS (nunca uses `FloatField` para dinero o porcentajes, porque puede perder precisión). `max_digits=5, decimal_places=2` permite hasta `999.99`.
- **`choices=ZONA_CHOICES`** — limita los valores posibles de ese campo a los de la lista.
- **`default=...`** — el valor que toma el campo si no se especifica nada.
- **`verbose_name='...'`** — el texto en español que se muestra como etiqueta en formularios y en el panel `/admin/`. Sin esto, Django mostraría el nombre del campo en inglés (`first_name`).
- **`class Meta:`** — configuración extra del modelo que no es un campo: `verbose_name`/`verbose_name_plural` (cómo se llama "una" y "varias" en el panel admin), `ordering` (el orden por defecto al listar — acá, apellido y luego nombre).
- **`def __str__(self):`** — qué texto mostrar cuando Django necesita representar un vendedor como texto (por ejemplo, en un `<select>` de otro formulario, o en el panel admin). Si no lo defines, verías algo inútil como `Salesperson object (1)`.

### Paso 2 — La Migración

El modelo que acabas de escribir solo existe en el archivo Python — **todavía no existe ninguna tabla real en la base de datos**. Para crearla, Django usa "migraciones": archivos que describen el cambio (ej. "agregar la tabla Salesperson") y que se aplican en orden.

En la terminal, con el entorno virtual activado:

```
python manage.py makemigrations billing
```

Esto **no toca la base de datos todavía** — solo genera un archivo nuevo (algo como `billing/migrations/0005_salesperson.py`) describiendo el cambio. Deberías ver algo así en la consola:

```
Migrations for 'billing':
  billing\migrations\0005_salesperson.py
    + Create model Salesperson
```

Si en vez de eso ves `No changes detected`, revisa que guardaste el archivo `models.py` y que la clase esté bien escrita (sin errores de indentación).

Ahora sí, aplica el cambio real a la base de datos:

```
python manage.py migrate
```

Deberías ver:

```
Applying billing.0005_salesperson... OK
```

> **Regla de oro:** nunca edites la base de datos a mano ni edites una migración vieja ya aplicada. Si te equivocaste en un campo, cambia el modelo y corre `makemigrations` de nuevo — Django genera una migración nueva que corrige el campo.

### Paso 3 — El Formulario (`forms.py`)

El formulario es el puente entre el HTML (lo que el usuario llena) y el modelo (lo que se guarda). Abre `billing/forms.py` y agrega:

```python
# billing/forms.py
from .models import Salesperson

class SalespersonForm(forms.ModelForm):
    class Meta:
        model = Salesperson
        fields = [
            'first_name', 'last_name', 'dni', 'email', 'phone',
            'hire_date', 'commission_rate', 'zone', 'is_active',
        ]
        widgets = {
            'first_name': forms.TextInput(attrs={'class': 'form-control'}),
            'last_name': forms.TextInput(attrs={'class': 'form-control'}),
            'dni': forms.TextInput(attrs={'class': 'form-control'}),
            'email': forms.EmailInput(attrs={'class': 'form-control'}),
            'phone': forms.TextInput(attrs={'class': 'form-control'}),
            'hire_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'commission_rate': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'zone': forms.Select(attrs={'class': 'form-select'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }

    def clean_commission_rate(self):
        rate = self.cleaned_data.get('commission_rate')
        if rate is not None and (rate < 0 or rate > 100):
            raise forms.ValidationError('La comisión debe estar entre 0 y 100.')
        return rate
```

**Explicación:**

- **`class SalespersonForm(forms.ModelForm):`** — un `ModelForm` es un formulario "ligado" a un modelo: Django genera automáticamente un campo de formulario por cada campo del modelo que listes en `fields`, con el tipo de input correcto (texto, número, fecha, `<select>`, checkbox...).
- **`class Meta:`** — acá le decís a Django DE QUÉ modelo es este formulario (`model = Salesperson`) y CUÁLES de sus campos mostrar (`fields = [...]`). Si un campo del modelo no aparece en esta lista, simplemente no aparece en el formulario (ej. `created_at`, que se llena solo).
- **`widgets = {...}`** — un widget es "cómo se ve" el campo en HTML. Por defecto Django ya elige uno razonable (texto para CharField, checkbox para BooleanField, etc.), pero acá los personalizamos para que tengan las clases de Bootstrap (`form-control`, `form-select`) y así se vean iguales al resto del sistema.
- **`forms.DateInput(attrs={..., 'type': 'date'})`** — el `type: 'date'` hace que el navegador muestre un selector de calendario nativo.
- **`def clean_commission_rate(self):`** — una validación PERSONALIZADA para un campo específico. Django llama automáticamente a cualquier método con el nombre `clean_<nombre_del_campo>` cuando valida el formulario. Si algo está mal, se lanza `forms.ValidationError(...)` con el mensaje que se le va a mostrar al usuario, justo debajo de ese campo. Si está bien, siempre hay que `return` el valor (aunque no lo hayas modificado).

> Para la lista completa de tipos de campo, widgets y métodos disponibles, ver la sección [Guía de métodos y campos útiles en Forms](#guía-de-métodos-y-campos-útiles-en-forms) más abajo.

### Paso 4 — Las Vistas (`views.py`)

Las vistas son las que de verdad "hacen" algo: leen la base de datos, procesan el formulario, deciden qué mostrar. Vamos a usar **vistas basadas en clase (CBV)** — Django ya trae clases genéricas (`ListView`, `CreateView`, `UpdateView`, `DeleteView`, `DetailView`) que resuelven el 90% del trabajo repetitivo del CRUD; solo hay que decirles el modelo y el formulario.

Abre `billing/views.py` y agrega (asegúrate de que `Salesperson` y `SalespersonForm` estén importados arriba del archivo):

```python
# billing/views.py
from django.views.generic import ListView, CreateView, UpdateView, DeleteView, DetailView
from shared.mixins import PermissionRequiredRedirectMixin
from .models import Salesperson
from .forms import SalespersonForm

class SalespersonListView(LoginRequiredMixin, PermissionRequiredRedirectMixin, ListView):
    model = Salesperson
    template_name = 'billing/salesperson_list.html'
    context_object_name = 'items'          # nombre con el que la plantilla accede a la lista
    permission_required = 'billing.view_salesperson'
    permission_redirect_url = '/'

class SalespersonDetailView(LoginRequiredMixin, PermissionRequiredRedirectMixin, DetailView):
    model = Salesperson
    template_name = 'billing/salesperson_detail.html'
    context_object_name = 'salesperson'
    permission_required = 'billing.view_salesperson'
    permission_redirect_url = '/salespersons/'

class SalespersonCreateView(LoginRequiredMixin, PermissionRequiredRedirectMixin, CreateView):
    model = Salesperson
    form_class = SalespersonForm
    template_name = 'billing/salesperson_form.html'
    success_url = reverse_lazy('billing:salesperson_list')
    permission_required = 'billing.add_salesperson'
    permission_redirect_url = '/salespersons/'

class SalespersonUpdateView(LoginRequiredMixin, PermissionRequiredRedirectMixin, UpdateView):
    model = Salesperson
    form_class = SalespersonForm
    template_name = 'billing/salesperson_form.html'
    success_url = reverse_lazy('billing:salesperson_list')
    permission_required = 'billing.change_salesperson'
    permission_redirect_url = '/salespersons/'

class SalespersonDeleteView(LoginRequiredMixin, PermissionRequiredRedirectMixin, DeleteView):
    model = Salesperson
    template_name = 'billing/salesperson_confirm_delete.html'
    success_url = reverse_lazy('billing:salesperson_list')
    permission_required = 'billing.delete_salesperson'
    permission_redirect_url = '/salespersons/'
```

**Explicación de cada pieza (se repite en las 5 clases):**

- **`model = Salesperson`** — le dice a la vista con qué modelo trabajar.
- **`form_class = SalespersonForm`** — (solo en Create/Update) qué formulario usar para validar los datos que llegan.
- **`template_name = '...'`** — qué archivo HTML renderizar. Por convención, en este proyecto siempre es `templates/<app>/<modelo>_<acción>.html`.
- **`context_object_name = 'items'`** — el nombre de la variable que vas a usar DENTRO de la plantilla HTML para recorrer los resultados (ej. `{% for item in items %}`). Si no lo pones, Django usa por defecto `object_list` (para listas) u `object` (para uno solo) — funciona igual, pero un nombre elegido por vos es más claro de leer.
- **`success_url = reverse_lazy('billing:salesperson_list')`** — a dónde redirigir cuando la operación (crear/editar/borrar) sale bien. `reverse_lazy` convierte el `name` de una URL (definida en `urls.py`) en la ruta real (`/salespersons/`), sin tener que escribirla a mano ni arriesgarte a que quede desactualizada si cambias la URL después.
- **`permission_required = 'billing.add_salesperson'`** — el permiso Django real que hay que tener para entrar a esta vista. Fíjate el patrón: `<nombre de la app>.<acción>_<nombre del modelo en minúscula>`. Django genera estos 4 permisos automáticamente (`add_`, `change_`, `delete_`, `view_`) apenas migras el modelo — no hay que crearlos a mano.
- **`permission_redirect_url = '/salespersons/'`** — a dónde mandar al usuario (con un mensaje de error) si NO tiene ese permiso.
- **`LoginRequiredMixin`** — exige que haya una sesión iniciada (si no, redirige al login). Siempre va primero en la lista de herencia.
- **`PermissionRequiredRedirectMixin`** — la pieza que realmente revisa `permission_required` (está definida en `shared/mixins.py`, reutilizada por todo el proyecto).

### Paso 5 — Las URLs (`urls.py`)

Ahora hay que decirle a Django qué dirección web activa cada vista. Abre `billing/urls.py` y agrega estas líneas dentro de la lista `urlpatterns`:

```python
# billing/urls.py
path('salespersons/', views.SalespersonListView.as_view(), name='salesperson_list'),
path('salespersons/create/', views.SalespersonCreateView.as_view(), name='salesperson_create'),
path('salespersons/<int:pk>/', views.SalespersonDetailView.as_view(), name='salesperson_detail'),
path('salespersons/<int:pk>/edit/', views.SalespersonUpdateView.as_view(), name='salesperson_update'),
path('salespersons/<int:pk>/delete/', views.SalespersonDeleteView.as_view(), name='salesperson_delete'),
```

**Explicación:**

- **`path('salespersons/', vista, name='...')`** — el primer argumento es el pedazo de URL (se suma al prefijo de la app; como `billing.urls` está incluido en la raíz, esto termina siendo `/salespersons/`). El segundo es la vista que atiende. El tercero, `name=`, es un **alias interno** que vas a usar en el código y en las plantillas para no tener que escribir la URL a mano — así, si un día cambias `/salespersons/` por `/vendedores/`, no tenés que salir a buscar cada link del sistema, solo cambiás esta línea.
- **`<int:pk>`** — una parte VARIABLE de la URL: acepta cualquier número entero y se lo pasa a la vista como el argumento `pk` (primary key = el ID del registro). Por ejemplo, `/salespersons/7/edit/` abre el formulario de edición del vendedor con ID 7.
- **`views.SalespersonListView.as_view()`** — las CBV no se usan directo, hay que llamarles `.as_view()` (esto convierte la clase en algo que Django puede tratar como una función normal). Las FBV (funciones simples, como `brand_list`) NO llevan `.as_view()`.

Con esto ya podrías entrar a `/salespersons/` en el navegador (una vez con sesión iniciada y el permiso correspondiente) y verías... un error, porque falta el último paso: las plantillas.

### Paso 6 — Las Plantillas (`templates/billing/`)

Cada vista de las que armamos apunta a un archivo HTML que **todavía no existe**. Hay que crear 4 archivos dentro de `billing/templates/billing/`.

**`salesperson_list.html`** (el listado):

```html
{% extends 'billing/base.html' %}
{% block title %}Vendedores{% endblock %}
{% block content %}

<div class="d-flex justify-content-between align-items-center mb-3">
  <h2 class="mb-0">Vendedores</h2>
  <a href="{% url 'billing:salesperson_create' %}" class="btn btn-primary">+ Nuevo vendedor</a>
</div>

<table class="table table-striped table-hover">
  <thead class="table-dark">
    <tr><th>#</th><th>Nombre</th><th>Cédula</th><th>Zona</th><th>Comisión</th><th>Activo</th><th>Acciones</th></tr>
  </thead>
  <tbody>
    {% for item in items %}
    <tr>
      <td>{{ forloop.counter }}</td>
      <td>{{ item.last_name }}, {{ item.first_name }}</td>
      <td>{{ item.dni }}</td>
      <td>{{ item.get_zone_display }}</td>
      <td>{{ item.commission_rate }}%</td>
      <td>
        {% if item.is_active %}
          <span class="badge bg-success">Sí</span>
        {% else %}
          <span class="badge bg-danger">No</span>
        {% endif %}
      </td>
      <td>
        <a href="{% url 'billing:salesperson_detail' item.pk %}" class="btn btn-sm btn-info">Ver</a>
        <a href="{% url 'billing:salesperson_update' item.pk %}" class="btn btn-sm btn-warning">Editar</a>
        <a href="{% url 'billing:salesperson_delete' item.pk %}" class="btn btn-sm btn-danger">Borrar</a>
      </td>
    </tr>
    {% empty %}
    <tr><td colspan="7" class="text-center">No hay vendedores registrados</td></tr>
    {% endfor %}
  </tbody>
</table>
{% endblock %}
```

**`salesperson_form.html`** (sirve para CREAR y EDITAR, es el mismo formulario en los dos casos):

```html
{% extends 'billing/base.html' %}
{% block title %}Vendedor{% endblock %}
{% block content %}
<div class="row justify-content-center">
  <div class="col-md-7">
    <div class="card shadow">
      <div class="card-header bg-primary text-white">
        <h4 class="mb-0">{{ form.instance.pk|yesno:"Editar vendedor,Nuevo vendedor" }}</h4>
      </div>
      <div class="card-body">
        <form method="post">
          {% csrf_token %}
          {{ form.as_p }}
          <button type="submit" class="btn btn-primary">Guardar</button>
          <a href="{% url 'billing:salesperson_list' %}" class="btn btn-secondary">Cancelar</a>
        </form>
      </div>
    </div>
  </div>
</div>
{% endblock %}
```

**`salesperson_confirm_delete.html`** (pantalla de "¿estás seguro?"):

```html
{% extends 'billing/base.html' %}
{% block title %}Eliminar Vendedor{% endblock %}
{% block content %}
<div class="row justify-content-center">
  <div class="col-md-6">
    <div class="card shadow">
      <div class="card-header bg-danger text-white"><h4 class="mb-0">Confirmar eliminación</h4></div>
      <div class="card-body">
        <p>¿Seguro que deseas eliminar a <strong>{{ object }}</strong>? Esta acción no se puede deshacer.</p>
        <form method="post">
          {% csrf_token %}
          <button type="submit" class="btn btn-danger">Sí, eliminar</button>
          <a href="{% url 'billing:salesperson_list' %}" class="btn btn-secondary">Cancelar</a>
        </form>
      </div>
    </div>
  </div>
</div>
{% endblock %}
```

**`salesperson_detail.html`** (ver el detalle de uno solo):

```html
{% extends 'billing/base.html' %}
{% block title %}{{ salesperson }}{% endblock %}
{% block content %}
<div class="row justify-content-center">
  <div class="col-md-7">
    <div class="card shadow">
      <div class="card-header bg-primary text-white"><h4 class="mb-0">{{ salesperson }}</h4></div>
      <div class="card-body">
        <p><strong>Cédula:</strong> {{ salesperson.dni }}</p>
        <p><strong>Correo:</strong> {{ salesperson.email|default:"-" }}</p>
        <p><strong>Teléfono:</strong> {{ salesperson.phone|default:"-" }}</p>
        <p><strong>Fecha de contratación:</strong> {{ salesperson.hire_date|date:"d/m/Y" }}</p>
        <p><strong>Zona:</strong> {{ salesperson.get_zone_display }}</p>
        <p><strong>Comisión:</strong> {{ salesperson.commission_rate }}%</p>
      </div>
      <div class="card-footer d-flex gap-2">
        <a href="{% url 'billing:salesperson_list' %}" class="btn btn-outline-secondary">Volver</a>
        <a href="{% url 'billing:salesperson_update' salesperson.pk %}" class="btn btn-warning">Editar</a>
        <a href="{% url 'billing:salesperson_delete' salesperson.pk %}" class="btn btn-danger">Borrar</a>
      </div>
    </div>
  </div>
</div>
{% endblock %}
```

**Explicación de las etiquetas de plantilla (template tags) que aparecen:**

- **`{% extends 'billing/base.html' %}`** — SIEMPRE va primero: hace que esta página "herede" la barra de navegación, el pie de página y los estilos ya definidos en `base.html`, para no repetirlos en cada pantalla.
- **`{% block content %}...{% endblock %}`** — el hueco dentro de `base.html` que esta plantilla rellena con SU contenido propio.
- **`{% for item in items %}...{% empty %}...{% endfor %}`** — recorre una lista. `{% empty %}` es lo que se muestra si la lista está vacía (en vez de una tabla en blanco).
- **`{{ variable }}`** — imprime un valor. `{{ item.dni }}` es "el campo `dni` del objeto `item`".
- **`{{ item.get_zone_display }}`** — un método que Django genera SOLO para campos con `choices`: en vez de mostrar el valor guardado (`'norte'`), muestra el texto legible (`'Norte'`).
- **`{% if condición %}...{% else %}...{% endif %}`** — igual que un `if` de Python.
- **`{% csrf_token %}`** — **obligatorio** en todo `<form method="post">`. Es un código de seguridad que evita que otro sitio web envíe formularios falsos a tu sistema en tu nombre. Si lo olvidas, Django rechaza el envío con un error 403.
- **`{{ form.as_p }}`** — la forma más rápida de mostrar TODOS los campos de un formulario, cada uno envuelto en un `<p>` con su etiqueta y sus errores. Es la opción más simple para empezar; más adelante podés reemplazarla por campos escritos a mano (`{{ form.first_name }}`, `{{ form.first_name.errors }}`, etc.) si querés un diseño más prolijo, como hacen `product_form.html` o `invoice_form.html`.
- **`{% url 'billing:salesperson_update' item.pk %}` ** — genera la URL real a partir del `name` que le pusiste en `urls.py` (`billing:salesperson_update`), reemplazando `<int:pk>` por `item.pk`. Nunca escribas la URL a mano (`/salespersons/7/edit/`) — si cambia el patrón de URLs, todo lo que use `{% url %}` se actualiza solo.
- **`{{ valor|filtro }}`** — un "filtro" transforma un valor antes de mostrarlo. `|default:"-"` muestra un guion si el valor está vacío; `|date:"d/m/Y"` da formato a una fecha; `|yesno:"Sí,No"` convierte `True`/`False` en texto.

### Paso 7 — Agregar el link al menú

Abre `billing/templates/billing/base.html`, busca la barra de navegación (los `<li class="nav-item">` dentro de `<ul class="navbar-nav me-auto">`) y agrega uno nuevo, junto a los demás:

```html
<li class="nav-item">
  <a class="nav-link" href="{% url 'billing:salesperson_list' %}">
    <i class="bi bi-person-badge me-1"></i>Vendedores
  </a>
</li>
```

Fíjate en qué bloque `{% if user|has_group:... %}` lo pones, según qué rol debería ver este módulo en el menú (esto es solo visual — el permiso real que de verdad bloquea el acceso ya lo pusiste en la vista con `permission_required`).

### Paso 8 — Darle permisos a los roles

Aunque migraste el modelo, **Django ya creó los 4 permisos solos** (`billing.add_salesperson`, `change_salesperson`, `delete_salesperson`, `view_salesperson`) — pero **ningún rol los tiene asignados todavía**, así que ahora mismo nadie (excepto un superusuario) puede usar este módulo nuevo. Dos formas de asignarlos:

1. **Desde la interfaz** (la más fácil): entra a `/security/permissions/` como administrador, elige el rol (ej. "Administrador"), busca el cuadro "Vendedor" y marca las casillas Ver/Agregar/Editar/Eliminar que corresponda.
2. **Desde código**: agrega los codenames al diccionario `ROLES` en `security/management/commands/setup_roles.py` y vuelve a correr `python manage.py setup_roles`.

### Paso 9 — ¡Probarlo!

1. Corre el servidor: `python manage.py runserver`
2. Entra a `http://127.0.0.1:8000/` e inicia sesión como administrador.
3. Deberías ver "Vendedores" en el menú (si agregaste el link en el paso 7). Si no, entra directo a `http://127.0.0.1:8000/salespersons/`.
4. Prueba crear uno con "+ Nuevo vendedor", edítalo, míralo con "Ver", y bórralo — las 4 operaciones del CRUD.

Si algo falla, revisa en este orden: 1) ¿corriste `makemigrations` y `migrate`? 2) ¿el nombre de la plantilla en la vista coincide EXACTO con el archivo que creaste? 3) ¿el `name=` de la URL coincide con lo que usás en `{% url %}`? 4) leé el error que Django muestra en el navegador (con `DEBUG=True` es bastante claro sobre qué línea y qué archivo falló).

### Resumen del patrón (para memorizar)

```
Modelo (models.py)
   → migración (makemigrations + migrate)
   → formulario (forms.py)
   → vistas con permission_required (views.py)
   → rutas (urls.py)
   → plantillas (templates/)
   → link en el menú (base.html)
   → permisos asignados a roles (/security/permissions/ o setup_roles.py)
```

Este es el mismo camino que siguen **todos** los módulos existentes del sistema (Brand, Product, Customer, Supplier, Purchase, etc.) — no hay magia oculta, solo repetición consistente del mismo patrón Django: **Modelo → Formulario → Vista → URL → Plantilla**.

---

## Guía de métodos y campos útiles en Forms

Referencia rápida de lo que vas a usar una y otra vez al escribir formularios en `forms.py`. No hace falta memorizarla — vuelve a esta sección cada vez que necesites un tipo de campo o una validación.

### Tipos de campo más comunes

Cada uno le dice a Django qué tipo de dato acepta y cómo validarlo automáticamente:

| Campo | Para qué sirve | Ejemplo |
|---|---|---|
| `CharField` | Texto corto (obligatorio poner `max_length`) | `forms.CharField(max_length=100)` |
| `EmailField` | Texto que además debe tener forma de correo | `forms.EmailField()` |
| `IntegerField` | Números enteros | `forms.IntegerField(min_value=1)` |
| `DecimalField` | Números con decimales exactos (dinero, porcentajes) | `forms.DecimalField(max_digits=10, decimal_places=2)` |
| `BooleanField` | Sí/No (checkbox) | `forms.BooleanField(required=False)` |
| `DateField` | Una fecha | `forms.DateField()` |
| `DateTimeField` | Fecha y hora | `forms.DateTimeField()` |
| `ChoiceField` | Elegir UNA opción de una lista fija (no ligada a otro modelo) | `forms.ChoiceField(choices=[('a','A'),('b','B')])` |
| `ModelChoiceField` | Elegir UN registro de otro modelo (genera un `<select>` con esos registros) | `forms.ModelChoiceField(queryset=Brand.objects.all())` |
| `ModelMultipleChoiceField` | Elegir VARIOS registros de otro modelo (checkboxes o `<select multiple>`) | `forms.ModelMultipleChoiceField(queryset=Supplier.objects.all())` |
| `FileField` / `ImageField` | Subir un archivo / una imagen | `forms.ImageField(required=False)` |

> Dato clave: en un `ModelForm` (como todos los de este proyecto), **no necesitas declarar los campos que ya existen en el modelo** — Django los genera solos a partir de `Meta.fields`. Solo declaras un campo a mano cuando necesitás algo especial que el modelo no puede inferir (ej. un campo `role` que en realidad no es una columna de `User`, como en `security/forms.py` → `UserRegisterForm`).

### Widgets más comunes (cómo se ve el campo en HTML)

| Widget | Se ve como |
|---|---|
| `TextInput` | `<input type="text">` |
| `Textarea` | `<textarea>` (varias líneas) |
| `EmailInput` | `<input type="email">` |
| `NumberInput` | `<input type="number">` |
| `PasswordInput` | `<input type="password">` (oculta lo que se escribe) |
| `DateInput(attrs={'type': 'date'})` | selector de calendario |
| `Select` | `<select>` (una opción) |
| `SelectMultiple` | `<select multiple>` (varias opciones) |
| `CheckboxInput` | `<input type="checkbox">` |
| `CheckboxSelectMultiple` | una lista de checkboxes (para elegir varios) |
| `RadioSelect` | botones de opción (uno a la vez) |
| `ClearableFileInput` | selector de archivo, con opción de "borrar el actual" al editar |

Se usan así, dentro de `Meta.widgets` (para un `ModelForm`) o como argumento `widget=` (para un campo declarado a mano):
```python
'mi_campo': forms.Select(attrs={'class': 'form-select'})
```
`attrs={...}` son atributos HTML normales — en este proyecto casi siempre se usa para poner las clases de Bootstrap (`form-control`, `form-select`, `form-check-input`).

### Argumentos que aceptan casi todos los campos

| Argumento | Qué hace |
|---|---|
| `required=False` | El campo se vuelve opcional (por defecto, todos son obligatorios) |
| `label='Texto'` | La etiqueta que se muestra (si no, Django la genera del nombre del campo) |
| `help_text='Texto'` | Un texto de ayuda debajo del campo |
| `initial=valor` | Valor precargado cuando el formulario está vacío |
| `widget=...` | Qué widget usar (ver tabla de arriba) |
| `validators=[...]` | Lista de funciones de validación extra (ej. `validate_cedula_ec`) |
| `min_value` / `max_value` | (en campos numéricos) límites permitidos |
| `queryset=...` | (en ModelChoiceField/ModelMultipleChoiceField) de qué registros elegir |
| `empty_label='...'` | (en ModelChoiceField) el texto de la opción vacía, ej. `'-- Elige uno --'` |

### Métodos y atributos que vas a usar en las vistas

Esto es lo que realmente escribís en `views.py` cuando trabajás con un formulario a mano (en una FBV) — en las CBV (`CreateView`, etc.) Django hace estos pasos por vos automáticamente:

```python
form = MiForm(request.POST)      # arma el formulario con los datos que llegaron
if form.is_valid():              # corre TODAS las validaciones (campo por campo y clean())
    dato = form.cleaned_data['nombre_del_campo']   # el valor ya validado y convertido al tipo correcto
    objeto = form.save()         # crea/actualiza el registro en la base de datos
else:
    form.errors                  # diccionario con los errores por campo, para mostrarlos
```

| Método / atributo | Qué hace |
|---|---|
| `form.is_valid()` | Corre todas las validaciones. Devuelve `True`/`False`. **Siempre hay que llamarlo antes de leer `cleaned_data`** |
| `form.cleaned_data` | Diccionario con los valores YA validados y convertidos (ej. una fecha llega como objeto `date`, no como texto) |
| `form.save()` | (solo ModelForm) Guarda el registro en la base de datos y lo devuelve |
| `form.save(commit=False)` | Prepara el objeto en memoria SIN guardarlo todavía — útil cuando necesitás modificar algo antes de guardar (ver `invoice_create` en `billing/views.py`) |
| `form.errors` | Diccionario de errores por campo, para mostrarlos en la plantilla |
| `form.non_field_errors()` | Errores que no son de un campo específico (los que lanza `clean()`, no `clean_<campo>()`) |
| `form.as_p()` / `.as_table()` / `.as_ul()` | Formas rápidas de renderizar TODOS los campos de una vez |
| `clean_<campo>(self)` | Validación de UN campo específico. Se define dentro de la clase del formulario; siempre debe hacer `return` del valor |
| `clean(self)` | Validación que involucra VARIOS campos a la vez (ej. "la fecha de fin debe ser posterior a la de inicio"). Se llama después de todos los `clean_<campo>` |

### Formularios que no son de un modelo (`forms.Form`)

No todos los formularios crean o editan un registro — por ejemplo, `RecoverCredentialsForm` (correo + canal de envío) o `PasswordChangeCodeForm` (código + nueva contraseña) en `security/forms.py` no guardan nada directamente, solo recolectan datos para que LA VISTA decida qué hacer con ellos. Para esos casos se usa `forms.Form` en vez de `forms.ModelForm` — es igual, pero sin `Meta.model` ni `save()`; declarás cada campo a mano:

```python
class MiFormularioForm(forms.Form):
    correo = forms.EmailField(label='Correo electrónico')
    codigo = forms.CharField(max_length=6, label='Código de verificación')
```

---

## Exportación PDF y Excel

```python
exporter = ExportMixin()
exporter.export_filename = 'productos'
exporter.export_title = 'Listado de Productos'
exporter.export_headers = ['Nombre', 'Marca', 'Precio']
exporter.get_export_rows = lambda qs: [[p.name, p.brand.name, p.unit_price] for p in qs]

if export == 'pdf':
    return exporter.export_to_pdf(queryset)
else:
    return exporter.export_to_excel(queryset)
```

---

## Django ORM

Abrir el shell interactivo:
```
python manage.py shell_plus --print-sql
```

Ejemplos básicos:
```python
# CREATE
Brand.objects.create(name='Nike', is_active=True)

# READ
Product.objects.filter(is_active=True).order_by('-unit_price')

# UPDATE
p = Product.objects.get(id=1)
p.unit_price = 9.99
p.save()

# DELETE
Brand.objects.get(name='Nike').delete()

# AGREGACIONES
from django.db.models import Sum, Avg, Count
Product.objects.aggregate(total=Sum('stock'))
Brand.objects.annotate(n=Count('products')).values('name', 'n')

# PERMISOS (¿puede este usuario borrar productos?)
user.has_perm('billing.delete_product')
```

---

## Credenciales de acceso

Crear superusuario:
```
python manage.py createsuperuser
```

Cambiar contraseña desde el shell:
```python
python manage.py shell
from django.contrib.auth.models import User
u = User.objects.get(username='admin')
u.set_password('nueva_contraseña')
u.save()
```

Panel de administración: `http://127.0.0.1:8000/admin/`

---

## Tecnologías utilizadas

### Proyecto principal (Django)

| Tecnología | Uso |
|---|---|
| Python 3.14 | Lenguaje principal |
| Django 6.0.6 | Framework web |
| SQLite | Base de datos |
| Bootstrap 5.3 | Estilos UI |
| JavaScript (vanilla) | Formularios dinámicos, filtros en vivo, simulación visual de pago con tarjeta |
| Pillow | Imágenes de productos |
| openpyxl | Exportación Excel |
| reportlab | Exportación PDF |
| python-barcode | Códigos de barra |
| requests | Cliente HTTP hacia PayPal y hacia el microservicio de facturación SRI |
| whitenoise | Archivos estáticos/media en producción |
| Twilio | Envío de WhatsApp |
| SMTP de Gmail | Envío de correos |
| API REST de PayPal | Cobro real (Sandbox/Live) |
| django-extensions | shell_plus |
| gunicorn | Servidor de producción (Render) |

### Microservicio de facturación electrónica (FastAPI)

| Tecnología | Uso |
|---|---|
| Python 3.14 | Lenguaje principal |
| FastAPI + uvicorn | Framework web y servidor ASGI |
| SQLModel (SQLAlchemy + Pydantic) | ORM y validación de datos |
| SQLite (por defecto, cambiable a Postgres) | Base de datos propia |
| lxml | Construcción y firma del XML |
| cryptography | Lectura del certificado `.p12` y firma XAdES-BES |
| zeep | Cliente SOAP contra los web services del SRI |
| reportlab + python-barcode | Generación del PDF del RIDE |
| pydantic-settings + python-dotenv | Configuración vía `.env` propio |
| pytest + httpx | Tests propios |

---

*Desarrollado para la asignatura de Programación / Desarrollo Web con Python (Django) · Universidad Estatal de Milagro (UNEMI)*
