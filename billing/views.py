from django.conf import settings
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import ListView, CreateView, UpdateView, DeleteView, DetailView
from django.urls import reverse_lazy, reverse
from django.contrib.auth import login
from django.http import JsonResponse
from .models import * #el astericos importa todo(cuando se que trabajare con todos los que esta en esa clase)
from .forms import SignUpForm, BrandForm, InvoiceForm, InvoiceDetailFormSet, ProductForm, CustomerQuickCreateForm, SupplierQuickCreateForm
from decimal import Decimal
from django.core.paginator import Paginator
from .export_mixins import ExportMixin
from django.db import models
from django.utils import timezone
from shared.mixins import PermissionRequiredRedirectMixin
from shared.decorators import audit_action, permission_required_redirect
from shared.notifications import send_email_with_attachments, send_whatsapp_message, send_credentials_email, get_admin_recipients
from caja.models import SesionCaja, MovimientoCaja
from configuracion.models import ConfiguracionSistema, EmpresaFacturacionElectronica
from notificaciones.services import notificar_stock_bajo
from shared.pagination import build_extra_qs, get_page_range

# Este archivo mezcla dos estilos de vista a propósito, para que veas ambos:
#
# - Vistas por FUNCIÓN (FBV, ej. brand_list, invoice_create): una función
#   normal de Python que recibe `request` y devuelve una respuesta. Más
#   explícitas, buenas para lógica particular (ej. invoice_create, que
#   valida stock y arma la factura paso a paso).
#
# - Vistas por CLASE (CBV, ej. ProductCreateView): heredan de clases
#   genéricas de Django (CreateView/UpdateView/DeleteView/DetailView) que ya
#   traen el CRUD resuelto — con 5-6 líneas alcanza. Mejor para el caso común
#   "formulario que crea/edita/borra un modelo", como Product/Customer/Supplier.
#
# TODAS las vistas que modifican datos están protegidas con el permiso
# Django real del modelo correspondiente (permission_required /
# @permission_required_redirect) — ver la sección "Sistema de Roles y
# Permisos" del README para el porqué.

@login_required
def home(request):
    from django.db.models import Count
    total_brands = Brand.objects.count()
    total_products = Product.objects.count()
    total_customers = Customer.objects.count()
    total_invoices = Invoice.objects.count()
    recent_invoices = Invoice.objects.select_related('customer').order_by('-invoice_date')[:5]
    low_stock = Product.objects.filter(stock__lte=5).order_by('stock')
    context = {
        'total_brands': total_brands,
        'total_products': total_products,
        'total_customers': total_customers,
        'total_invoices': total_invoices,
        'recent_invoices': recent_invoices,
        'low_stock': low_stock,
    }
    return render(request, 'billing/home.html', context)

# === REGISTRO ===
# NOTA: SignUpView es un flujo de auto-registro público que ya NO está
# enlazado desde ningún template del sistema (ver la nota en forms.py sobre
# SignUpForm). El alta real de usuarios es security.views.RegisterView.
class SignUpView(CreateView):
    form_class = SignUpForm
    template_name = 'registration/signup.html'
    success_url = reverse_lazy('billing:brand_list')
    def form_valid(self, form):
        response = super().form_valid(form)
        login(self.request, self.object)
        return response


# === BRAND (FBV) ===
# brand_list es el ejemplo más simple de "listado con filtros, exportación y
# paginación" — el mismo esqueleto se repite en productgroup_list,
# supplier_list, product_list, customer_list e invoice_list más abajo (y en
# purchasing/views.py -> purchase_list). Una vez que entiendes este, entiendes
# todos: 1) leer filtros de la URL (?q=...&is_active=...), 2) aplicar
# .filter() al queryset solo si el filtro viene en la URL, 3) si piden
# exportar, cortar acá y devolver el PDF/Excel, 4) paginar lo que sobra,
# 5) renderizar el template con todo listo.
@permission_required_redirect('billing.access_brand_module', '/')
@audit_action('LIST_BRANDS')  # registra en consola quién listó marcas y cuándo
def brand_list(request):
    query = request.GET.get('q', '')
    is_active = request.GET.get('is_active', '')
    export = request.GET.get('export', '')

    brands = Brand.objects.all()

    if query:
        brands = brands.filter(name__icontains=query)
    if is_active == '1':
        brands = brands.filter(is_active=True)
    elif is_active == '0':
        brands = brands.filter(is_active=False)

    if export in ('pdf', 'excel'):
        if not request.user.has_perm(f'billing.export_{export}_brand'):
            messages.error(request, 'No tienes permiso para exportar este listado.')
        else:
            exporter = ExportMixin()
            exporter.export_filename = 'marcas'
            exporter.export_title = 'Listado de Marcas'
            exporter.export_headers = ['Nombre', 'Descripción', 'Activo', 'Creado']
            exporter.get_export_rows = lambda qs: [
                [
                    b.name,
                    b.description or '-',
                    'Sí' if b.is_active else 'No',
                    b.created_at.strftime('%d/%m/%Y'),
                ]
                for b in qs
            ]
            if export == 'pdf':
                return exporter.export_to_pdf(brands)
            else:
                return exporter.export_to_excel(brands)

    paginator = Paginator(brands, 10)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    context = {
        'page_obj': page_obj,
        'page_range': get_page_range(page_obj),
        'extra_qs': build_extra_qs(request),
        'query': query,
        'is_active': is_active,
    }
    return render(request, 'billing/brand_list.html', context)

@permission_required_redirect('billing.add_brand', '/brands/')
@audit_action('CREATE_BRAND')
def brand_create(request):
    if request.method == 'POST':
        form = BrandForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'Brand created!')
            return redirect('billing:brand_list')
    else: form = BrandForm()
    return render(request, 'billing/brand_form.html', {'form':form, 'title':'Crear marca'})

@permission_required_redirect('billing.change_brand', '/brands/')
@audit_action('UPDATE_BRAND')
def brand_update(request, pk):
    brand = get_object_or_404(Brand, pk=pk)
    if request.method == 'POST':
        form = BrandForm(request.POST, instance=brand)
        if form.is_valid():
            form.save()
            messages.success(request, 'Brand updated!')
            return redirect('billing:brand_list')
    else: form = BrandForm(instance=brand)
    return render(request, 'billing/brand_form.html', {'form':form, 'title':'Ediatr Marca'})

@permission_required_redirect('billing.view_brand', '/brands/')
def brand_detail(request, pk):
    brand = get_object_or_404(Brand, pk=pk)
    return render(request, 'billing/brand_detail.html', {'brand': brand})


@permission_required_redirect('billing.delete_brand', '/brands/')
@audit_action('DELETE_BRAND')
def brand_delete(request, pk):
    brand = get_object_or_404(Brand, pk=pk)
    if request.method == 'POST':
        brand.delete()
        messages.success(request, 'Marca borrada!')
        return redirect('billing:brand_list')
    return render(request, 'billing/brand_confirm_delete.html', {'object': brand})

# Clase sin usar (quedó de un intento anterior de convertir el listado a
# CBV): no tiene 'model' ni 'template_name', y ninguna URL la referencia — la
# que de verdad se usa es la función productgroup_list de abajo. Se deja
# como referencia de que "ListView" también existiría como opción para un
# listado, aunque acá se optó por la función.
class ProductGroupListView(LoginRequiredMixin, ListView):
    pass


@permission_required_redirect('billing.access_productgroup_module', '/')
def productgroup_list(request):
    query = request.GET.get('q', '')
    is_active = request.GET.get('is_active', '')
    export = request.GET.get('export', '')

    items = ProductGroup.objects.all()

    if query:
        items = items.filter(name__icontains=query)
    if is_active == '1':
        items = items.filter(is_active=True)
    elif is_active == '0':
        items = items.filter(is_active=False)

    if export in ('pdf', 'excel'):
        if not request.user.has_perm(f'billing.export_{export}_productgroup'):
            messages.error(request, 'No tienes permiso para exportar este listado.')
        else:
            exporter = ExportMixin()
            exporter.export_filename = 'grupos'
            exporter.export_title = 'Listado de Grupos'
            exporter.export_headers = ['Nombre', 'Activo', 'Creado']
            exporter.get_export_rows = lambda qs: [
                [
                    g.name,
                    'Sí' if g.is_active else 'No',
                    g.created_at.strftime('%d/%m/%Y'),
                ]
                for g in qs
            ]
            if export == 'pdf':
                return exporter.export_to_pdf(items)
            else:
                return exporter.export_to_excel(items)

    paginator = Paginator(items, 10)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    context = {
        'page_obj': page_obj,
        'page_range': get_page_range(page_obj),
        'extra_qs': build_extra_qs(request),
        'query': query,
        'is_active': is_active,
    }
    return render(request, 'billing/productgroup_list.html', context)

# A partir de acá, el patrón CBV que se repite para ProductGroup, Supplier,
# Product y Customer: una clase por acción (Create/Update/Delete/Detail),
# 'model' + 'fields' (o 'form_class' si el formulario está en forms.py) le
# dicen a Django qué mostrar, y 'permission_required' qué permiso exigir.
# LoginRequiredMixin va SIEMPRE primero en la herencia (si no hay sesión,
# redirige al login antes de siquiera revisar el permiso).
class ProductGroupCreateView(LoginRequiredMixin, PermissionRequiredRedirectMixin, CreateView):
    model = ProductGroup
    fields = ['name', 'is_active']
    template_name = 'billing/productgroup_form.html'
    success_url = reverse_lazy('billing:productgroup_list')
    permission_required = 'billing.add_productgroup'
    permission_redirect_url = '/groups/'

class ProductGroupUpdateView(LoginRequiredMixin, PermissionRequiredRedirectMixin, UpdateView):
    model = ProductGroup
    fields = ['name', 'is_active']
    template_name = 'billing/productgroup_form.html'
    success_url = reverse_lazy('billing:productgroup_list')
    permission_required = 'billing.change_productgroup'
    permission_redirect_url = '/groups/'

class ProductGroupDeleteView(LoginRequiredMixin, PermissionRequiredRedirectMixin, DeleteView):
    model = ProductGroup
    template_name = 'billing/productgroup_confirm_delete.html'
    success_url = reverse_lazy('billing:productgroup_list')
    permission_required = 'billing.delete_productgroup'
    permission_redirect_url = '/groups/'

class ProductGroupDetailView(LoginRequiredMixin, PermissionRequiredRedirectMixin, DetailView):
    model = ProductGroup
    template_name = 'billing/productgroup_detail.html'
    context_object_name = 'group'
    permission_required = 'billing.view_productgroup'
    permission_redirect_url = '/groups/'

@permission_required_redirect('billing.access_supplier_module', '/')
def supplier_list(request):
    query = request.GET.get('q', '')
    is_active = request.GET.get('is_active', '')
    export = request.GET.get('export', '')

    items = Supplier.objects.all()

    if query:
        items = items.filter(
            models.Q(name__icontains=query) |
            models.Q(contact_name__icontains=query) |
            models.Q(email__icontains=query)
        )
    if is_active == '1':
        items = items.filter(is_active=True)
    elif is_active == '0':
        items = items.filter(is_active=False)

    if export in ('pdf', 'excel'):
        if not request.user.has_perm(f'billing.export_{export}_supplier'):
            messages.error(request, 'No tienes permiso para exportar este listado.')
        else:
            exporter = ExportMixin()
            exporter.export_filename = 'proveedores'
            exporter.export_title = 'Listado de Proveedores'
            exporter.export_headers = ['Nombre', 'Contacto', 'Correo', 'Teléfono', 'Activo']
            exporter.get_export_rows = lambda qs: [
                [
                    s.name,
                    s.contact_name or '-',
                    s.email or '-',
                    s.phone or '-',
                    'Sí' if s.is_active else 'No',
                ]
                for s in qs
            ]
            if export == 'pdf':
                return exporter.export_to_pdf(items)
            else:
                return exporter.export_to_excel(items)

    paginator = Paginator(items, 10)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    context = {
        'page_obj': page_obj,
        'page_range': get_page_range(page_obj),
        'extra_qs': build_extra_qs(request),
        'query': query,
        'is_active': is_active,
    }
    return render(request, 'billing/supplier_list.html', context)

class SupplierCreateView(LoginRequiredMixin, PermissionRequiredRedirectMixin, CreateView):
    model = Supplier
    fields = ['name', 'contact_name', 'email', 'phone', 'address', 'is_active']
    template_name = 'billing/supplier_form.html'
    success_url = reverse_lazy('billing:supplier_list')
    permission_required = 'billing.add_supplier'
    permission_redirect_url = '/suppliers/'

    def form_valid(self, form):
        response = super().form_valid(form)
        supplier = self.object
        for admin_nombre, admin_email in get_admin_recipients():
            send_credentials_email(
                admin_email, f'Nuevo proveedor registrado — {supplier.name}',
                (
                    f'Hola {admin_nombre},\n\n'
                    f'Se registró un nuevo proveedor en el sistema: {supplier.name}.\n\n'
                    f'Atentamente,\n'
                    f'Sistema de Ventas TecnoStock'
                ),
                html_template='nuevo_proveedor_registrado.html',
                html_context={
                    'admin_nombre': admin_nombre, 'proveedor_nombre': supplier.name,
                    'proveedor_telefono': supplier.phone,
                    'fecha': timezone.now().strftime('%d/%m/%Y %H:%M'),
                    'proveedor_url': f'{settings.SITE_URL}{reverse("billing:supplier_detail", args=[supplier.pk])}',
                },
            )
        return response

class SupplierUpdateView(LoginRequiredMixin, PermissionRequiredRedirectMixin, UpdateView):
    model = Supplier
    fields = ['name', 'contact_name', 'email', 'phone', 'address', 'is_active']
    template_name = 'billing/supplier_form.html'
    success_url = reverse_lazy('billing:supplier_list')
    permission_required = 'billing.change_supplier'
    permission_redirect_url = '/suppliers/'

class SupplierDeleteView(LoginRequiredMixin, PermissionRequiredRedirectMixin, DeleteView):
    model = Supplier
    template_name = 'billing/supplier_confirm_delete.html'
    success_url = reverse_lazy('billing:supplier_list')
    permission_required = 'billing.delete_supplier'
    permission_redirect_url = '/suppliers/'

class SupplierDetailView(LoginRequiredMixin, PermissionRequiredRedirectMixin, DetailView):
    model = Supplier
    template_name = 'billing/supplier_detail.html'
    context_object_name = 'supplier'
    permission_required = 'billing.view_supplier'
    permission_redirect_url = '/suppliers/'

class ProductDetailView(LoginRequiredMixin, PermissionRequiredRedirectMixin, DetailView):
    model = Product
    template_name = 'billing/product_detail.html'
    context_object_name = 'product'
    permission_required = 'billing.view_product'
    permission_redirect_url = '/products/'

@permission_required_redirect('billing.access_product_module', '/')
def product_list(request):
    query = request.GET.get('q', '')
    brand_id = request.GET.get('brand', '')
    group_id = request.GET.get('group', '')
    supplier_id = request.GET.get('supplier', '')
    min_price = request.GET.get('min_price', '')
    max_price = request.GET.get('max_price', '')
    stock_status = request.GET.get('stock_status', '')
    is_active = request.GET.get('is_active', '')

    items = Product.objects.select_related('brand', 'group').prefetch_related('suppliers').all()

    if query:
        items = items.filter(
            models.Q(name__icontains=query) |
            models.Q(description__icontains=query) |
            models.Q(barcode__icontains=query)
        )
    if brand_id:
        items = items.filter(brand_id=brand_id)
    if group_id:
        items = items.filter(group_id=group_id)
    if supplier_id:
        items = items.filter(suppliers__id=supplier_id)
    if min_price:
        items = items.filter(unit_price__gte=min_price)
    if max_price:
        items = items.filter(unit_price__lte=max_price)
    if stock_status == 'out':
        items = items.filter(stock=0)
    elif stock_status == 'low':
        items = items.filter(stock__gt=0, stock__lte=10)
    elif stock_status == 'available':
        items = items.filter(stock__gt=0)
    if is_active == '1':
        items = items.filter(is_active=True)
    elif is_active == '0':
        items = items.filter(is_active=False)

    items = items.distinct()

    export = request.GET.get('export', '')

    if export in ('pdf', 'excel'):
        if not request.user.has_perm(f'billing.export_{export}_product'):
            messages.error(request, 'No tienes permiso para exportar este listado.')
        else:
            exporter = ExportMixin()
            exporter.export_filename = 'productos'
            exporter.export_title = 'Listado de Productos'
            exporter.export_headers = ['Nombre', 'Marca', 'Grupo', 'Precio', 'Stock', 'Proveedores', 'Activo']
            exporter.get_export_rows = lambda qs: [
                [
                    p.name,
                    p.brand.name,
                    p.group.name,
                    f'${p.unit_price}',
                    p.stock,
                    ', '.join(s.name for s in p.suppliers.all()) or '-',
                    'Sí' if p.is_active else 'No',
                ]
                for p in qs
            ]
            if export == 'pdf':
                return exporter.export_to_pdf(items)
            else:
                return exporter.export_to_excel(items)

    paginator = Paginator(items, 10)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    context = {
        'page_obj': page_obj,
        'page_range': get_page_range(page_obj),
        'extra_qs': build_extra_qs(request),
        'query': query,
        'selected_brand': brand_id,
        'selected_group': group_id,
        'selected_supplier': supplier_id,
        'min_price': min_price,
        'max_price': max_price,
        'stock_status': stock_status,
        'is_active': is_active,
        'brands': Brand.objects.filter(is_active=True),
        'groups': ProductGroup.objects.filter(is_active=True),
        'suppliers': Supplier.objects.filter(is_active=True),
    }
    return render(request, 'billing/product_list.html', context)

class ProductCreateView(LoginRequiredMixin, PermissionRequiredRedirectMixin, CreateView):
    model = Product
    form_class = ProductForm
    template_name = 'billing/product_form.html'
    success_url = reverse_lazy('billing:product_list')
    permission_required = 'billing.add_product'
    permission_redirect_url = '/products/'

class ProductUpdateView(LoginRequiredMixin, PermissionRequiredRedirectMixin, UpdateView):
    model = Product
    form_class = ProductForm
    template_name = 'billing/product_form.html'
    success_url = reverse_lazy('billing:product_list')
    permission_required = 'billing.change_product'
    permission_redirect_url = '/products/'

class ProductDeleteView(LoginRequiredMixin, PermissionRequiredRedirectMixin, DeleteView):
    model = Product
    template_name = 'billing/product_confirm_delete.html'
    success_url = reverse_lazy('billing:product_list')
    permission_required = 'billing.delete_product'
    permission_redirect_url = '/products/'

@permission_required_redirect('billing.access_customer_module', '/')
def customer_list(request):
    query = request.GET.get('q', '')
    is_active = request.GET.get('is_active', '')
    export = request.GET.get('export', '')

    items = Customer.objects.all()

    if query:
        items = items.filter(
            models.Q(first_name__icontains=query) |
            models.Q(last_name__icontains=query) |
            models.Q(dni__icontains=query) |
            models.Q(email__icontains=query)
        )
    if is_active == '1':
        items = items.filter(is_active=True)
    elif is_active == '0':
        items = items.filter(is_active=False)

    if export in ('pdf', 'excel'):
        if not request.user.has_perm(f'billing.export_{export}_customer'):
            messages.error(request, 'No tienes permiso para exportar este listado.')
        else:
            exporter = ExportMixin()
            exporter.export_filename = 'clientes'
            exporter.export_title = 'Listado de Clientes'
            exporter.export_headers = ['Cédula/RUC', 'Apellido', 'Nombre', 'Correo', 'Teléfono', 'Activo']
            exporter.get_export_rows = lambda qs: [
                [
                    c.dni,
                    c.last_name,
                    c.first_name,
                    c.email or '-',
                    c.phone or '-',
                    'Sí' if c.is_active else 'No',
                ]
                for c in qs
            ]
            if export == 'pdf':
                return exporter.export_to_pdf(items)
            else:
                return exporter.export_to_excel(items)

    paginator = Paginator(items, 10)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    context = {
        'page_obj': page_obj,
        'page_range': get_page_range(page_obj),
        'extra_qs': build_extra_qs(request),
        'query': query,
        'is_active': is_active,
    }
    return render(request, 'billing/customer_list.html', context)

class CustomerCreateView(LoginRequiredMixin, PermissionRequiredRedirectMixin, CreateView):
    model = Customer
    fields = ['tipo_identificacion', 'dni', 'first_name', 'last_name', 'email', 'phone', 'address', 'is_active']
    template_name = 'billing/customer_form.html'
    success_url = reverse_lazy('billing:customer_list')
    permission_required = 'billing.add_customer'
    permission_redirect_url = '/customers/'

    def form_valid(self, form):
        response = super().form_valid(form)
        customer = self.object
        for admin_nombre, admin_email in get_admin_recipients():
            send_credentials_email(
                admin_email, f'Nuevo cliente registrado — {customer.full_name}',
                (
                    f'Hola {admin_nombre},\n\n'
                    f'Se registró un nuevo cliente en el sistema: {customer.full_name}.\n\n'
                    f'Atentamente,\n'
                    f'Sistema de Ventas TecnoStock'
                ),
                html_template='nuevo_cliente_registrado.html',
                html_context={
                    'admin_nombre': admin_nombre, 'cliente_nombre': customer.full_name,
                    'cliente_dni': customer.dni, 'cliente_email': customer.email,
                    'fecha': timezone.now().strftime('%d/%m/%Y %H:%M'),
                    'cliente_url': f'{settings.SITE_URL}{reverse("billing:customer_detail", args=[customer.pk])}',
                },
            )
        return response

@permission_required_redirect('billing.add_customer', '/invoices/create/')
def customer_quick_create(request):
    """
    Alta rápida de cliente desde el modal del paso 1 del wizard de factura
    (ver invoice-wizard.js) — responde JSON en vez de redirigir, para que el
    cliente nuevo se pueda inyectar en el <select> de invoice_form.html SIN
    recargar la página ni perder el resto del wizard ya llenado.
    """
    if request.method != 'POST':
        return JsonResponse({'ok': False, 'errors': {'__all__': ['Método no permitido.']}}, status=405)

    form = CustomerQuickCreateForm(request.POST)
    if not form.is_valid():
        return JsonResponse({'ok': False, 'errors': form.errors}, status=400)

    customer = form.save()
    return JsonResponse({
        'ok': True,
        'customer': {
            'id': customer.id,
            'label': customer.full_name,
            'dni': customer.dni,
            'tipo_identificacion': customer.tipo_identificacion,
            'first_name': customer.first_name,
            'last_name': customer.last_name,
            'email': customer.email or '',
            'phone': customer.phone or '',
            'address': customer.address or '',
            'credito_disponible': float(customer.credito_disponible()),
        },
    }, status=201)

@permission_required_redirect('billing.add_supplier', '/suppliers/')
def supplier_quick_create(request):
    """
    Alta rápida de proveedor desde el modal del paso 1 del wizard de compra
    (ver purchase-wizard.js) — mismo patrón exacto que customer_quick_create
    de arriba: responde JSON en vez de redirigir, para inyectar el proveedor
    nuevo en el <select> de purchase_form.html sin recargar la página.
    """
    if request.method != 'POST':
        return JsonResponse({'ok': False, 'errors': {'__all__': ['Método no permitido.']}}, status=405)

    form = SupplierQuickCreateForm(request.POST)
    if not form.is_valid():
        return JsonResponse({'ok': False, 'errors': form.errors}, status=400)

    supplier = form.save()
    return JsonResponse({
        'ok': True,
        'supplier': {
            'id': supplier.id,
            'label': supplier.name,
            'name': supplier.name,
            'contact_name': supplier.contact_name or '',
            'email': supplier.email or '',
            'phone': supplier.phone or '',
            'address': supplier.address or '',
        },
    }, status=201)


class CustomerUpdateView(LoginRequiredMixin, PermissionRequiredRedirectMixin, UpdateView):
    model = Customer
    fields = ['tipo_identificacion', 'dni', 'first_name', 'last_name', 'email', 'phone', 'address', 'is_active']
    template_name = 'billing/customer_form.html'
    success_url = reverse_lazy('billing:customer_list')
    permission_required = 'billing.change_customer'
    permission_redirect_url = '/customers/'

class CustomerDeleteView(LoginRequiredMixin, PermissionRequiredRedirectMixin, DeleteView):
    model = Customer
    template_name = 'billing/customer_confirm_delete.html'
    success_url = reverse_lazy('billing:customer_list')
    permission_required = 'billing.delete_customer'
    permission_redirect_url = '/customers/'

class CustomerDetailView(LoginRequiredMixin, PermissionRequiredRedirectMixin, DetailView):
    model = Customer
    template_name = 'billing/customer_detail.html'
    context_object_name = 'customer'
    permission_required = 'billing.view_customer'
    permission_redirect_url = '/customers/'

@permission_required_redirect('billing.access_invoice_module', '/')
def invoice_list(request):
    query = request.GET.get('q', '')
    date_from = request.GET.get('date_from', '')
    date_to = request.GET.get('date_to', '')
    min_total = request.GET.get('min_total', '')
    max_total = request.GET.get('max_total', '')
    export = request.GET.get('export', '')

    invoices = Invoice.objects.select_related('customer').all()

    if query:
        invoices = invoices.filter(
            models.Q(customer__first_name__icontains=query) |
            models.Q(customer__last_name__icontains=query) |
            models.Q(customer__dni__icontains=query)
        )
    if date_from:
        invoices = invoices.filter(invoice_date__date__gte=date_from)
    if date_to:
        invoices = invoices.filter(invoice_date__date__lte=date_to)
    if min_total:
        invoices = invoices.filter(total__gte=min_total)
    if max_total:
        invoices = invoices.filter(total__lte=max_total)

    if export in ('pdf', 'excel'):
        if not request.user.has_perm(f'billing.export_{export}_invoice'):
            messages.error(request, 'No tienes permiso para exportar este listado.')
        else:
            exporter = ExportMixin()
            exporter.export_filename = 'facturas'
            exporter.export_title = 'Listado de Facturas'
            exporter.export_headers = ['#', 'Cliente', 'Fecha', 'Subtotal', 'IVA', 'Total']
            exporter.get_export_rows = lambda qs: [
                [
                    inv.id,
                    str(inv.customer),
                    inv.invoice_date.strftime('%d/%m/%Y'),
                    f'${inv.subtotal}',
                    f'${inv.tax}',
                    f'${inv.total}',
                ]
                for inv in qs
            ]
            if export == 'pdf':
                return exporter.export_to_pdf(invoices)
            else:
                return exporter.export_to_excel(invoices)

    paginator = Paginator(invoices, 10)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    context = {
        'page_obj': page_obj,
        'page_range': get_page_range(page_obj),
        'extra_qs': build_extra_qs(request),
        'query': query,
        'date_from': date_from,
        'date_to': date_to,
        'min_total': min_total,
        'max_total': max_total,
    }
    return render(request, 'billing/invoice_list.html', context)

# La vista más compleja del proyecto: crea una factura con VARIAS líneas de
# producto a la vez (usa InvoiceDetailFormSet), valida stock, y al confirmar
# descuenta el inventario. Vale la pena leerla completa una vez para entender
# el patrón "formulario + formset" que se repite en purchasing/views.py
# -> purchase_create con la misma estructura.
@permission_required_redirect('billing.add_invoice', '/invoices/')
def invoice_create(request):
    import json

    # products_data/customers_data se mandan como JSON al template para que
    # el JavaScript del formulario pueda autocompletar precio/stock al elegir
    # un producto, SIN pedirle nada al servidor (todo pasa en el navegador).
    # Ver billing/templates/billing/invoice_form.html.
    products_data = {
        p.id: {
            'price': float(p.unit_price), 'stock': p.stock, 'name': p.name, 'barcode': p.barcode or '',
            'brand': p.brand.name if p.brand_id else '',
            'image_url': p.image.url if p.image else p.placeholder_image,
        }
        for p in Product.objects.filter(is_active=True)
    }
    customers_data = {
        c.id: {'dni': c.dni, 'tipo_identificacion': c.tipo_identificacion,
               'first_name': c.first_name, 'last_name': c.last_name,
               'email': c.email or '', 'phone': c.phone or '', 'address': c.address or '',
               'credito_disponible': float(c.credito_disponible())}
        for c in Customer.objects.filter(is_active=True)
    }

    context_base = {
        'title': 'Crear Factura',
        'products_json': json.dumps(products_data),
        'customers_json': json.dumps(customers_data),
        # IVA real y configurable (ver configuracion/models.py) para que el
        # resumen de totales en el paso 2/3 del wizard (invoice-wizard.js)
        # coincida con el cálculo real del servidor — antes estaba
        # hardcodeado a 0.15 en el JS, desincronizado de este valor.
        'iva_fraccion_json': json.dumps(float(ConfiguracionSistema.get_solo().iva_fraccion)),
    }

    if request.method == 'POST':
        form = InvoiceForm(request.POST)          # el cliente
        formset = InvoiceDetailFormSet(request.POST)  # las líneas (producto/cantidad/precio)

        # form.is_valid() y formset.is_valid() solo revisan tipos/campos
        # obligatorios (ej. "cantidad debe ser un número"). Las reglas de
        # NEGOCIO (cliente activo, no repetir producto, stock suficiente) se
        # revisan a mano después, porque dependen de otros datos (el estado
        # actual del Customer/Product en la base) que un ModelForm no conoce.
        if form.is_valid() and formset.is_valid():

            # Validar cliente activo
            customer = form.cleaned_data.get('customer')
            if customer and not customer.is_active:
                messages.error(request, f'El cliente {customer.full_name} está inactivo.')
                return render(request, 'billing/invoice_form.html', {
                    **context_base, 'form': form, 'formset': formset
                })

            # Validar al menos un producto
            productos_validos = [
                f for f in formset
                if f.cleaned_data and not f.cleaned_data.get('DELETE')
                and f.cleaned_data.get('product')
            ]
            if not productos_validos:
                messages.error(request, 'La factura debe tener al menos un producto.')
                return render(request, 'billing/invoice_form.html', {
                    **context_base, 'form': form, 'formset': formset
                })

            # Validar productos duplicados y stock
            productos_ids = []
            for detail_form in formset:
                if detail_form.cleaned_data and not detail_form.cleaned_data.get('DELETE'):
                    product = detail_form.cleaned_data.get('product')
                    quantity = detail_form.cleaned_data.get('quantity', 0)
                    if product:
                        if product.id in productos_ids:
                            messages.error(request, f'El producto "{product.name}" está duplicado.')
                            return render(request, 'billing/invoice_form.html', {
                                **context_base, 'form': form, 'formset': formset
                            })
                        productos_ids.append(product.id)
                        if quantity > product.stock:
                            messages.error(request, f'Stock insuficiente para "{product.name}". Disponible: {product.stock}')
                            return render(request, 'billing/invoice_form.html', {
                                **context_base, 'form': form, 'formset': formset
                            })

            # Total proyectado en memoria (las líneas todavía no son
            # InvoiceDetail reales) — lo usan tanto el chequeo de crédito
            # (si es CREDITO) como la validación de monto recibido en
            # efectivo (si es EFECTIVO, que solo aplica al CONTADO, ver
            # Invoice.clean(), así que acá nunca lleva interés).
            proyectado_subtotal = sum(
                f.cleaned_data.get('quantity', 0) * f.cleaned_data.get('unit_price', 0)
                for f in productos_validos
            )
            # IVA configurable (ver configuracion/models.py) — antes estaba
            # hardcodeado a 1.15 acá, desincronizado del cálculo real de abajo.
            iva_fraccion = ConfiguracionSistema.get_solo().iva_fraccion
            proyectado_total = (proyectado_subtotal * (1 + iva_fraccion)).quantize(Decimal('0.01'))

            # Validar crédito disponible del cliente ANTES de guardar nada.
            if customer and form.cleaned_data.get('tipo_pago') == Invoice.CREDITO:
                # Si se difiere a meses, el interés también se proyecta —
                # si no, el chequeo de crédito subestimaría lo que la
                # factura realmente le va a deber al cliente.
                meses_credito_proyectado = form.cleaned_data.get('meses_credito')
                proyectado_total_credito = proyectado_total
                if meses_credito_proyectado:
                    interes_proyectado = (
                        proyectado_total_credito * Invoice.tasa_interes(meses_credito_proyectado)
                    ).quantize(Decimal('0.01'))
                    proyectado_total_credito += interes_proyectado
                disponible = customer.credito_disponible()
                if proyectado_total_credito > disponible:
                    messages.error(
                        request,
                        f'{customer.full_name} no tiene crédito disponible suficiente '
                        f'(disponible: ${disponible:.2f}, requerido: ${proyectado_total_credito:.2f}).'
                    )
                    return render(request, 'billing/invoice_form.html', {
                        **context_base, 'form': form, 'formset': formset
                    })

            # Una venta en EFECTIVO o TARJETA exige que el vendedor/cajero
            # tenga una caja abierta (venta de mostrador durante un turno de
            # caja) — así se puede ligar el ingreso a una sesión real (ver
            # caja/models.py -> SesionCaja). Solo EFECTIVO exige además saber
            # cuánto dinero entregó el cliente para calcular el cambio;
            # TARJETA es dinero que nunca entra físicamente a la caja (va a
            # un datáfono externo), así que no genera MovimientoCaja (ver
            # _finalizar_venta) pero igual necesita la caja abierta como
            # prerequisito de la venta.
            forma_pago = form.cleaned_data.get('forma_pago')
            monto_recibido = form.cleaned_data.get('monto_recibido')
            if forma_pago in (Invoice.EFECTIVO, Invoice.TARJETA):
                tiene_caja_abierta = SesionCaja.objects.filter(
                    usuario=request.user, estado=SesionCaja.ABIERTA
                ).exists()
                if not tiene_caja_abierta:
                    messages.error(
                        request,
                        f'Debes abrir una caja antes de registrar una venta en {dict(Invoice.FORMA_PAGO_CHOICES)[forma_pago].lower()}.'
                    )
                    return render(request, 'billing/invoice_form.html', {
                        **context_base, 'form': form, 'formset': formset
                    })
                if forma_pago == Invoice.EFECTIVO:
                    if monto_recibido is None:
                        messages.error(
                            request,
                            'Indica cuánto dinero te entregó el cliente para calcular el cambio.'
                        )
                        return render(request, 'billing/invoice_form.html', {
                            **context_base, 'form': form, 'formset': formset
                        })
                    if monto_recibido < proyectado_total:
                        messages.error(
                            request,
                            f'El monto recibido (${monto_recibido}) no puede ser menor al total de la factura (${proyectado_total}).'
                        )
                        return render(request, 'billing/invoice_form.html', {
                            **context_base, 'form': form, 'formset': formset
                        })
                    tarjeta_titular = tarjeta_cvv = tarjeta_expiracion = None
                else:
                    monto_recibido = None
                    # Ya validados por InvoiceForm.clean() (requeridos +
                    # formato + fecha no vencida) — acá solo se leen los
                    # valores limpios para pasarlos a _finalizar_venta.
                    tarjeta_titular = form.cleaned_data.get('tarjeta_titular')
                    tarjeta_cvv = form.cleaned_data.get('tarjeta_cvv')
                    tarjeta_expiracion = form.cleaned_data.get('tarjeta_expiracion')
            else:
                monto_recibido = None
                tarjeta_titular = tarjeta_cvv = tarjeta_expiracion = None

            # PAYPAL es distinto a las otras formas de pago: el pago se
            # confirma de forma ASÍNCRONA (el navegador sale a paypal.com y
            # vuelve), así que acá NO se crea la Invoice todavía — se crea
            # una orden en PayPal y se redirige al checkout. La Invoice real
            # recién se crea cuando el pago se captura de verdad (ver
            # paypal_pagos/views.py -> paypal_return / paypal_webhook, que
            # llaman a _finalizar_venta() igual que el camino síncrono de acá abajo).
            if forma_pago == Invoice.PAYPAL:
                from paypal_pagos.client import PayPalError
                from paypal_pagos.services import crear_orden_venta

                # Igual que efectivo/tarjeta: se exige caja abierta ANTES de
                # iniciar el checkout de PayPal (no después, cuando ya se
                # capturó el pago — en ese punto la venta ya no se puede
                # rechazar sin dejar un cobro real sin factura asociada).
                tiene_caja_abierta = SesionCaja.objects.filter(
                    usuario=request.user, estado=SesionCaja.ABIERTA
                ).exists()
                if not tiene_caja_abierta:
                    messages.error(request, 'Debes abrir una caja antes de registrar una venta con paypal.')
                    return render(request, 'billing/invoice_form.html', {
                        **context_base, 'form': form, 'formset': formset
                    })

                lineas = [
                    {'product_id': f.cleaned_data['product'].id, 'quantity': f.cleaned_data['quantity'],
                     'unit_price': str(f.cleaned_data['unit_price'])}
                    for f in productos_validos
                ]
                datos_venta = {
                    'customer_id': customer.id, 'tipo_pago': form.cleaned_data.get('tipo_pago'), 'lineas': lineas,
                }
                try:
                    orden = crear_orden_venta(datos_venta, request.user)
                except PayPalError as e:
                    messages.error(request, str(e))
                    return render(request, 'billing/invoice_form.html', {
                        **context_base, 'form': form, 'formset': formset
                    })
                return redirect(orden.approval_url)

            lineas = [
                {'product': f.cleaned_data['product'], 'quantity': f.cleaned_data['quantity'],
                 'unit_price': f.cleaned_data['unit_price']}
                for f in productos_validos
            ]
            invoice, email_enviado = _finalizar_venta(
                customer, form.cleaned_data.get('tipo_pago'), forma_pago, lineas, request.user,
                meses_credito=form.cleaned_data.get('meses_credito'), monto_recibido=monto_recibido,
                tarjeta_titular=tarjeta_titular, tarjeta_cvv=tarjeta_cvv,
                tarjeta_expiracion=tarjeta_expiracion,
            )

            cambio_msg = f' Cambio a devolver: ${invoice.cambio}.' if invoice.cambio is not None else ''

            # Estado del comprobante electrónico (SRI) — generarlo es "best
            # effort" (ver _finalizar_venta), así que puede no existir del
            # todo (config de SRI inválida) sin que eso afecte la venta.
            comprobante = getattr(invoice, 'comprobante_electronico', None)
            if comprobante is None:
                sri_msg = ''
            elif comprobante.estado == comprobante.AUTORIZADO:
                sri_msg = f' Autorizada por el SRI (N° {comprobante.numero_autorizacion}).'
            elif comprobante.estado == comprobante.ERROR:
                sri_msg = ' No se pudo generar el comprobante electrónico (ver el detalle de la factura).'
            else:
                sri_msg = f' Comprobante electrónico: {comprobante.get_estado_display()}.'

            if invoice.customer.es_consumidor_final:
                messages.success(request, f'Factura #{invoice.id} creada! Total: ${invoice.total}.{cambio_msg}{sri_msg} Venta a Consumidor Final, no se envía PDF por correo.')
            elif invoice.customer.email:
                if email_enviado:
                    messages.success(request, f'Factura #{invoice.id} creada! Total: ${invoice.total}.{cambio_msg}{sri_msg} PDF enviado a {invoice.customer.email}.')
                else:
                    messages.warning(request, f'Factura #{invoice.id} creada! Total: ${invoice.total}.{cambio_msg}{sri_msg} No se pudo enviar el PDF por correo.')
            else:
                messages.success(request, f'Factura #{invoice.id} creada! Total: ${invoice.total}.{cambio_msg}{sri_msg} El cliente no tiene correo registrado, no se envió el PDF.')

            return redirect('billing:invoice_list')

    else:
        form = InvoiceForm()
        formset = InvoiceDetailFormSet()

    return render(request, 'billing/invoice_form.html', {
        **context_base,
        'form': form,
        'formset': formset,
    })


# Nombre/RUC/dirección a mostrar como emisor en el PDF y el correo de la
# factura de venta: los de la empresa activa en Facturación Electrónica (la
# que realmente firma esta misma factura ante el SRI vía
# facturacion_electronica.services._payload_desde_invoice), para que el
# membrete de la factura nunca contradiga a quien la firmó. Si todavía no
# hay ninguna empresa conectada, cae a los datos generales de
# ConfiguracionSistema — evita una factura en blanco antes de conectar la
# primera empresa, cuando no hay ninguna firma electrónica en juego.
def _datos_emisor(config):
    empresa = EmpresaFacturacionElectronica.get_activa()
    if empresa is None:
        return config.empresa_nombre, config.empresa_ruc, config.empresa_direccion
    return empresa.razon_social, empresa.ruc, empresa.direccion_matriz


# Qué documento mostrar/descargar/adjuntar para una factura: el RIDE REAL
# del SRI (vía el microservicio) si el comprobante electrónico ya está
# AUTORIZADO — es el comprobante legal de esa venta, no tiene sentido
# seguir mostrando el PDF armado acá en paralelo. Para cualquier otro caso
# (sin comprobante, comprobante en un estado no definitivo, o la empresa
# activa no tiene facturación electrónica conectada) se sigue usando
# _build_invoice_pdf como respaldo — el sistema no puede depender de que el
# SRI/microservicio estén funcionando para poder facturar. Si el
# comprobante SÍ está autorizado pero el microservicio no puede entregar el
# RIDE justo en este momento (best effort, mismo criterio que el resto de
# la integración SRI), también cae al PDF local en vez de fallar.
def _documento_factura(invoice):
    comprobante = getattr(invoice, 'comprobante_electronico', None)
    if comprobante is not None:
        from facturacion_electronica.models import ComprobanteElectronico
        if comprobante.estado == ComprobanteElectronico.AUTORIZADO:
            from facturacion_electronica.ride import build_ride_pdf
            from facturacion_electronica.services import SRIError
            try:
                return build_ride_pdf(comprobante), f'ride_{invoice.id:04d}.pdf', True
            except SRIError:
                pass
    return _build_invoice_pdf(invoice), f'factura_{invoice.id:04d}.pdf', False


# Crea la Invoice real + sus InvoiceDetail, baja stock, calcula totales,
# dispara la notificación de stock bajo, registra el ingreso en caja (si
# aplica) y envía el comprobante por correo/WhatsApp. `lineas` es una lista
# de dicts {'product', 'quantity', 'unit_price'} ya validados por el caller.
# Devuelve (invoice, email_enviado).
#
# La usa tanto el camino síncrono de invoice_create (efectivo/tarjeta,
# arriba) como paypal_pagos.services.finalizar_orden (una vez
# que PayPal confirma el pago) — así los dos caminos comparten exactamente
# la misma lógica de negocio en vez de duplicarla.
def _finalizar_venta(
    customer, tipo_pago, forma_pago, lineas, usuario, meses_credito=None, monto_recibido=None,
    tarjeta_titular=None, tarjeta_cvv=None, tarjeta_expiracion=None,
):
    # EFECTIVO y TARJETA comparten sesión de caja abierta (venta de
    # mostrador) — solo EFECTIVO genera un MovimientoCaja más abajo, porque
    # es la única que mueve dinero físico dentro de la caja.
    sesion_caja = None
    if forma_pago in (Invoice.EFECTIVO, Invoice.TARJETA):
        sesion_caja = SesionCaja.objects.filter(usuario=usuario, estado=SesionCaja.ABIERTA).first()

    invoice = Invoice(
        customer=customer, tipo_pago=tipo_pago, forma_pago=forma_pago, meses_credito=meses_credito,
        monto_recibido=monto_recibido, tarjeta_titular=tarjeta_titular,
        tarjeta_cvv=tarjeta_cvv, tarjeta_expiracion=tarjeta_expiracion,
    )
    invoice.save()
    for linea in lineas:
        InvoiceDetail.objects.create(
            invoice=invoice, product=linea['product'],
            quantity=linea['quantity'], unit_price=linea['unit_price'],
        )

    # Bajar stock: por cada línea de la factura, resta la cantidad vendida
    # del stock del producto. Ya se validó arriba que hay stock suficiente,
    # pero igual se frena en 0 por seguridad.
    for detail in invoice.details.all():
        product = detail.product
        product.stock -= detail.quantity
        if product.stock < 0:
            product.stock = 0
        product.save()
        notificar_stock_bajo(product)

    # Los totales se calculan DESPUÉS de guardar las líneas (recién ahí
    # existen y tienen su subtotal calculado por InvoiceDetail.save()).
    config = ConfiguracionSistema.get_solo()
    subtotal = sum(d.subtotal for d in invoice.details.all())
    invoice.subtotal = subtotal
    # Multiplicar dos Decimal suma sus decimales (2 + 2 = 4); sin quantize,
    # el total en memoria mostraría "$115.0000" hasta el próximo refresh_from_db().
    invoice.tax = (subtotal * config.iva_fraccion).quantize(Decimal('0.01'))
    invoice.total = invoice.subtotal + invoice.tax
    invoice.aplicar_tipo_pago()
    invoice.save()

    # Facturación electrónica (SRI): automática y "best effort" — un fallo
    # acá (SRI caído, certificado mal configurado en el .env, red lenta)
    # NUNCA debe revertir ni bloquear la venta ya completada, mismo criterio
    # que el correo/WhatsApp más abajo. Se guarda el comprobante devuelto
    # (no solo se llama) porque el correo de abajo le adjunta el RIDE/XML si
    # se generó. Ver facturacion_electronica/services.py -> generar_y_enviar_comprobante().
    from facturacion_electronica.services import generar_y_enviar_comprobante
    comprobante = generar_y_enviar_comprobante(invoice)

    # Venta en efectivo -> ingreso automático a la caja abierta del vendedor
    # (MovimientoCaja.save() ya valida que la sesión siga ABIERTA, ver
    # caja/models.py). Si por alguna razón la caja se cerró entre la
    # validación de invoice_create y acá, sesion_caja queda None y
    # simplemente no se registra el movimiento — no bloquea la venta.
    # TARJETA exige caja abierta (arriba) pero NO genera movimiento: el
    # dinero no entra físicamente a la caja, va a un datáfono externo.
    if sesion_caja and forma_pago == Invoice.EFECTIVO:
        MovimientoCaja.objects.create(
            sesion=sesion_caja, tipo=MovimientoCaja.INGRESO,
            monto=invoice.total, concepto=f'Venta factura #{invoice.id:04d}',
            invoice=invoice,
        )

    # Enviar automáticamente el documento de la factura al correo del
    # cliente, junto con el XML del comprobante electrónico si el SRI ya lo
    # generó (best effort: si la parte SRI falló del todo, `comprobante`
    # queda None y el correo sale igual, solo con el PDF local). El
    # documento en sí (PDF local o RIDE real) lo decide _documento_factura
    # — mismo criterio que usa invoice_pdf para la descarga manual, así el
    # diseño del comprobante no se duplica en dos lugares. Consumidor Final
    # nunca recibe correo (es una venta anónima de mostrador).
    email_enviado = False
    if invoice.customer.email and not invoice.customer.es_consumidor_final:
        pdf_bytes, nombre_pdf, es_ride = _documento_factura(invoice)
        adjuntos = [(nombre_pdf, pdf_bytes, 'application/pdf')]
        detalle_sri = ''
        if comprobante is not None:
            xml = comprobante.xml_autorizado or comprobante.xml_firmado or comprobante.xml_generado
            if xml:
                adjuntos.append((f'factura_sri_{invoice.id:04d}.xml', xml.encode('utf-8'), 'application/xml'))
                detalle_sri = (
                    ' El PDF adjunto es tu comprobante electrónico autorizado por el SRI (RIDE); también '
                    'adjuntamos su XML.' if es_ride
                    else ' También adjuntamos el XML de tu comprobante electrónico del SRI.'
                )
        razon_social_emisor = _datos_emisor(config)[0]
        subject = f'Tu factura #{invoice.id:04d} — {razon_social_emisor}'
        body = (
            f'Estimado/a {invoice.customer.full_name},\n\n'
            f'Adjuntamos el PDF de tu factura #{invoice.id:04d} por un total de ${invoice.total}.'
            f'{detalle_sri}\n\n'
            f'Gracias por tu compra.\n\n'
            f'Atentamente,\n'
            f'{razon_social_emisor}'
        )
        productos_ctx = [
            {'nombre': d.product.name, 'cantidad': d.quantity, 'subtotal': f'${d.subtotal}'}
            for d in invoice.details.all()
        ]
        # OJO: no se pasa factura_url — invoice_detail es una vista interna
        # protegida por permiso, y el cliente no es un usuario del sistema
        # (no tiene con qué iniciar sesión para verla); el PDF ya va adjunto acá.
        email_enviado = send_email_with_attachments(
            invoice.customer.email, subject, body, adjuntos,
            html_template='confirmacion_compra.html',
            html_context={
                'usuario': invoice.customer.full_name, 'factura_numero': f'{invoice.id:04d}',
                'fecha': invoice.invoice_date.strftime('%d/%m/%Y %H:%M'),
                'metodo_pago': invoice.get_forma_pago_display() or invoice.get_tipo_pago_display(),
                'productos': productos_ctx, 'subtotal': f'${invoice.subtotal}', 'iva': f'${invoice.tax}',
                'total': f'${invoice.total}',
            },
        )

    # WhatsApp: mismo criterio que el correo (nunca a Consumidor Final),
    # pero es "best effort" — no cambia nada del resto del flujo si falla o
    # no hay teléfono.
    if invoice.customer.phone and not invoice.customer.es_consumidor_final:
        whatsapp_body = (
            f'{config.empresa_nombre} — Factura #{invoice.id:04d}\n'
            f'Total: ${invoice.total}. ¡Gracias por tu compra!'
        )
        send_whatsapp_message(invoice.customer.phone, whatsapp_body)

    return invoice, email_enviado


@permission_required_redirect('billing.view_invoice', '/invoices/')
def invoice_detail(request, pk):
    invoice = get_object_or_404(
        Invoice.objects.select_related('customer').prefetch_related('details__product'),
        pk=pk
    )
    return render(request, 'billing/invoice_detail.html', {'invoice': invoice})
    
# Arma los bytes del PDF de una factura y los devuelve (sin HttpResponse
# todavía) — así el mismo PDF sirve tanto para la descarga manual
# (invoice_pdf) como para adjuntarlo al correo automático al crear la
# factura (invoice_create más abajo), sin duplicar todo este código dos veces.
def _build_invoice_pdf(invoice):
    from reportlab.lib.pagesizes import letter
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib import colors
    from reportlab.lib.units import cm
    import io

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter,
        topMargin=2*cm, bottomMargin=2*cm,
        leftMargin=2*cm, rightMargin=2*cm)

    styles = getSampleStyleSheet()
    story = []

    # Header
    title_style = ParagraphStyle('title', parent=styles['Normal'],
        fontSize=22, fontName='Helvetica-Bold',
        textColor=colors.HexColor('#4e54c8'), spaceAfter=4)
    sub_style = ParagraphStyle('sub', parent=styles['Normal'],
        fontSize=9, textColor=colors.HexColor('#94a3b8'), spaceAfter=2)
    normal = ParagraphStyle('normal', parent=styles['Normal'],
        fontSize=9, textColor=colors.HexColor('#334155'), spaceAfter=2)
    bold = ParagraphStyle('bold', parent=styles['Normal'],
        fontSize=9, fontName='Helvetica-Bold',
        textColor=colors.HexColor('#334155'), spaceAfter=2)

    config = ConfiguracionSistema.get_solo()
    razon_social_emisor, ruc_emisor, direccion_emisor = _datos_emisor(config)
    story.append(Paragraph(razon_social_emisor, title_style))
    story.append(Paragraph('Sistema de Ventas y Facturación', sub_style))
    datos_empresa = ' | '.join(
        d for d in [ruc_emisor and f'RUC: {ruc_emisor}', direccion_emisor, config.empresa_telefono] if d
    )
    if datos_empresa:
        story.append(Paragraph(datos_empresa, sub_style))
    story.append(HRFlowable(width='100%', thickness=1, color=colors.HexColor('#e2e8f0')))
    story.append(Spacer(1, 0.3*cm))

    # Info factura y cliente
    info_data = [
        [Paragraph('<b>FACTURA</b>', ParagraphStyle('', parent=styles['Normal'], fontSize=14, fontName='Helvetica-Bold', textColor=colors.HexColor('#4e54c8'))),
         Paragraph(f'<b>Factura N°:</b> {invoice.id:04d}', bold)],
        ['', Paragraph(f'<b>Fecha:</b> {invoice.invoice_date.strftime("%d/%m/%Y %H:%M")}', normal)],
        [Paragraph('<b>Cliente:</b>', bold), Paragraph(f'{invoice.customer.full_name}', normal)],
        [Paragraph('<b>Cédula/RUC:</b>', bold), Paragraph(f'{invoice.customer.dni}', normal)],
        [Paragraph('<b>Correo:</b>', bold), Paragraph(f'{invoice.customer.email or "-"}', normal)],
        [Paragraph('<b>Teléfono:</b>', bold), Paragraph(f'{invoice.customer.phone or "-"}', normal)],
    ]
    info_table = Table(info_data, colWidths=[8*cm, 9*cm])
    info_table.setStyle(TableStyle([
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('TOPPADDING', (0,0), (-1,-1), 3),
        ('BOTTOMPADDING', (0,0), (-1,-1), 3),
    ]))
    story.append(info_table)
    story.append(Spacer(1, 0.4*cm))
    story.append(HRFlowable(width='100%', thickness=1, color=colors.HexColor('#e2e8f0')))
    story.append(Spacer(1, 0.3*cm))

    # Tabla de productos
    headers = ['Producto', 'Cantidad', 'Precio Unitario', 'Subtotal']
    rows = [headers]
    for d in invoice.details.all():
        rows.append([
            d.product.name,
            str(d.quantity),
            f'${d.unit_price}',
            f'${d.subtotal}',
        ])

    prod_table = Table(rows, colWidths=[9*cm, 2.5*cm, 3.5*cm, 3*cm])
    prod_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#4e54c8')),
        ('TEXTCOLOR', (0,0), (-1,0), colors.white),
        ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
        ('FONTSIZE', (0,0), (-1,-1), 9),
        ('ALIGN', (1,0), (-1,-1), 'CENTER'),
        ('ALIGN', (2,0), (-1,-1), 'RIGHT'),
        ('ALIGN', (3,0), (-1,-1), 'RIGHT'),
        ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.white, colors.HexColor('#f8fafc')]),
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#e2e8f0')),
        ('TOPPADDING', (0,0), (-1,-1), 8),
        ('BOTTOMPADDING', (0,0), (-1,-1), 8),
        ('LEFTPADDING', (0,0), (-1,-1), 8),
    ]))
    story.append(prod_table)
    story.append(Spacer(1, 0.4*cm))

    # Totales
    totales_data = [
        ['', 'Subtotal:', f'${invoice.subtotal}'],
        ['', f'IVA ({config.iva_porcentaje}%):', f'${invoice.tax}'],
        ['', 'TOTAL:', f'${invoice.total}'],
    ]
    totales_table = Table(totales_data, colWidths=[9*cm, 4*cm, 5*cm])
    totales_table.setStyle(TableStyle([
        ('ALIGN', (1,0), (-1,-1), 'RIGHT'),
        ('FONTNAME', (1,2), (-1,2), 'Helvetica-Bold'),
        ('FONTSIZE', (0,0), (-1,-1), 9),
        ('FONTSIZE', (1,2), (-1,2), 11),
        ('TEXTCOLOR', (1,2), (-1,2), colors.HexColor('#4e54c8')),
        ('TOPPADDING', (0,0), (-1,-1), 5),
        ('LINEABOVE', (1,2), (-1,2), 1.5, colors.HexColor('#4e54c8')),
    ]))
    story.append(totales_table)
    story.append(Spacer(1, 0.5*cm))
    story.append(HRFlowable(width='100%', thickness=1, color=colors.HexColor('#e2e8f0')))
    story.append(Spacer(1, 0.2*cm))
    story.append(Paragraph(f'Gracias por su compra — {razon_social_emisor}', sub_style))

    doc.build(story)
    buffer.seek(0)
    return buffer.getvalue()


@permission_required_redirect('billing.view_invoice', '/invoices/')
def invoice_pdf(request, pk):
    from django.http import HttpResponse

    invoice = get_object_or_404(
        Invoice.objects.select_related('customer').prefetch_related('details__product'),
        pk=pk
    )
    pdf_bytes, nombre_pdf, _es_ride = _documento_factura(invoice)
    response = HttpResponse(pdf_bytes, content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="{nombre_pdf}"'
    return response


# Dibuja el código de barras de un producto como PNG, en memoria (nunca se
# guarda en disco) — mismo espíritu que _build_invoice_pdf de arriba. Se usa
# como <img src="..."> tanto en product_detail.html/product_list.html como
# en la vista de impresión (product_barcode_print).
def _build_barcode_image(codigo):
    import io

    import barcode
    from barcode.writer import ImageWriter

    buffer = io.BytesIO()
    # barcode.get() recalcula su propio dígito verificador a partir de los
    # primeros 12 dígitos — coincide con el que ya guarda Product.barcode
    # porque usa el mismo algoritmo estándar EAN-13 (ver Product._generar_barcode).
    ean = barcode.get('ean13', codigo[:12], writer=ImageWriter())
    ean.write(buffer, options={'write_text': True})
    buffer.seek(0)
    return buffer.read()


@permission_required_redirect('billing.view_product', '/products/')
def product_barcode_image(request, pk):
    from django.http import HttpResponse

    product = get_object_or_404(Product, pk=pk)
    if not product.barcode:
        return HttpResponse(status=404)
    return HttpResponse(_build_barcode_image(product.barcode), content_type='image/png')


@permission_required_redirect('billing.view_product', '/products/')
def product_barcode_print(request, pk):
    product = get_object_or_404(Product, pk=pk)
    return render(request, 'billing/product_barcode_print.html', {'product': product})


@permission_required_redirect('billing.delete_invoice', '/invoices/')
def invoice_delete(request, pk):
    from django.db import models
    invoice = get_object_or_404(Invoice, pk=pk)
    if request.method == 'POST':
        # Al borrar una factura, hay que devolver al inventario lo que se
        # vendió — si no, el stock quedaría descontado para siempre aunque
        # la venta ya no exista.
        # Restaurar stock antes de eliminar
        for detail in invoice.details.all():
            product = detail.product
            product.stock += detail.quantity
            product.save()
        invoice_id = invoice.id
        try:
            invoice.delete()
        except models.deletion.ProtectedError:
            # La factura tiene un Comprobante Electrónico vinculado con FK PROTECT
            # — no se puede borrar físicamente sin eliminar primero el comprobante.
            # Revertimos el stock que ya sumamos para no dejarlo inflado.
            for detail in invoice.details.all():
                product = detail.product
                product.stock -= detail.quantity
                product.save()
            messages.error(
                request,
                f'No se puede eliminar la factura #{invoice_id:04d} porque tiene un '
                f'comprobante electrónico asociado. Para eliminarla, primero borra el '
                f'comprobante electrónico desde el panel de administración de Django.'
            )
            return redirect('billing:invoice_detail', pk=invoice.pk)
        messages.success(request, f'Factura #{invoice_id} eliminada y stock restaurado.')
        return redirect('billing:invoice_list')
    return render(request, 'billing/invoice_confirm_delete.html', {'object': invoice})


# Anulación real (soft-delete): a diferencia de invoice_delete (borrado
# físico, reservado a Administrador), esto solo marca is_active=False y
# restaura el stock — la factura sigue existiendo para historial/auditoría,
# pero deja de admitir cobros (ver cobros/models.py -> CobroFactura.clean()).
@permission_required_redirect('billing.change_invoice', '/invoices/')
def invoice_cancel(request, pk):
    from cobros.models import CobroFactura

    invoice = get_object_or_404(Invoice, pk=pk)

    if not invoice.is_active:
        messages.info(request, f'La factura #{invoice.id:04d} ya estaba anulada.')
        return redirect('billing:invoice_detail', pk=invoice.pk)

    if request.method == 'POST':
        if CobroFactura.objects.filter(factura=invoice).exists():
            messages.error(
                request,
                'No se puede anular una factura que ya tiene cobros registrados. '
                'Elimina primero esos cobros desde el historial de cobros.'
            )
            return redirect('billing:invoice_detail', pk=invoice.pk)

        for detail in invoice.details.all():
            product = detail.product
            product.stock += detail.quantity
            product.save()

        invoice.is_active = False
        invoice.save(update_fields=['is_active'])
        messages.success(request, f'Factura #{invoice.id:04d} anulada y stock restaurado.')
        return redirect('billing:invoice_list')

    return render(request, 'billing/invoice_confirm_cancel.html', {'object': invoice})