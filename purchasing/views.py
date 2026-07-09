from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from decimal import Decimal
from billing.models import Product
from shared.decorators import permission_required_redirect
from .models import Purchase, PurchaseDetail
from .forms import PurchaseForm, PurchaseDetailFormSet


@permission_required_redirect('purchasing.view_purchase', '/')
def purchase_list(request):
    from billing.models import Supplier
    query = request.GET.get('q', '')
    date_from = request.GET.get('date_from', '')
    date_to = request.GET.get('date_to', '')
    supplier_id = request.GET.get('supplier', '')

    purchases = Purchase.objects.select_related('supplier').all()

    if query:
        purchases = purchases.filter(document_number__icontains=query)
    if supplier_id:
        purchases = purchases.filter(supplier_id=supplier_id)
    if date_from:
        purchases = purchases.filter(purchase_date__date__gte=date_from)
    if date_to:
        purchases = purchases.filter(purchase_date__date__lte=date_to)

    context = {
        'items': purchases,
        'query': query,
        'date_from': date_from,
        'date_to': date_to,
        'selected_supplier': supplier_id,
        'suppliers': Supplier.objects.filter(is_active=True),
    }
    return render(request, 'purchasing/purchase_list.html', context)


@permission_required_redirect('purchasing.add_purchase', '/purchases/')
def purchase_create(request):
    import json
    from django.db import IntegrityError
    from billing.models import Supplier, Product

    suppliers_products = {}
    for supplier in Supplier.objects.filter(is_active=True):
        suppliers_products[supplier.id] = [
            {'id': p.id, 'name': p.name, 'cost': float(p.last_cost) if p.last_cost else 0}
            for p in supplier.products.filter(is_active=True)
        ]

    context_base = {
        'title': 'Nueva Compra',
        'suppliers_products_json': json.dumps(suppliers_products),
    }

    if request.method == 'POST':
        print("POST DATA:", dict(request.POST))
        form = PurchaseForm(request.POST)
        formset = PurchaseDetailFormSet(request.POST, instance=Purchase())
        print("form valid:", form.is_valid())
        print("formset valid:", formset.is_valid())
        print("formset errors:", formset.errors)
        for i, f in enumerate(formset.forms):
            print(f"form {i} cleaned_data:", getattr(f, 'cleaned_data', 'NO'))
            
        if form.is_valid() and formset.is_valid():

            # Validar proveedor activo
            supplier = form.cleaned_data.get('supplier')
            if supplier and not supplier.is_active:
                messages.error(request, f'El proveedor "{supplier.name}" está inactivo.')
                return render(request, 'purchasing/purchase_form.html', {
                    **context_base, 'form': form, 'formset': formset
                })

            # Validar al menos un producto
            productos_validos = [
                f for f in formset.forms
                if f.cleaned_data and not f.cleaned_data.get('DELETE')
                and f.cleaned_data.get('product')
            ]

            if not productos_validos:
                messages.error(request, 'La compra debe tener al menos un producto.')
                return render(request, 'purchasing/purchase_form.html', {
                    **context_base, 'form': form, 'formset': formset
                })

            # Validar duplicados, cantidad y costo
            productos_ids = []
            for detail_form in formset.forms:
                if detail_form.cleaned_data and not detail_form.cleaned_data.get('DELETE'):
                    product = detail_form.cleaned_data.get('product')
                    quantity = detail_form.cleaned_data.get('quantity') or 0
                    unit_cost = detail_form.cleaned_data.get('unit_cost') or 0
                    if product:
                        if product.id in productos_ids:
                            messages.error(request, f'El producto "{product.name}" está duplicado.')
                            return render(request, 'purchasing/purchase_form.html', {
                                **context_base, 'form': form, 'formset': formset
                            })
                        productos_ids.append(product.id)
                        if quantity <= 0:
                            messages.error(request, f'La cantidad de "{product.name}" debe ser mayor a 0.')
                            return render(request, 'purchasing/purchase_form.html', {
                                **context_base, 'form': form, 'formset': formset
                            })
                        if unit_cost <= 0:
                            messages.error(request, f'El costo de "{product.name}" debe ser mayor a 0.')
                            return render(request, 'purchasing/purchase_form.html', {
                                **context_base, 'form': form, 'formset': formset
                            })

            # Guardar
            try:
                purchase = form.save(commit=False)
                purchase.save()
                formset.instance = purchase
                formset.save()

                subtotal = sum(d.subtotal for d in purchase.details.all())
                purchase.subtotal = subtotal
                purchase.tax = subtotal * Decimal('0.15')
                purchase.total = purchase.subtotal + purchase.tax
                purchase.save()

                for detail in purchase.details.all():
                    product = detail.product
                    product.stock += detail.quantity
                    product.last_cost = detail.unit_cost
                    product.save()

                messages.success(request, f'Compra #{purchase.id} registrada! Total: ${purchase.total}')
                return redirect('purchasing:purchase_list')

            except IntegrityError:
                messages.error(request, 'Ya existe una compra con ese número de documento para este proveedor.')
            except Exception as e:
                import traceback
                traceback.print_exc()
                messages.error(request, f'Error al guardar: {str(e)}')

    else:
        form = PurchaseForm()
        formset = PurchaseDetailFormSet()

    return render(request, 'purchasing/purchase_form.html', {
        **context_base,
        'form': form,
        'formset': formset,
    })
    
    


@permission_required_redirect('purchasing.view_purchase', '/purchases/')
def purchase_detail(request, pk):
    purchase = get_object_or_404(
        Purchase.objects.select_related('supplier').prefetch_related('details__product'),
        pk=pk
    )
    return render(request, 'purchasing/purchase_detail.html', {'purchase': purchase})


@permission_required_redirect('purchasing.delete_purchase', '/purchases/')
def purchase_delete(request, pk):
    purchase = get_object_or_404(Purchase, pk=pk)
    if request.method == 'POST':
        purchase_id = purchase.id
        purchase.delete()
        messages.success(request, f'Compra #{purchase_id} eliminada!')
        return redirect('purchasing:purchase_list')
    return render(request, 'purchasing/purchase_confirm_delete.html', {'object': purchase})


@permission_required_redirect('purchasing.view_purchase', '/purchases/')
def purchase_report(request):
    from django.db.models import Avg, Sum, Count
    from billing.models import Supplier
    query = request.GET.get('q', '')
    supplier_id = request.GET.get('supplier', '')

    report = PurchaseDetail.objects.values(
        'product__name'
    ).annotate(
        avg_cost=Avg('unit_cost'),
        total_quantity=Sum('quantity'),
        total_purchases=Count('purchase'),
    ).order_by('product__name')

    if query:
        report = report.filter(product__name__icontains=query)
    if supplier_id:
        report = report.filter(purchase__supplier_id=supplier_id)

    context = {
        'report': report,
        'query': query,
        'selected_supplier': supplier_id,
        'suppliers': Supplier.objects.filter(is_active=True),
    }
    return render(request, 'purchasing/purchase_report.html', context)