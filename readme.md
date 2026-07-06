# Sistema de Ventas y Facturación — TecnoStock S.A.

Sistema web desarrollado con **Django 6.0** que permite gestionar el ciclo completo de ventas de una empresa: marcas, grupos de productos, proveedores, productos, clientes, facturación y compras. Incluye un módulo de compras que actualiza el inventario automáticamente.

---

## Tabla de contenidos

- [Requisitos previos](#requisitos-previos)
- [Instalación paso a paso](#instalación-paso-a-paso)
- [Estructura del proyecto](#estructura-del-proyecto)
- [Apps del proyecto](#apps-del-proyecto)
- [Modelos de datos](#modelos-de-datos)
- [Funcionalidades](#funcionalidades)
- [URLs del sistema](#urls-del-sistema)
- [Carpeta shared](#carpeta-shared)
- [Exportación PDF y Excel](#exportación-pdf-y-excel)
- [Django ORM](#django-orm)
- [Credenciales de acceso](#credenciales-de-acceso)

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
    config/
    shared/
    templates/
    media/
```

### Paso 2 — Abrir terminal en la carpeta del proyecto

En Windows con CMD:
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

Esto crea la carpeta `venvsales/` con Python y pip propios.

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

Cuando el entorno está activo, verás `(venvsales)` al inicio del prompt:
```
(venvsales) C:\ruta\proyecto>
```

> **IMPORTANTE:** El entorno virtual debe estar activo en cada sesión nueva de terminal. Si cierras y abres una terminal, debes activarlo nuevamente con el comando del Paso 4.

### Paso 5 — Instalar dependencias

```
pip install -r requirements.txt
```

Esto instala automáticamente todos los paquetes necesarios:

| Paquete | Versión | Para qué sirve |
|---|---|---|
| Django | 6.0.6 | Framework principal |
| Pillow | 12.2.0 | Manejo de imágenes en productos |
| openpyxl | 3.1.5 | Exportación a Excel |
| reportlab | 4.5.1 | Exportación a PDF |
| django-extensions | 4.1 | Shell plus con SQL |
| sqlparse | 0.5.5 | Formato de consultas SQL |

### Paso 6 — Aplicar migraciones

Las migraciones crean las tablas en la base de datos SQLite.

```
python manage.py migrate
```

Deberías ver un mensaje como:
```
Applying billing.0001_initial... OK
Applying billing.0002_product_image... OK
Applying billing.0003_alter_customer_dni... OK
Applying billing.0004_product_last_cost... OK
Applying purchasing.0001_initial... OK
Applying purchasing.0002_purchase_unique_purchase_per_supplier... OK
```

### Paso 7 — Crear superusuario (administrador)

```
python manage.py createsuperuser
```

Ingresa el nombre de usuario, email y contraseña cuando te lo pida.

### Paso 8 — Ejecutar el servidor

```
python manage.py runserver
```

Abrir en el navegador:
```
http://127.0.0.1:8000/
```

Para detener el servidor: `Ctrl + C`

---

## Actualizar dependencias

Si agregas nuevas librerías al proyecto, actualiza el archivo `requirements.txt`:

```
pip install nombre_libreria
pip freeze > requirements.txt
```

---

## Estructura del proyecto

```
sales_project/
│
├── manage.py                    # Script principal de administración Django
├── requirements.txt             # Lista de dependencias del proyecto
├── dbventas.sqlite3             # Base de datos SQLite (se genera automáticamente)
│
├── config/                      # Configuración principal del proyecto Django
│   ├── __init__.py
│   ├── settings.py              # Configuración: BD, apps, templates, media, auth
│   ├── urls.py                  # URLs raíz del proyecto
│   ├── asgi.py                  # Configuración ASGI
│   └── wsgi.py                  # Configuración WSGI
│
├── billing/                     # App principal: ventas y facturación
│   ├── __init__.py
│   ├── admin.py                 # Registro de modelos en el panel /admin/
│   ├── apps.py                  # Configuración de la app
│   ├── models.py                # Modelos: Brand, Product, Customer, Invoice, etc.
│   ├── forms.py                 # Formularios con widgets Bootstrap
│   ├── views.py                 # Vistas FBV y CBV
│   ├── urls.py                  # Rutas de la app (app_name = 'billing')
│   ├── export_mixins.py         # Mixin genérico para exportar a PDF y Excel
│   ├── migrations/              # Migraciones de la base de datos
│   │   ├── 0001_initial.py      # Migración inicial con todos los modelos
│   │   ├── 0002_product_image.py
│   │   ├── 0003_alter_customer_dni.py
│   │   └── 0004_product_last_cost.py
│   └── templates/billing/
│       ├── base.html                      # Plantilla base con navbar
│       ├── home.html                      # Dashboard con estadísticas
│       ├── brand_list.html                # Listado de marcas
│       ├── brand_form.html                # Formulario marca
│       ├── brand_confirm_delete.html
│       ├── productgroup_list.html
│       ├── productgroup_form.html
│       ├── productgroup_confirm_delete.html
│       ├── supplier_list.html
│       ├── supplier_form.html
│       ├── supplier_detail.html           # Detalle con productos del proveedor
│       ├── supplier_confirm_delete.html
│       ├── product_list.html              # Con filtros avanzados y paginación
│       ├── product_form.html              # Con imagen y validación de precio
│       ├── product_detail.html            # Con imagen grande y margen
│       ├── product_confirm_delete.html
│       ├── customer_list.html
│       ├── customer_form.html
│       ├── customer_detail.html           # Con historial de facturas
│       ├── customer_confirm_delete.html
│       ├── invoice_list.html
│       ├── invoice_form.html              # Formulario dinámico con JavaScript
│       ├── invoice_detail.html
│       └── invoice_confirm_delete.html
│
├── purchasing/                  # App de compras
│   ├── __init__.py
│   ├── admin.py                 # Admin con PurchaseDetailInline
│   ├── apps.py
│   ├── models.py                # Purchase y PurchaseDetail
│   ├── forms.py                 # PurchaseForm y PurchaseDetailFormSet
│   ├── views.py                 # Vistas FBV
│   ├── urls.py                  # Rutas (app_name = 'purchasing')
│   ├── migrations/
│   │   ├── 0001_initial.py
│   │   └── 0002_purchase_unique_purchase_per_supplier.py
│   └── templates/purchasing/
│       ├── purchase_list.html
│       ├── purchase_form.html           # Productos filtrados por proveedor
│       ├── purchase_detail.html
│       ├── purchase_confirm_delete.html
│       └── purchase_report.html         # Reporte costo promedio
│
├── shared/                      # Módulo reutilizable entre apps
│   ├── __init__.py
│   ├── mixins.py                # StaffRequiredMixin
│   ├── decorators.py            # @audit_action
│   └── validators.py            # validate_cedula_ec
│
├── templates/                   # Plantillas globales
│   └── registration/
│       ├── login.html
│       └── signup.html
│
└── media/                       # Archivos subidos por usuarios
    ├── no-image.png             # Imagen placeholder
    └── products/                # Imágenes de productos
```

---

## Apps del proyecto

### config/
Carpeta de configuración principal. No es una app en sí misma.

- **settings.py** — configuración del proyecto: base de datos SQLite, apps instaladas, rutas de templates, configuración de archivos media, URLs de login/logout, validadores de contraseña e idioma (`es-ec`).
- **urls.py** — rutas principales: `''` incluye `billing.urls`, `'purchases/'` incluye `purchasing.urls`, `'accounts/'` incluye autenticación de Django y `/admin/` para el panel administrativo. También configura el servicio de archivos media en desarrollo.

### billing/
App principal del sistema. Gestiona todo el ciclo de ventas.

- **models.py** — define 8 modelos: Brand, ProductGroup, Supplier, Product (con `last_cost` y propiedades `inventory_value` y `margin`), Customer, CustomerProfile, Invoice, InvoiceDetail.
- **forms.py** — SignUpForm (registro con Bootstrap), BrandForm, InvoiceForm, InvoiceDetailFormSet (formset dinámico), ProductForm (con validación de precio > 0).
- **views.py** — mezcla de FBV (Brand, Invoice, buscadores) y CBV (ProductGroup, Supplier, Product, Customer con CreateView, UpdateView, DeleteView, DetailView). Incluye exportación PDF/Excel, paginación, filtros avanzados y actualización de stock al facturar.
- **export_mixins.py** — clase `ExportMixin` reutilizable que genera Excel (openpyxl) y PDF (reportlab) de cualquier queryset.

### purchasing/
App del módulo de compras. Reutiliza modelos de billing.

- **models.py** — importa `Supplier` y `Product` de `billing.models`. Define `Purchase` (cabecera con FK a Supplier, número de documento, totales) y `PurchaseDetail` (líneas con `unit_cost` en vez de `unit_price`). Incluye `UniqueConstraint` para evitar duplicar el número de documento por proveedor.
- **forms.py** — `PurchaseForm` con supplier y document_number. `PurchaseDetailFormSet` con `inlineformset_factory`.
- **views.py** — FBV: `purchase_list` (con filtros), `purchase_create` (suma stock y actualiza `last_cost`), `purchase_detail`, `purchase_delete`, `purchase_report` (con `annotate` y `aggregate`).

### shared/
Módulo transversal reutilizable por cualquier app.

- **mixins.py** — `StaffRequiredMixin`: verifica que el usuario tenga `is_staff=True` antes de permitir eliminar registros. Aplicado en ProductGroupDeleteView, SupplierDeleteView, ProductDeleteView y CustomerDeleteView.
- **decorators.py** — `@audit_action('NOMBRE')`: registra en consola el usuario, acción, método HTTP, ruta e IP. Aplicado en todas las vistas de Brand.
- **validators.py** — `validate_cedula_ec`: valida cédula ecuatoriana (10 dígitos) o RUC (13 dígitos) con el algoritmo oficial del Registro Civil.

---

## Modelos de datos

### Brand (Marca)
| Campo | Tipo | Descripción |
|---|---|---|
| name | CharField(100, unique) | Nombre de la marca |
| description | TextField | Descripción opcional |
| is_active | BooleanField | Estado activo/inactivo |
| created_at | DateTimeField(auto_now_add) | Fecha de creación |
| updated_at | DateTimeField(auto_now) | Última actualización |

### ProductGroup (Grupo de productos)
| Campo | Tipo | Descripción |
|---|---|---|
| name | CharField(100, unique) | Nombre del grupo |
| is_active | BooleanField | Estado |
| created_at / updated_at | DateTimeField | Auditoría |

### Supplier (Proveedor)
| Campo | Tipo | Descripción |
|---|---|---|
| name | CharField(200) | Nombre de la empresa |
| contact_name | CharField | Contacto |
| email | EmailField | Correo |
| phone | CharField(20) | Teléfono |
| address | TextField | Dirección |
| is_active | BooleanField | Estado |

### Product (Producto)
| Campo | Tipo | Descripción |
|---|---|---|
| name | CharField(200) | Nombre |
| brand | ForeignKey → Brand | Marca (PROTECT) |
| group | ForeignKey → ProductGroup | Grupo (PROTECT) |
| suppliers | ManyToManyField → Supplier | Proveedores |
| unit_price | DecimalField(12,2) | Precio de venta |
| last_cost | DecimalField(12,2) | Último costo de compra |
| stock | IntegerField | Unidades en inventario |
| image | ImageField | Foto del producto |
| is_active | BooleanField | Estado |

Propiedades: `inventory_value` (stock × precio) y `margin` (% ganancia).

### Customer (Cliente)
| Campo | Tipo | Descripción |
|---|---|---|
| dni | CharField(13, unique) | Cédula/RUC validado |
| first_name / last_name | CharField | Nombres |
| email / phone / address | — | Datos de contacto |
| is_active | BooleanField | Estado |

### Invoice (Factura)
| Campo | Tipo | Descripción |
|---|---|---|
| customer | ForeignKey → Customer | Cliente (PROTECT) |
| invoice_date | DateTimeField(auto) | Fecha de emisión |
| subtotal / tax / total | DecimalField | Totales calculados |

### Purchase (Compra)
| Campo | Tipo | Descripción |
|---|---|---|
| supplier | ForeignKey → Supplier | Proveedor (PROTECT) |
| document_number | CharField(20) | N° factura del proveedor |
| subtotal / tax / total | DecimalField | Totales |

Restricción: `document_number` único por `supplier`.

---

## Funcionalidades

### Autenticación
- Login / Logout con protección CSRF
- Registro de usuarios con inicio de sesión automático
- Todas las vistas protegidas con `@login_required` o `LoginRequiredMixin`
- Eliminación protegida con `StaffRequiredMixin` (requiere `is_staff=True`)

### Dashboard
- Conteo de marcas, productos, clientes y facturas
- 5 facturas más recientes
- Alerta de productos con stock bajo (≤ 5 unidades)

### Buscadores y Filtros
Todos los módulos tienen barra de búsqueda y filtros avanzados que se mantienen al paginar.

### Paginación
10 registros por página con navegación completa que conserva los filtros.

### Exportación
Botones PDF y Excel en cada listado que exportan los registros filtrados actualmente.

### Facturación Dinámica
- Precio cargado automáticamente al seleccionar producto
- Precio no editable (protegido)
- Cálculo en tiempo real de subtotales, IVA y total
- Stock baja al confirmar la factura
- Validación de stock suficiente antes de guardar

### Módulo de Compras
- Productos filtrados por proveedor seleccionado
- Stock sube al registrar una compra
- `last_cost` actualizado automáticamente
- Margen de ganancia calculado y visible en el listado
- Reporte de costo promedio por producto

---

## URLs del sistema

### Autenticación
| URL | Descripción |
|---|---|
| `/accounts/login/` | Iniciar sesión |
| `/accounts/logout/` | Cerrar sesión |
| `/signup/` | Registro |
| `/admin/` | Panel Django |

### Billing
| URL | Descripción |
|---|---|
| `/` | Dashboard |
| `/brands/` | Listado de marcas |
| `/brands/create/` | Crear marca |
| `/brands/<id>/edit/` | Editar |
| `/brands/<id>/delete/` | Eliminar |
| `/groups/` | Listado de grupos |
| `/groups/create/` | Crear grupo |
| `/groups/<id>/edit/` | Editar |
| `/groups/<id>/delete/` | Eliminar |
| `/suppliers/` | Listado de proveedores |
| `/suppliers/create/` | Crear proveedor |
| `/suppliers/<id>/` | Detalle |
| `/suppliers/<id>/edit/` | Editar |
| `/suppliers/<id>/delete/` | Eliminar |
| `/products/` | Listado de productos |
| `/products/create/` | Crear producto |
| `/products/<id>/` | Detalle |
| `/products/<id>/edit/` | Editar |
| `/products/<id>/delete/` | Eliminar |
| `/customers/` | Listado de clientes |
| `/customers/create/` | Crear cliente |
| `/customers/<id>/` | Detalle |
| `/customers/<id>/edit/` | Editar |
| `/customers/<id>/delete/` | Eliminar |
| `/invoices/` | Listado de facturas |
| `/invoices/create/` | Crear factura |
| `/invoices/<id>/` | Detalle |
| `/invoices/<id>/delete/` | Eliminar |

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

### StaffRequiredMixin
Protege las vistas de eliminación para usuarios staff solamente.

```python
class ProductDeleteView(LoginRequiredMixin, StaffRequiredMixin, DeleteView):
    model = Product
    staff_redirect_url = '/products/'
```

### @audit_action
Registra en consola cada acción sobre las vistas de Brand.

```python
@login_required
@audit_action('CREATE_BRAND')
def brand_create(request):
    ...
```

### validate_cedula_ec
Valida cédula ecuatoriana o RUC con el algoritmo oficial.

```python
dni = models.CharField(max_length=13, validators=[validate_cedula_ec])
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

| Tecnología | Versión | Uso |
|---|---|---|
| Python | 3.14 | Lenguaje principal |
| Django | 6.0.6 | Framework web |
| SQLite | — | Base de datos |
| Bootstrap | 5.3 | Estilos UI |
| JavaScript | ES6 | Formularios dinámicos |
| Pillow | 12.2.0 | Imágenes |
| openpyxl | 3.1.5 | Exportación Excel |
| reportlab | 4.5.1 | Exportación PDF |
| django-extensions | 4.1 | shell_plus |

---

*Desarrollado para la asignatura de Programación / Desarrollo Web con Python (Django) · 4to Semestre · Universidad Estatal de Milagro (UNEMI)*# sales-project
