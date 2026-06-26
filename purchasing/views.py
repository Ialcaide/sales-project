from django.shortcuts import render

# Create your views here.
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from decimal import Decimal
from billing.models import Product
from .models import Purchase, PurchaseDetail
from .forms import PurchaseForm, PurchaseDetailFormSet

@login_required
def purchase_report(request):
    from django.db.models import Avg, Sum, Count
    report = PurchaseDetail.objects.values(
        'product__name'
    ).annotate(
        avg_cost=Avg('unit_cost'),
        total_quantity=Sum('quantity'),
        total_purchases=Count('purchase'),
    ).order_by('product__name')

    return render(request, 'purchasing/purchase_report.html', {'report': report})

@login_required
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

@login_required
def purchase_create(request):
    import json
    if request.method == 'POST':
        form = PurchaseForm(request.POST)
        formset = PurchaseDetailFormSet(request.POST)
        if form.is_valid() and formset.is_valid():
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
    else:
        form = PurchaseForm()
        formset = PurchaseDetailFormSet()

    # Productos agrupados por proveedor
    from billing.models import Supplier, Product
    suppliers_products = {}
    for supplier in Supplier.objects.filter(is_active=True):
        suppliers_products[supplier.id] = [
            {'id': p.id, 'name': p.name, 'cost': float(p.last_cost) if p.last_cost else 0}
            for p in supplier.products.filter(is_active=True)
        ]

    return render(request, 'purchasing/purchase_form.html', {
        'form': form,
        'formset': formset,
        'title': 'Nueva Compra',
        'suppliers_products_json': json.dumps(suppliers_products),
    })


@login_required
def purchase_detail(request, pk):
    purchase = get_object_or_404(
        Purchase.objects.select_related('supplier').prefetch_related('details__product'),
        pk=pk
    )
    return render(request, 'purchasing/purchase_detail.html', {'purchase': purchase})


@login_required
def purchase_delete(request, pk):
    purchase = get_object_or_404(Purchase, pk=pk)
    if request.method == 'POST':
        purchase_id = purchase.id
        purchase.delete()
        messages.success(request, f'Compra #{purchase_id} eliminada!')
        return redirect('purchasing:purchase_list')
    return render(request, 'purchasing/purchase_confirm_delete.html', {'object': purchase})

@login_required
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