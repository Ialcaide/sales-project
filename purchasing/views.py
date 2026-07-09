from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.core.paginator import Paginator
from decimal import Decimal
from billing.models import Product
from billing.export_mixins import ExportMixin
from shared.decorators import permission_required_redirect
from shared.pagination import build_extra_qs, get_page_range
from .models import Purchase, PurchaseDetail
from .forms import PurchaseForm, PurchaseDetailFormSet

# Este archivo es el "hermano" de billing/views.py -> invoice_create: mismo
# patrón de formulario + formset (cabecera + líneas), pero de compras en vez
# de ventas. La diferencia clave es que una compra SUMA stock (entra
# mercadería) mientras que una factura RESTA stock (sale mercadería).


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

    export = request.GET.get('export', '')
    if export in ('pdf', 'excel'):
        exporter = ExportMixin()
        exporter.export_filename = 'compras'
        exporter.export_title = 'Listado de Compras'
        exporter.export_headers = ['#', 'Proveedor', 'N° Documento', 'Fecha', 'Subtotal', 'IVA', 'Total']
        exporter.get_export_rows = lambda qs: [
            [
                p.id,
                p.supplier.name,
                p.document_number,
                p.purchase_date.strftime('%d/%m/%Y'),
                f'${p.subtotal}',
                f'${p.tax}',
                f'${p.total}',
            ]
            for p in qs
        ]
        if export == 'pdf':
            return exporter.export_to_pdf(purchases)
        else:
            return exporter.export_to_excel(purchases)

    paginator = Paginator(purchases, 10)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    context = {
        'items': page_obj,
        'page_obj': page_obj,
        'page_range': get_page_range(page_obj),
        'extra_qs': build_extra_qs(request),
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

    # suppliers_products: qué productos vende cada proveedor y a qué último
    # costo, en JSON para que el JavaScript del template filtre el <select>
    # de productos según el proveedor elegido, sin recargar la página.
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
        # Los print() de acá abajo son de depuración (quedaron de cuando se
        # diagnosticó un bug en este formulario) — no son necesarios para que
        # la vista funcione, solo ayudan a ver en la consola del servidor qué
        # llegó en el POST y por qué el formset pasó o no la validación.
        # Se pueden borrar sin problema si ya no los necesitas.
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

            # Guardar: mismo patrón que invoice_create en billing/views.py
            # (commit=False -> guardar cabecera -> asociar formset -> guardar
            # líneas -> recién ahí calcular totales), pero acá además cada
            # línea SUBE el stock del producto y actualiza su last_cost —
            # así el próximo Product.margin/last_cost ya refleja lo que
            # realmente costó la última compra.
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
                # Salta si se viola el UniqueConstraint del modelo Purchase
                # (mismo document_number + mismo supplier ya registrado).
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


# Genera el PDF de UNA compra individual (el comprobante), con el mismo
# diseño que billing/views.py -> invoice_pdf para las facturas: reportlab
# arma el documento en memoria (io.BytesIO) y se devuelve directo como
# descarga, sin guardar ningún archivo en disco.
@permission_required_redirect('purchasing.view_purchase', '/purchases/')
def purchase_pdf(request, pk):
    from reportlab.lib.pagesizes import letter
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib import colors
    from reportlab.lib.units import cm
    from django.http import HttpResponse
    import io

    purchase = get_object_or_404(
        Purchase.objects.select_related('supplier').prefetch_related('details__product'),
        pk=pk
    )

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
    story.append(Paragraph('Sistema de Gestión de Ventas y Facturación', sub_style))
    story.append(HRFlowable(width='100%', thickness=1, color=colors.HexColor('#e2e8f0')))
    story.append(Spacer(1, 0.3*cm))

    # Info compra y proveedor
    info_data = [
        [Paragraph('<b>COMPRA</b>', ParagraphStyle('', parent=styles['Normal'], fontSize=14, fontName='Helvetica-Bold', textColor=colors.HexColor('#4e54c8'))),
         Paragraph(f'<b>Compra N°:</b> {purchase.id:04d}', bold)],
        ['', Paragraph(f'<b>Fecha:</b> {purchase.purchase_date.strftime("%d/%m/%Y %H:%M")}', normal)],
        [Paragraph('<b>Proveedor:</b>', bold), Paragraph(f'{purchase.supplier.name}', normal)],
        [Paragraph('<b>N° Documento:</b>', bold), Paragraph(f'{purchase.document_number}', normal)],
        [Paragraph('<b>Correo:</b>', bold), Paragraph(f'{purchase.supplier.email or "-"}', normal)],
        [Paragraph('<b>Teléfono:</b>', bold), Paragraph(f'{purchase.supplier.phone or "-"}', normal)],
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
    headers = ['Producto', 'Cantidad', 'Costo Unitario', 'Subtotal']
    rows = [headers]
    for d in purchase.details.all():
        rows.append([
            d.product.name,
            str(d.quantity),
            f'${d.unit_cost}',
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
        ['', 'Subtotal:', f'${purchase.subtotal}'],
        ['', 'IVA (15%):', f'${purchase.tax}'],
        ['', 'TOTAL:', f'${purchase.total}'],
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
    story.append(Paragraph('Registro interno de compra — TecnoStock S.A.', sub_style))

    doc.build(story)
    buffer.seek(0)
    response = HttpResponse(buffer, content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="compra_{purchase.id:04d}.pdf"'
    return response


@permission_required_redirect('purchasing.delete_purchase', '/purchases/')
def purchase_delete(request, pk):
    purchase = get_object_or_404(Purchase, pk=pk)
    if request.method == 'POST':
        purchase_id = purchase.id
        purchase.delete()
        messages.success(request, f'Compra #{purchase_id} eliminada!')
        return redirect('purchasing:purchase_list')
    return render(request, 'purchasing/purchase_confirm_delete.html', {'object': purchase})


# Reporte agregado: cuánto se compró de cada producto en total, a qué costo
# promedio, y en cuántas compras distintas apareció. .values('product__name')
# agrupa por nombre de producto (como un GROUP BY en SQL), y .annotate()
# calcula Avg/Sum/Count por cada grupo — todo resuelto por el ORM, sin SQL manual.
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