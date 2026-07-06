from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from billing.models import Brand, Product, Customer, Invoice, ProductGroup
from purchasing.models import Purchase
from django.db.models import Count
import json

def get_context(request):
    datos_grupos = ProductGroup.objects.annotate(total=Count('products')).order_by('-total')
    return {
        'total_brands': Brand.objects.count(),
        'total_products': Product.objects.count(),
        'total_customers': Customer.objects.count(),
        'total_invoices': Invoice.objects.count(),
        'total_purchases': Purchase.objects.count(),
        'total_users': User.objects.count(),
        'low_stock': Product.objects.filter(stock__lte=5).order_by('stock'),
        'recent_invoices': Invoice.objects.select_related('customer').order_by('-invoice_date')[:5],
        'labels': json.dumps([g.name for g in datos_grupos]),
        'data': json.dumps([g.total for g in datos_grupos]),
    }

@login_required
def home(request):
    context = get_context(request)
    user = request.user
    if user.is_superuser or user.groups.filter(name='Administrador').exists():
        template = 'home/home_admin.html'
    elif user.groups.filter(name='Vendedor').exists():
        template = 'home/home_vendedor.html'
    elif user.groups.filter(name='Analista de Compras').exists():
        template = 'home/home_compras.html'
    else:
        template = 'home/home_admin.html'
    return render(request, template, context)