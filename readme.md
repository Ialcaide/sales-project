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
- [Cómo crear un CRUD desde cero](#cómo-crear-un-crud-desde-cero)
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
| twilio | Envío de mensajes de WhatsApp (recuperación de credenciales y alta de usuarios) |
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

## Cómo crear un CRUD desde cero

Esta guía crea un módulo nuevo de ejemplo — **"Almacén" (Warehouse)** — repitiendo exactamente el mismo patrón que ya usan `Product`, `Customer` y `Supplier` en `billing/`. Puedes copiar y adaptar estos pasos para cualquier modelo nuevo, en cualquier app.

### Paso 0 — Elige en qué app va

Si el modelo pertenece al negocio de ventas/catálogo, va en `billing/`. Si es sobre compras, en `purchasing/`. Si necesitas una app totalmente nueva:
```
python manage.py startapp mi_app
```
Y agrégala a `INSTALLED_APPS` en `config/settings.py`.

### Paso 1 — El modelo (`models.py`)

```python
# billing/models.py
class Warehouse(models.Model):
    """Almacenes físicos donde se guarda el stock."""
    name = models.CharField(max_length=150, unique=True, verbose_name='Nombre')
    address = models.CharField(max_length=255, blank=True, verbose_name='Dirección')
    is_active = models.BooleanField(default=True, verbose_name='Activo')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Almacén'
        verbose_name_plural = 'Almacenes'
        ordering = ['name']

    def __str__(self):
        return self.name
```

### Paso 2 — Migración

```
python manage.py makemigrations billing
python manage.py migrate
```

Esto crea la tabla en la base de datos. **Nunca edites las tablas a mano** — siempre a través de cambios al modelo + `makemigrations` + `migrate`.

### Paso 3 — El formulario (`forms.py`)

```python
# billing/forms.py
from .models import Warehouse

class WarehouseForm(forms.ModelForm):
    class Meta:
        model = Warehouse
        fields = ['name', 'address', 'is_active']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'address': forms.TextInput(attrs={'class': 'form-control'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }

    def clean_name(self):
        name = self.cleaned_data.get('name', '').strip()
        if not name:
            raise forms.ValidationError('El nombre es obligatorio.')
        return name
```

### Paso 4 — Las vistas (`views.py`)

Usamos **vistas basadas en clase (CBV)** — es el patrón recomendado en este proyecto porque requiere menos código repetido que las FBV. Cada acción CRUD se protege con el permiso Django real de `Warehouse` (Django ya generó `add_warehouse`, `change_warehouse`, `delete_warehouse`, `view_warehouse` automáticamente al migrar):

```python
# billing/views.py
from django.views.generic import ListView, CreateView, UpdateView, DeleteView
from shared.mixins import PermissionRequiredRedirectMixin
from .models import Warehouse
from .forms import WarehouseForm

class WarehouseListView(LoginRequiredMixin, PermissionRequiredRedirectMixin, ListView):
    model = Warehouse
    template_name = 'billing/warehouse_list.html'
    context_object_name = 'items'
    permission_required = 'billing.view_warehouse'
    permission_redirect_url = '/'

class WarehouseCreateView(LoginRequiredMixin, PermissionRequiredRedirectMixin, CreateView):
    model = Warehouse
    form_class = WarehouseForm
    template_name = 'billing/warehouse_form.html'
    success_url = reverse_lazy('billing:warehouse_list')
    permission_required = 'billing.add_warehouse'
    permission_redirect_url = '/warehouses/'

class WarehouseUpdateView(LoginRequiredMixin, PermissionRequiredRedirectMixin, UpdateView):
    model = Warehouse
    form_class = WarehouseForm
    template_name = 'billing/warehouse_form.html'
    success_url = reverse_lazy('billing:warehouse_list')
    permission_required = 'billing.change_warehouse'
    permission_redirect_url = '/warehouses/'

class WarehouseDeleteView(LoginRequiredMixin, PermissionRequiredRedirectMixin, DeleteView):
    model = Warehouse
    template_name = 'billing/warehouse_confirm_delete.html'
    success_url = reverse_lazy('billing:warehouse_list')
    permission_required = 'billing.delete_warehouse'
    permission_redirect_url = '/warehouses/'
```

> Si prefieres una vista por función (como `brand_list`/`brand_create` en este mismo archivo), el equivalente sería usar `@permission_required_redirect('billing.view_warehouse', '/')` de `shared/decorators.py` en vez de los mixins — ambos estilos conviven en el proyecto.

### Paso 5 — Las rutas (`urls.py`)

```python
# billing/urls.py
path('warehouses/', views.WarehouseListView.as_view(), name='warehouse_list'),
path('warehouses/create/', views.WarehouseCreateView.as_view(), name='warehouse_create'),
path('warehouses/<int:pk>/edit/', views.WarehouseUpdateView.as_view(), name='warehouse_update'),
path('warehouses/<int:pk>/delete/', views.WarehouseDeleteView.as_view(), name='warehouse_delete'),
```

### Paso 6 — Las plantillas (`templates/billing/`)

Copia y adapta `productgroup_list.html`, `productgroup_form.html` y `productgroup_confirm_delete.html` — son las más simples del proyecto (mismo tipo de modelo: nombre + activo). Solo cambia `ProductGroup` por `Warehouse` y los nombres de URL.

### Paso 7 — Agregar el link al menú

Busca la barra de navegación en `billing/templates/billing/base.html` y agrega un `<a href="{% url 'billing:warehouse_list' %}">Almacenes</a>` junto a los demás módulos.

### Paso 8 — Darle permisos a los roles

Los permisos `add_warehouse`/`change_warehouse`/`delete_warehouse`/`view_warehouse` ya existen en la base de datos (Django los crea solos al migrar), pero **ningún rol los tiene asignados todavía**. Dos formas de asignarlos:

1. **Desde la interfaz** (recomendado): entra a `/security/permissions/`, elige el rol (ej. "Administrador"), busca el cuadro "Almacén" y marca las casillas que corresponda.
2. **Desde código**, agregando los codenames al diccionario `ROLES` en `security/management/commands/setup_roles.py` y corriendo `python manage.py setup_roles` de nuevo.

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
