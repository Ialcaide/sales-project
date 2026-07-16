from collections import defaultdict
from decimal import Decimal

from django.db.models import Count, F, Sum
from django.shortcuts import render
from django.utils import timezone
from django.utils.dateparse import parse_date

from billing.export_mixins import ExportMixin
from billing.models import Invoice, Product
from caja.models import SesionCaja
from purchasing.models import Purchase
from shared.decorators import permission_required_redirect


def _periodo(request):
    """Rango de fechas del filtro (?desde=&hasta=), default: mes actual.
    Mismo estilo que purchasing.purchase_report: strings simples de GET, sin
    forms.Form dedicado."""
    hoy = timezone.now().date()
    desde = parse_date(request.GET.get('desde', '')) or hoy.replace(day=1)
    hasta = parse_date(request.GET.get('hasta', '')) or hoy
    return desde, hasta


def _sum2(queryset, field):
    """Sum() sobre SQLite puede traer ruido de punto flotante en DecimalField
    (mismo problema ya documentado en billing/models.py y caja/models.py) —
    se redondea a 2 decimales."""
    total = queryset.aggregate(total=Sum(field))['total']
    return total.quantize(Decimal('0.01')) if total is not None else Decimal('0.00')


@permission_required_redirect('billing.view_invoice', '/')
def reporte_index(request):
    return render(request, 'reportes/reporte_index.html')


@permission_required_redirect('billing.view_invoice', '/')
def reporte_ventas(request):
    desde, hasta = _periodo(request)
    facturas = Invoice.objects.select_related('customer').filter(
        is_active=True, invoice_date__date__gte=desde, invoice_date__date__lte=hasta,
    ).order_by('-invoice_date')

    por_tipo_pago = facturas.values('tipo_pago').annotate(total=Sum('total'), cantidad=Count('id')).order_by('tipo_pago')
    por_forma_pago = facturas.exclude(forma_pago__isnull=True).exclude(forma_pago='').values(
        'forma_pago'
    ).annotate(total=Sum('total'), cantidad=Count('id')).order_by('forma_pago')

    export = request.GET.get('export', '')
    if export in ('pdf', 'excel'):
        exporter = ExportMixin()
        exporter.export_filename = f'reporte_ventas_{desde}_{hasta}'
        exporter.export_title = f'Reporte de Ventas ({desde} a {hasta})'
        exporter.export_headers = ['Factura', 'Fecha', 'Cliente', 'Tipo de Pago', 'Forma de Pago', 'Total']
        exporter.get_export_rows = lambda qs: [
            [
                f'#{f.id:04d}', f.invoice_date.strftime('%d/%m/%Y'), f.customer.full_name,
                f.get_tipo_pago_display(), f.get_forma_pago_display() if f.forma_pago else '-', f'${f.total}',
            ]
            for f in qs
        ]
        return exporter.export_to_pdf(facturas) if export == 'pdf' else exporter.export_to_excel(facturas)

    context = {
        'desde': desde, 'hasta': hasta,
        'facturas': facturas,
        'por_tipo_pago': por_tipo_pago,
        'por_forma_pago': por_forma_pago,
        'total_general': _sum2(facturas, 'total'),
    }
    return render(request, 'reportes/reporte_ventas.html', context)


@permission_required_redirect('purchasing.view_purchase', '/')
def reporte_compras(request):
    desde, hasta = _periodo(request)
    compras = Purchase.objects.select_related('supplier').filter(
        is_active=True, purchase_date__date__gte=desde, purchase_date__date__lte=hasta,
    ).order_by('-purchase_date')

    por_tipo_pago = compras.values('tipo_pago').annotate(total=Sum('total'), cantidad=Count('id')).order_by('tipo_pago')
    por_proveedor = compras.values('supplier__name').annotate(
        total=Sum('total'), cantidad=Count('id')
    ).order_by('-total')

    export = request.GET.get('export', '')
    if export in ('pdf', 'excel'):
        exporter = ExportMixin()
        exporter.export_filename = f'reporte_compras_{desde}_{hasta}'
        exporter.export_title = f'Reporte de Compras ({desde} a {hasta})'
        exporter.export_headers = ['Compra', 'Fecha', 'Proveedor', 'Tipo de Pago', 'Total']
        exporter.get_export_rows = lambda qs: [
            [
                f'#{c.id:04d}', c.purchase_date.strftime('%d/%m/%Y'), c.supplier.name,
                c.get_tipo_pago_display(), f'${c.total}',
            ]
            for c in qs
        ]
        return exporter.export_to_pdf(compras) if export == 'pdf' else exporter.export_to_excel(compras)

    context = {
        'desde': desde, 'hasta': hasta,
        'compras': compras,
        'por_tipo_pago': por_tipo_pago,
        'por_proveedor': por_proveedor,
        'total_general': _sum2(compras, 'total'),
    }
    return render(request, 'reportes/reporte_compras.html', context)


@permission_required_redirect('billing.view_product', '/')
def reporte_inventario(request):
    productos = Product.objects.filter(is_active=True).select_related('brand', 'group')

    # El valor de inventario se agrupa en Python (no con Sum(F('stock')*F('unit_price'))
    # en el ORM) para evitar el mismo ruido de punto flotante de SQLite sobre
    # DecimalField ya documentado en el resto del proyecto, reutilizando
    # directamente Product.inventory_value.
    valor_por_marca = defaultdict(lambda: {'valor': Decimal('0.00'), 'unidades': 0})
    valor_por_grupo = defaultdict(lambda: {'valor': Decimal('0.00'), 'unidades': 0})
    valor_total = Decimal('0.00')
    for p in productos:
        valor = p.inventory_value
        valor_total += valor
        valor_por_marca[p.brand.name]['valor'] += valor
        valor_por_marca[p.brand.name]['unidades'] += p.stock
        valor_por_grupo[p.group.name]['valor'] += valor
        valor_por_grupo[p.group.name]['unidades'] += p.stock

    por_marca = sorted(
        [{'nombre': k, **v} for k, v in valor_por_marca.items()], key=lambda r: r['valor'], reverse=True
    )
    por_grupo = sorted(
        [{'nombre': k, **v} for k, v in valor_por_grupo.items()], key=lambda r: r['valor'], reverse=True
    )
    bajo_stock = productos.filter(stock__lte=F('stock_minimo')).order_by('stock')

    export = request.GET.get('export', '')
    if export in ('pdf', 'excel'):
        exporter = ExportMixin()
        exporter.export_filename = 'reporte_inventario'
        exporter.export_title = 'Reporte de Inventario'
        exporter.export_headers = ['Producto', 'Marca', 'Grupo', 'Stock', 'Precio Unitario', 'Valor en Stock']
        exporter.get_export_rows = lambda qs: [
            [p.name, p.brand.name, p.group.name, p.stock, f'${p.unit_price}', f'${p.inventory_value}']
            for p in qs
        ]
        return exporter.export_to_pdf(productos) if export == 'pdf' else exporter.export_to_excel(productos)

    context = {
        'productos': productos,
        'por_marca': por_marca,
        'por_grupo': por_grupo,
        'bajo_stock': bajo_stock,
        'valor_total': valor_total,
    }
    return render(request, 'reportes/reporte_inventario.html', context)


@permission_required_redirect('caja.view_sesioncaja', '/')
def reporte_caja(request):
    desde, hasta = _periodo(request)
    sesiones = SesionCaja.objects.select_related('usuario').filter(
        fecha_apertura__date__gte=desde, fecha_apertura__date__lte=hasta,
    ).order_by('-fecha_apertura')

    por_cajero = defaultdict(lambda: {'sesiones': 0, 'diferencia_total': Decimal('0.00')})
    total_ingresos = Decimal('0.00')
    total_egresos = Decimal('0.00')
    total_diferencia = Decimal('0.00')
    for s in sesiones:
        total_ingresos += s.total_ingresos
        total_egresos += s.total_egresos
        if s.diferencia is not None:
            total_diferencia += s.diferencia
            por_cajero[s.usuario.username]['diferencia_total'] += s.diferencia
        por_cajero[s.usuario.username]['sesiones'] += 1

    por_cajero_lista = sorted(
        [{'usuario': k, **v} for k, v in por_cajero.items()], key=lambda r: r['usuario']
    )

    export = request.GET.get('export', '')
    if export in ('pdf', 'excel'):
        exporter = ExportMixin()
        exporter.export_filename = f'reporte_caja_{desde}_{hasta}'
        exporter.export_title = f'Reporte de Caja ({desde} a {hasta})'
        exporter.export_headers = ['Sesión', 'Cajero', 'Apertura', 'Cierre', 'Ingresos', 'Egresos', 'Diferencia']
        exporter.get_export_rows = lambda qs: [
            [
                f'#{s.id:04d}', s.usuario.username, s.fecha_apertura.strftime('%d/%m/%Y %H:%M'),
                s.fecha_cierre.strftime('%d/%m/%Y %H:%M') if s.fecha_cierre else '-',
                f'${s.total_ingresos}', f'${s.total_egresos}',
                f'${s.diferencia}' if s.diferencia is not None else '-',
            ]
            for s in qs
        ]
        return exporter.export_to_pdf(sesiones) if export == 'pdf' else exporter.export_to_excel(sesiones)

    context = {
        'desde': desde, 'hasta': hasta,
        'sesiones': sesiones,
        'por_cajero': por_cajero_lista,
        'total_ingresos': total_ingresos,
        'total_egresos': total_egresos,
        'total_diferencia': total_diferencia,
    }
    return render(request, 'reportes/reporte_caja.html', context)
