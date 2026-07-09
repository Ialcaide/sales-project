from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import ListView, CreateView, UpdateView, DeleteView, DetailView
from django.urls import reverse_lazy
from django.contrib.auth import login
from .models import * #el astericos importa todo(cuando se que trabajare con todos los que esta en esa clase)
from .forms import SignUpForm, BrandForm, InvoiceForm, InvoiceDetailFormSet, ProductForm
from decimal import Decimal
from django.core.paginator import Paginator
from .export_mixins import ExportMixin
from django.db import models
from shared.mixins import PermissionRequiredRedirectMixin
from shared.decorators import audit_action, permission_required_redirect
from shared.notifications import send_email_with_attachment
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
@permission_required_redirect('billing.view_brand', '/')
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


@permission_required_redirect('billing.view_productgroup', '/')
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

@permission_required_redirect('billing.view_supplier', '/')
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

@permission_required_redirect('billing.view_product', '/')
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
            models.Q(description__icontains=query)
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

@permission_required_redirect('billing.view_customer', '/')
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
    fields = ['dni', 'first_name', 'last_name', 'email', 'phone', 'address', 'is_active']
    template_name = 'billing/customer_form.html'
    success_url = reverse_lazy('billing:customer_list')
    permission_required = 'billing.add_customer'
    permission_redirect_url = '/customers/'

class CustomerUpdateView(LoginRequiredMixin, PermissionRequiredRedirectMixin, UpdateView):
    model = Customer
    fields = ['dni', 'first_name', 'last_name', 'email', 'phone', 'address', 'is_active']
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

@permission_required_redirect('billing.view_invoice', '/')
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
        p.id: {'price': float(p.unit_price), 'stock': p.stock, 'name': p.name}
        for p in Product.objects.filter(is_active=True)
    }
    customers_data = {
        c.id: {'dni': c.dni, 'first_name': c.first_name, 'last_name': c.last_name,
               'email': c.email or '', 'phone': c.phone or '', 'address': c.address or ''}
        for c in Customer.objects.filter(is_active=True)
    }

    context_base = {
        'title': 'Crear Factura',
        'products_json': json.dumps(products_data),
        'customers_json': json.dumps(customers_data),
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

            # commit=False: crea el objeto Invoice en memoria SIN guardarlo
            # todavía en la base de datos. Se necesita así porque el formset
            # (las líneas) requiere que la factura YA tenga un id (invoice.save())
            # antes de poder asociarle las líneas (formset.instance = invoice).
            invoice = form.save(commit=False)
            invoice.save()
            formset.instance = invoice
            formset.save()  # ahora sí crea cada InvoiceDetail, ligado a esta invoice

            # Bajar stock: por cada línea de la factura, resta la cantidad
            # vendida del stock del producto. Ya se validó arriba que hay
            # stock suficiente, pero igual se frena en 0 por seguridad.
            for detail in invoice.details.all():
                product = detail.product
                product.stock -= detail.quantity
                if product.stock < 0:
                    product.stock = 0
                product.save()

            # Los totales se calculan DESPUÉS de guardar las líneas (recién
            # ahí existen y tienen su subtotal calculado por
            # InvoiceDetail.save()). IVA fijo del 15%.
            subtotal = sum(d.subtotal for d in invoice.details.all())
            invoice.subtotal = subtotal
            invoice.tax = subtotal * Decimal('0.15')
            invoice.total = invoice.subtotal + invoice.tax
            invoice.save()

            # Enviar automáticamente el PDF de la factura al correo del
            # cliente. Se reutiliza _build_invoice_pdf (la misma función que
            # arma el PDF para la descarga manual en invoice_pdf) para no
            # duplicar el diseño del comprobante en dos lugares.
            if invoice.customer.email:
                pdf_bytes = _build_invoice_pdf(invoice)
                subject = f'Tu factura #{invoice.id:04d} — TecnoStock S.A.'
                body = (
                    f'Estimado/a {invoice.customer.full_name},\n\n'
                    f'Adjuntamos el PDF de tu factura #{invoice.id:04d} por un total de ${invoice.total}.\n\n'
                    f'Gracias por tu compra.\n\n'
                    f'Atentamente,\n'
                    f'TecnoStock S.A.'
                )
                sent = send_email_with_attachment(
                    invoice.customer.email, subject, body,
                    f'factura_{invoice.id:04d}.pdf', pdf_bytes,
                )
                if sent:
                    messages.success(request, f'Factura #{invoice.id} creada! Total: ${invoice.total}. PDF enviado a {invoice.customer.email}.')
                else:
                    messages.warning(request, f'Factura #{invoice.id} creada! Total: ${invoice.total}. No se pudo enviar el PDF por correo.')
            else:
                messages.success(request, f'Factura #{invoice.id} creada! Total: ${invoice.total}. El cliente no tiene correo registrado, no se envió el PDF.')

            return redirect('billing:invoice_list')

    else:
        form = InvoiceForm()
        formset = InvoiceDetailFormSet()

    return render(request, 'billing/invoice_form.html', {
        **context_base,
        'form': form,
        'formset': formset,
    })       
    
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

    story.append(Paragraph('TecnoStock S.A.', title_style))
    story.append(Paragraph('Sistema de Ventas y Facturación', sub_style))
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
        ['', 'IVA (15%):', f'${invoice.tax}'],
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
    story.append(Paragraph('Gracias por su compra — TecnoStock S.A.', sub_style))

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
    pdf_bytes = _build_invoice_pdf(invoice)
    response = HttpResponse(pdf_bytes, content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="factura_{invoice.id:04d}.pdf"'
    return response


@permission_required_redirect('billing.delete_invoice', '/invoices/')
def invoice_delete(request, pk):
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
        invoice.delete()
        messages.success(request, f'Factura #{invoice_id} eliminada y stock restaurado.')
        return redirect('billing:invoice_list')
    return render(request, 'billing/invoice_confirm_delete.html', {'object': invoice})