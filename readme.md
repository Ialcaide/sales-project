# Sistema de Ventas y Facturación — TecnoStock S.A.

Sistema web desarrollado con **Django 6.0** para gestionar el ciclo completo de ventas de una empresa: marcas, grupos de productos, proveedores, productos (con imagen o imagen autogenerada), clientes, facturación, compras (con actualización automática de inventario) y un módulo completo de **seguridad** (usuarios, roles y permisos reales, recuperación de credenciales, notificaciones por correo y WhatsApp).

Este documento está pensado para que puedas **entender cómo funciona todo el sistema** siguiendo el mismo patrón que ya usa el proyecto.

---

## Tabla de contenidos

- [Requisitos previos](#requisitos-previos)
- [Instalación paso a paso](#instalación-paso-a-paso)
- [Variables de entorno (.env)](#variables-de-entorno-env)
- [Estructura del proyecto](#estructura-del-proyecto)
- [Cómo funciona el sistema (arquitectura general)](#cómo-funciona-el-sistema-arquitectura-general)
- [Apps del proyecto](#apps-del-proyecto)
- [Sistema de Roles y Permisos](#sistema-de-roles-y-permisos)
- [Notificaciones (Email y WhatsApp)](#notificaciones-email-y-whatsapp)
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

## Instalación paso a paso

### Paso 1 — Copiar el proyecto

Copia la carpeta del proyecto a tu computadora. La estructura debe verse así:

```
sales_project/
    manage.py
    requirements.txt
    billing/
    purchasing/
    security/
    home/
    shared/
    config/
    templates/
    media/
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

El entorno virtual aísla las dependencias del proyecto de las del sistema.

```
python -m venv venvsales
```

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

> **IMPORTANTE:** El entorno virtual debe estar activo en cada sesión nueva de terminal.

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
| whitenoise | Sirve archivos estáticos/media en producción |
| django-extensions | Shell plus con SQL |
| gunicorn | Servidor WSGI para producción (Render) |

### Paso 6 — Configurar el archivo `.env`

Ver la sección [Variables de entorno](#variables-de-entorno-env) más abajo. Sin esto, el sistema funciona igual, pero **no podrá enviar correos ni mensajes de WhatsApp**.

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

---

## Variables de entorno (.env)

El proyecto lee automáticamente un archivo `.env` en la raíz (mismo nivel que `manage.py`), si existe. Esto lo hace `config/settings.py` al arrancar, **sin sobrescribir** variables reales del sistema operativo (así en Render, por ejemplo, siguen mandando las variables configuradas en su dashboard).

Crea un archivo llamado `.env` (sin nombre antes del punto) en la raíz del proyecto:

```env
# Gmail — para enviar correos de credenciales y recuperación de contraseña.
# Debe ser una "Contraseña de aplicación" de Gmail (16 caracteres), no tu contraseña normal.
EMAIL_HOST_USER=tucorreo@gmail.com
EMAIL_HOST_PASSWORD=xxxxxxxxxxxxxxxx

# Twilio — para enviar WhatsApp. Se obtienen creando una cuenta gratuita en
# https://www.twilio.com/ y activando el "WhatsApp Sandbox".
TWILIO_ACCOUNT_SID=ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TWILIO_AUTH_TOKEN=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TWILIO_WHATSAPP_FROM=whatsapp:+14155238886

# URL pública real del sistema (para que los links de los correos/WhatsApp
# funcionen sin importar si estás corriendo en tu PC o en producción).
SITE_URL=https://sales-project-dxoy.onrender.com
```

Este archivo **nunca se sube a git** (ya está en `.gitignore`). Si no lo creas, el sistema sigue funcionando normalmente — solo que al crear usuarios o recuperar credenciales, el envío de correo/WhatsApp se omite silenciosamente (queda registrado como advertencia en la consola del servidor) en vez de fallar.

---

## Estructura del proyecto

```
sales_project/
│
├── manage.py                    # Script principal de administración Django
├── requirements.txt              # Lista de dependencias del proyecto
├── dbventas.sqlite3              # Base de datos SQLite (se genera automáticamente)
├── .env                          # Variables de entorno locales (no versionado)
│
├── config/                       # Configuración principal del proyecto Django
│   ├── settings.py               # BD, apps, middleware, templates, media, email, twilio
│   ├── urls.py                   # URLs raíz: reparte tráfico a cada app
│   ├── asgi.py / wsgi.py         # Puntos de entrada del servidor
│
├── billing/                      # App principal: catálogo, clientes y facturación
│   ├── models.py                 # Brand, ProductGroup, Supplier, Product, Customer, Invoice...
│   ├── forms.py                  # Formularios de billing
│   ├── views.py                  # Vistas FBV y CBV de billing
│   ├── urls.py                   # Rutas de billing (app_name = 'billing')
│   ├── export_mixins.py          # Mixin genérico para exportar a PDF y Excel
│   ├── admin.py                  # Registro en el panel /admin/
│   ├── migrations/
│   └── templates/billing/
│
├── purchasing/                   # App de compras (actualiza el inventario)
│   ├── models.py                 # Purchase, PurchaseDetail
│   ├── forms.py                  # PurchaseForm, PurchaseDetailFormSet
│   ├── views.py
│   ├── urls.py                   # app_name = 'purchasing'
│   └── templates/purchasing/
│
├── security/                     # App de seguridad: usuarios, roles y permisos
│   ├── models.py                 # UserProfile (teléfono/WhatsApp del usuario)
│   ├── forms.py                  # UserRegisterForm, UserUpdateForm, RecoverCredentialsForm...
│   ├── views.py                  # Login, registro, roles, permisos, recuperación de acceso
│   ├── urls.py                   # app_name = 'security'
│   ├── templatetags/security_tags.py  # Filtro {{ user|has_group:"Administrador" }}
│   ├── management/commands/setup_roles.py  # Crea/sincroniza los 3 roles del sistema
│   └── templates/security/
│
├── home/                          # App del dashboard (pantalla de inicio por rol)
│   ├── views.py                   # Elige la plantilla según el rol del usuario
│   └── urls.py
│
├── shared/                        # Código reutilizable entre todas las apps
│   ├── mixins.py                  # StaffRequiredMixin, GroupRequiredMixin, PermissionRequiredRedirectMixin
│   ├── decorators.py              # @audit_action, permission_required_redirect
│   ├── notifications.py           # send_credentials_email, send_whatsapp_message
│   └── validators.py              # validate_cedula_ec
│
├── templates/                     # Plantillas globales (fuera de cada app)
│   └── registration/              # login.html, password_reset_confirm.html, etc.
│
└── media/                         # Archivos subidos por usuarios (imágenes de productos)
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
    path('accounts/', include('django.contrib.auth.urls')),   # login/logout/reset de Django
    path('security/', include('security.urls')),               # /security/... usuarios, roles, permisos
    path('purchases/', include('purchasing.urls')),            # /purchases/... compras
    path('', include('home.urls')),                             # / → dashboard
    path('', include('billing.urls')),                          # /products/, /customers/, etc.
]
```

Cada app sigue el mismo patrón interno:

1. **`models.py`** — define las tablas (una clase = una tabla). Django genera el SQL automáticamente.
2. **`forms.py`** — define qué campos se piden en un formulario HTML y cómo se validan, ligados (o no) a un modelo.
3. **`views.py`** — la lógica: recibe la petición, valida permisos, lee/guarda con el ORM, decide qué template renderizar.
4. **`urls.py`** — mapea una URL (ej. `/products/create/`) a una función o clase de `views.py`.
5. **`templates/<app>/`** — el HTML que ve el usuario, con `{{ variables }}` y `{% tags %}` de Django.

Todo el acceso a la base de datos pasa por el **ORM** de Django (`Model.objects.filter(...)`, `.create(...)`, etc.) — nunca se escribe SQL a mano en este proyecto.

---

## Apps del proyecto

### config/
Carpeta de configuración principal (no es una app en sí misma).

- **`settings.py`** — base de datos, apps instaladas, middleware, templates, archivos media/estáticos, email (Gmail), WhatsApp (Twilio), URL pública (`SITE_URL`), idioma (`es-ec`).
- **`urls.py`** — reparte las URLs raíz a cada app, y sirve `/media/` explícitamente (funciona en desarrollo **y** en producción).

### billing/
App principal del sistema. Gestiona catálogo, clientes y facturación.

- **`models.py`** — `Brand`, `ProductGroup`, `Supplier`, `Product` (con `image` e imagen autogenerada `placeholder_image` cuando no hay foto), `Customer`, `CustomerProfile`, `Invoice`, `InvoiceDetail`.
- **`forms.py`** — formularios con widgets Bootstrap y validaciones (`clean_<campo>`).
- **`views.py`** — mezcla de vistas por función (FBV: Brand, Invoice) y por clase (CBV: Product, Customer, Supplier con `CreateView`/`UpdateView`/`DeleteView`/`DetailView`). Todas protegidas con permisos reales de Django (ver [Sistema de Roles y Permisos](#sistema-de-roles-y-permisos)).
- **`export_mixins.py`** — `ExportMixin`, reutilizable para exportar cualquier queryset a Excel o PDF.

### purchasing/
App del módulo de compras. Reutiliza modelos de `billing` (`Supplier`, `Product`).

- **`models.py`** — `Purchase` (cabecera) y `PurchaseDetail` (líneas, con `unit_cost`). Restricción: no se puede repetir el mismo número de documento para el mismo proveedor.
- **`views.py`** — al confirmar una compra, sube el stock del producto y actualiza `last_cost` automáticamente.

### security/
App de seguridad: usuarios, roles, permisos y recuperación de acceso.

- **`models.py`** — `UserProfile`: perfil 1-a-1 con el `User` de Django, agrega el campo `phone` (teléfono/WhatsApp) que Django no trae por defecto.
- **`forms.py`** — `UserRegisterForm` (alta de usuario por el admin, con validaciones de correo/teléfono duplicado), `UserUpdateForm` (edición), `RecoverCredentialsForm` (correo + canal de envío).
- **`views.py`** — login personalizado, alta/edición/borrado de usuarios (solo administradores), gestión de roles (`Group`), gestión de permisos por rol/usuario, recuperación de credenciales por correo o WhatsApp.
- **`management/commands/setup_roles.py`** — comando (`python manage.py setup_roles`) que crea/sincroniza los 3 roles del sistema con sus permisos base.

### home/
App pequeña que solo decide qué dashboard mostrar según el rol del usuario logueado (`home_admin.html`, `home_vendedor.html`, `home_compras.html`).

### shared/
Módulo transversal reutilizable por cualquier app (ver sección dedicada más abajo).

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

Correr `python manage.py setup_roles` crea los grupos si no existen y sincroniza sus permisos (`group.permissions.set(...)`). **Esto es solo el punto de partida** — después, un administrador puede ajustar los permisos de cada rol libremente desde la pantalla de Gestión de Permisos, y esos cambios se aplican de inmediato a todos los usuarios de ese rol.

### La pantalla de Gestión de Permisos (`/security/permissions/`)

- **Izquierda:** lista de Roles y buscador de Usuarios — se elige a quién se le va a editar los permisos.
- **Derecha:** un cuadro por cada modelo (Producto, Cliente, Factura, etc.) con casillas **Ver / Agregar / Editar / Eliminar**.
- Si estás viendo un **usuario**, los permisos que ya tiene por su rol aparecen marcados y bloqueados (🔒 *vía rol*) — no se pueden quitar ahí (para eso se edita el rol). Puedes marcar casillas **extra** para darle permisos individuales solo a él.
- El botón **"Dar acceso a todos los permisos"** (solo visible con un usuario seleccionado) le otorga de una vez todos los permisos del sistema de forma directa.
- Cualquier cambio se aplica de inmediato: si le quitas `delete_product` a un rol, todos sus usuarios pierden esa capacidad al instante, sin reiniciar el servidor ni tocar código.

---

## Notificaciones (Email y WhatsApp)

`shared/notifications.py` centraliza el envío:

```python
send_credentials_email(to_email, subject, body)   # SMTP de Gmail
send_whatsapp_message(phone, body)                 # API de Twilio
```

Ambas funciones **nunca lanzan una excepción hacia la vista** — si falla el envío (o si no configuraste el `.env`), registran una advertencia en la consola y devuelven `False`, para que el resto de la operación (crear el usuario, por ejemplo) se complete igual.

Se usan en dos flujos:

1. **Alta de usuario** (`security/views.py` → `RegisterView`): al crear un usuario con su rol, se le envían sus credenciales (usuario, contraseña, rol, link de acceso) por correo **y** WhatsApp automáticamente.
2. **Recuperar credenciales** (`/security/recover/`): el usuario ingresa su correo y elige el canal (correo o WhatsApp); el sistema genera un link de restablecimiento de contraseña seguro (con el mecanismo de tokens propio de Django) y lo envía por ese canal.

El link que reciben siempre apunta a `settings.SITE_URL` (la URL pública real, ej. `https://sales-project-dxoy.onrender.com`), nunca a `localhost`, sin importar desde dónde el administrador esté operando.

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

### Invoice (Factura) / Purchase (Compra)
Cabeceras con `subtotal`, `tax` (IVA) y `total` calculados. `Purchase` tiene restricción de `document_number` único por `supplier`.

### UserProfile (security)
| Campo | Tipo | Descripción |
|---|---|---|
| user | OneToOneField → User | El usuario de Django |
| phone | CharField(20) | Teléfono/WhatsApp, usado para notificaciones |

---

## Funcionalidades

### Autenticación y acceso
- Login personalizado (`/accounts/login/` o `/security/login/`), con recuperación de credenciales por correo/WhatsApp — **no hay auto-registro público**: los usuarios los crea un administrador con un rol asignado.
- Todas las vistas protegidas con `@login_required` / `LoginRequiredMixin`, y las de negocio además con permisos reales por rol (ver arriba).

### Dashboard
Pantalla distinta según el rol del usuario, con conteos y gráficos (marcas, productos, clientes, facturas, compras, stock bajo).

### Buscadores, filtros y paginación
Todos los listados tienen búsqueda y filtros que se mantienen al paginar (10 registros por página).

### Exportación
Botones PDF y Excel en cada listado, exportan exactamente lo que está filtrado en pantalla.

### Facturación dinámica
Precio autocompletado al elegir producto, cálculo en tiempo real de subtotal/IVA/total, validación de stock suficiente, y baja de stock al confirmar.

### Módulo de Compras
Productos filtrados por proveedor, sube el stock y actualiza `last_cost` al registrar la compra, reporte de costo promedio por producto.

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
- **`send_credentials_email(to_email, subject, body)`** / **`send_whatsapp_message(phone, body)`** — ver [Notificaciones](#notificaciones-email-y-whatsapp).

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

| Tecnología | Uso |
|---|---|
| Python 3.14 | Lenguaje principal |
| Django 6.0.6 | Framework web |
| SQLite | Base de datos |
| Bootstrap 5.3 | Estilos UI |
| JavaScript (vanilla) | Formularios dinámicos, filtros en vivo |
| Pillow | Imágenes de productos |
| openpyxl | Exportación Excel |
| reportlab | Exportación PDF |
| whitenoise | Archivos estáticos/media en producción |
| Twilio | Envío de WhatsApp |
| SMTP de Gmail | Envío de correos |
| django-extensions | shell_plus |
| gunicorn | Servidor de producción (Render) |

---

*Desarrollado para la asignatura de Programación / Desarrollo Web con Python (Django) · Universidad Estatal de Milagro (UNEMI)*
