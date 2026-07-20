from django.conf import settings
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.core.paginator import Paginator
from django.http import JsonResponse
from django.urls import reverse
from django.utils import timezone
from decimal import Decimal
from billing.models import Product
from billing.export_mixins import ExportMixin
from caja.models import MovimientoCaja, SesionCaja
from configuracion.models import ConfiguracionSistema
from paypal_pagos.client import PayPalError
from paypal_pagos.services import crear_pago_proveedor
from shared.decorators import permission_required_redirect
from shared.notifications import send_credentials_email, get_admin_recipients
from shared.pagination import build_extra_qs, get_page_range
from .models import Bodega, Purchase, PurchaseDetail
from .forms import BodegaQuickCreateForm, PurchaseForm, PurchaseDetailFormSet

# Este archivo es el "hermano" de billing/views.py -> invoice_create: mismo
# patrón de formulario + formset (cabecera + líneas), pero de compras en vez
# de ventas. La diferencia clave es que una compra SUMA stock (entra
# mercadería) mientras que una factura RESTA stock (sale mercadería).


@permission_required_redirect('purchasing.access_purchase_module', '/')
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
        if not request.user.has_perm(f'purchasing.export_{export}_purchase'):
            messages.error(request, 'No tienes permiso para exportar este listado.')
        else:
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
def bodega_quick_create(request):
    """
    Alta rápida de bodega desde el modal del paso 1 del wizard de compra
    (ver static/js/purchase-wizard.js) — mismo patrón que
    billing.views.customer_quick_create/supplier_quick_create: responde
    JSON en vez de redirigir. Bodega no tiene su propio permiso ('add_bodega'
    existe automático por ser un modelo, pero acá se reusa el permiso de
    crear compras — quien puede armar el wizard, puede darle de alta a una
    bodega nueva sin salir de él).
    """
    if request.method != 'POST':
        return JsonResponse({'ok': False, 'errors': {'__all__': ['Método no permitido.']}}, status=405)

    form = BodegaQuickCreateForm(request.POST)
    if not form.is_valid():
        return JsonResponse({'ok': False, 'errors': form.errors}, status=400)

    bodega = form.save()
    return JsonResponse({
        'ok': True,
        'bodega': {'id': bodega.id, 'label': bodega.nombre},
    }, status=201)


@permission_required_redirect('purchasing.add_purchase', '/purchases/')
def purchase_create(request):
    import json
    from django.db import IntegrityError
    from billing.models import Supplier, Product

    # last_prices: último costo pagado a CADA proveedor por CADA producto
    # (a diferencia de Product.last_cost, que es global y se pisa con
    # cualquier proveedor). Una sola consulta ordenada por fecha descendente;
    # como solo nos interesa la primera fila que aparece por cada
    # (proveedor, producto), el resto se descarta al armar el dict.
    last_prices = {}
    detalles_recientes = PurchaseDetail.objects.select_related('purchase').order_by(
        'product_id', '-purchase__purchase_date'
    )
    for d in detalles_recientes:
        key = (d.purchase.supplier_id, d.product_id)
        if key not in last_prices:
            last_prices[key] = float(d.unit_cost)

    # suppliers_products: qué productos vende cada proveedor, a qué último
    # costo global, código de barras, imagen, último precio pagado A ESE
    # proveedor puntual, y stock/stock_minimo (para mostrarlo junto al
    # nombre y resaltar los productos con stock bajo en el selector) — en
    # JSON para que el JavaScript del template autocomplete/filtre el
    # <select> de productos sin recargar la página.
    suppliers_products = {}
    for supplier in Supplier.objects.filter(is_active=True):
        suppliers_products[supplier.id] = [
            {
                'id': p.id,
                'name': p.name,
                'cost': float(p.last_cost) if p.last_cost else 0,
                'barcode': p.barcode or '',
                'image_url': p.image.url if p.image else p.placeholder_image,
                'last_price': last_prices.get((supplier.id, p.id)),
                'stock': p.stock,
                'stock_minimo': p.stock_minimo,
            }
            for p in supplier.products.filter(is_active=True)
        ]

    # productos_reposicion_urgente: productos con stock <= stock_minimo, de
    # CUALQUIER proveedor (no solo el elegido en el paso 1) — se listan en
    # el wizard con sus proveedores habituales para agilizar la compra. Se
    # prefetchean solo los proveedores ACTIVOS: no tiene sentido ofrecer un
    # botón "comprarle a X" si X ya no está activo.
    from django.db.models import F, Prefetch
    productos_reposicion_urgente = Product.objects.filter(
        is_active=True, stock__lte=F('stock_minimo')
    ).prefetch_related(
        Prefetch('suppliers', queryset=Supplier.objects.filter(is_active=True))
    ).order_by('stock')

    config = ConfiguracionSistema.get_solo()
    context_base = {
        'title': 'Nueva Compra',
        'suppliers_products_json': json.dumps(suppliers_products),
        'iva_fraccion_json': json.dumps(float(config.iva_fraccion)),
        'retencion_porcentaje_default_json': json.dumps(float(config.retencion_porcentaje_default)),
        'productos_reposicion_urgente': productos_reposicion_urgente,
    }

    if request.method == 'POST':
        form = PurchaseForm(request.POST, request.FILES)
        formset = PurchaseDetailFormSet(request.POST, instance=Purchase())

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

            # Validar duplicados, que cada producto pertenezca al proveedor
            # elegido, cantidad y costo. El filtro por proveedor en el <select>
            # (purchase-wizard.js) es solo visual — el <select> renderizado
            # trae TODOS los productos activos, así que sin este chequeo el
            # servidor guardaría cualquier combinación producto/proveedor.
            supplier_product_ids = set(supplier.products.values_list('id', flat=True)) if supplier else set()
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
                        if product.id not in supplier_product_ids:
                            messages.error(
                                request,
                                f'"{product.name}" no está registrado como producto de "{supplier.name}" — '
                                f'agrégalo primero a sus proveedores, o elige otro producto.'
                            )
                            return render(request, 'purchasing/purchase_form.html', {
                                **context_base, 'form': form, 'formset': formset
                            })
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

            # EFECTIVO, TARJETA y PAYPAL (compras al CONTADO) exigen caja
            # abierta del usuario — a diferencia de "pagos" (abonos a
            # compras a crédito), donde PayPal no la exige, en "compras" las
            # 3 formas de pago la piden (confirmado con el usuario). Nada de
            # esto aplica a CREDITO, que no tiene forma_pago (ver
            # Purchase.clean()).
            forma_pago = form.cleaned_data.get('forma_pago')
            sesion_caja = None
            paypal_payout_id = None
            if form.cleaned_data.get('tipo_pago') == Purchase.CONTADO:
                sesion_caja = SesionCaja.objects.filter(
                    usuario=request.user, estado=SesionCaja.ABIERTA
                ).first()
                if not sesion_caja:
                    messages.error(request, 'Debes abrir una caja antes de registrar una compra al contado.')
                    return render(request, 'purchasing/purchase_form.html', {
                        **context_base, 'form': form, 'formset': formset
                    })

                if forma_pago == Purchase.PAYPAL:
                    # PAYPAL acá es un pago REAL (Payouts, dinero saliendo al
                    # proveedor) — igual que billing nunca crea la Invoice
                    # hasta que el pago está resuelto, acá no se guarda NADA
                    # de la compra si el payout falla. El monto se calcula
                    # desde las líneas ya validadas, SIN guardar todavía el
                    # Purchase (mismo criterio que invoice_create calcula
                    # proyectado_total antes de decidir el camino de PayPal).
                    subtotal_prospectivo = sum(
                        (f.cleaned_data['quantity'] * f.cleaned_data['unit_cost']
                         * (1 - (f.cleaned_data.get('descuento_porcentaje') or Decimal('0')) / Decimal('100')))
                        for f in productos_validos
                    ).quantize(Decimal('0.01'))
                    tax_prospectivo = (subtotal_prospectivo * config.iva_fraccion).quantize(Decimal('0.01'))
                    total_prospectivo = subtotal_prospectivo + tax_prospectivo
                    retencion_valor_prospectivo = (
                        subtotal_prospectivo * (form.cleaned_data.get('retencion_porcentaje') or Decimal('0'))
                        / Decimal('100')
                    ).quantize(Decimal('0.01'))
                    monto_neto_prospectivo = total_prospectivo - retencion_valor_prospectivo

                    referencia = f'compra-{supplier.id}-{timezone.now():%Y%m%d%H%M%S%f}'
                    try:
                        paypal_payout_id, _status = crear_pago_proveedor(
                            supplier, monto_neto_prospectivo, referencia,
                        )
                    except PayPalError as e:
                        messages.error(request, str(e))
                        return render(request, 'purchasing/purchase_form.html', {
                            **context_base, 'form': form, 'formset': formset
                        })

            # Guardar: mismo patrón que invoice_create en billing/views.py
            # (commit=False -> guardar cabecera -> asociar formset -> guardar
            # líneas -> recién ahí calcular totales). A diferencia de antes,
            # el stock/last_cost del producto YA NO se actualiza acá — la
            # compra nace en fase BORRADOR y esa actualización se mueve a
            # purchase_marcar_recibida, recién cuando la mercadería llegó de
            # verdad (ver ese view más abajo).
            try:
                purchase = form.save(commit=False)
                # Los campos de tarjeta solo se guardan si de verdad se pagó
                # con tarjeta (mismo criterio que billing/pagos/cobros).
                if forma_pago != Purchase.TARJETA:
                    purchase.tarjeta_titular = purchase.tarjeta_cvv = purchase.tarjeta_expiracion = None
                purchase.paypal_payout_id = paypal_payout_id
                purchase.save()
                formset.instance = purchase
                formset.save()

                subtotal = sum(d.subtotal for d in purchase.details.all())
                purchase.subtotal = subtotal
                # Multiplicar dos Decimal suma sus decimales (2 + 2 = 4);
                # sin quantize, el total en memoria mostraría "$115.0000" en
                # vez de "$115.00" hasta el próximo refresh_from_db(). IVA
                # configurable (ver configuracion/models.py).
                purchase.tax = (subtotal * ConfiguracionSistema.get_solo().iva_fraccion).quantize(Decimal('0.01'))
                purchase.total = purchase.subtotal + purchase.tax

                # Una compra a crédito nace con interés (según meses_credito)
                # y saldo = total + interés; al contado queda pagada de una
                # (ver Purchase.aplicar_financiamiento() y módulo 'pagos').
                purchase.aplicar_financiamiento()

                # Retención: puramente informativa, calculada sobre el
                # subtotal (antes de IVA) — no genera ningún comprobante de
                # retención real ni valida contra tablas oficiales del SRI.
                purchase.retencion_valor = (
                    purchase.subtotal * purchase.retencion_porcentaje / Decimal('100')
                ).quantize(Decimal('0.01'))
                purchase.save()

                # Solo EFECTIVO genera un MovimientoCaja EGRESO real — con
                # tarjeta el dinero no sale físicamente de la caja (va a un
                # datáfono externo), y con PayPal ya salió por Payouts, no
                # por la caja (mismo criterio que billing/pagos).
                if forma_pago == Purchase.EFECTIVO and sesion_caja:
                    MovimientoCaja.objects.create(
                        sesion=sesion_caja, tipo=MovimientoCaja.EGRESO, monto=purchase.monto_neto_a_pagar,
                        concepto=f'Compra #{purchase.id:04d} - {purchase.supplier.name}',
                        purchase=purchase,
                    )

                # Aviso a los administradores (evento nuevo, no existía antes
                # ningún correo para esto) — "best effort", nunca bloquea el
                # registro de la compra.
                productos_ctx = [
                    {'nombre': d.product.name, 'cantidad': d.quantity}
                    for d in purchase.details.all()
                ]
                for admin_nombre, admin_email in get_admin_recipients():
                    send_credentials_email(
                        admin_email, f'Compra a proveedor registrada — #{purchase.id:04d}',
                        (
                            f'Hola {admin_nombre},\n\n'
                            f'Se registró una nueva compra en el sistema:\n\n'
                            f'N° de compra: {purchase.id:04d}\n'
                            f'Proveedor: {purchase.supplier.name}\n'
                            f'Total: ${purchase.total}\n\n'
                            f'Atentamente,\n'
                            f'Sistema de Ventas TecnoStock'
                        ),
                        html_template='compra_proveedor_registrada.html',
                        html_context={
                            'usuario': admin_nombre, 'proveedor_nombre': purchase.supplier.name,
                            'compra_numero': f'{purchase.id:04d}',
                            'fecha': purchase.purchase_date.strftime('%d/%m/%Y %H:%M'),
                            'total': f'${purchase.total}', 'productos': productos_ctx,
                            'compra_url': f'{settings.SITE_URL}{reverse("purchasing:purchase_detail", args=[purchase.pk])}',
                        },
                    )

                # Aviso informativo de seguimiento: la fecha estimada de
                # entrega ya no se pide en el wizard, se calcula sola
                # (purchase.fecha_entrega_estimada = purchase_date + 24h).
                messages.info(
                    request,
                    f'Seguimiento: el pedido debería llegar a más tardar el '
                    f'{purchase.fecha_entrega_estimada:%d/%m/%Y %H:%M} (~24 horas).'
                )

                if purchase.tipo_pago == Purchase.CREDITO:
                    messages.success(
                        request,
                        f'Compra #{purchase.id} registrada en Borrador! Total: ${purchase.total} + '
                        f'interés ${purchase.interes} ({purchase.meses_credito} meses) = '
                        f'${purchase.saldo} a pagar. Cuota mínima mensual: ${purchase.cuota_minima}'
                    )
                else:
                    messages.success(request, f'Compra #{purchase.id} registrada en Borrador! Total: ${purchase.total}')
                return redirect('purchasing:purchase_detail', pk=purchase.pk)

            except IntegrityError:
                # Salta si se viola el UniqueConstraint del modelo Purchase
                # (mismo document_number + mismo supplier ya registrado).
                messages.error(request, 'Ya existe una compra con ese número de documento para este proveedor.')
            except Exception as e:
                import traceback
                traceback.print_exc()
                messages.error(request, f'Error al guardar: {str(e)}')
        else:
            # Sin este mensaje, un error de validación (ej. elegir "Crédito"
            # sin indicar los meses) hacía que la página simplemente se
            # recargara con el campo marcado en rojo pero sin ningún aviso
            # visible arriba — parecía que "no pasaba nada" al guardar.
            messages.error(request, 'No se pudo guardar la compra: revisa los errores señalados en el formulario.')

    else:
        form = PurchaseForm()
        formset = PurchaseDetailFormSet()

    return render(request, 'purchasing/purchase_form.html', {
        **context_base,
        'form': form,
        'formset': formset,
    })


# Transiciones de fase: Borrador -> Confirmada -> Recibida. Cada una exige
# que la compra esté en la fase inmediata anterior (no se puede saltar
# pasos) y reusa el permiso 'purchasing.change_purchase' — no hace falta
# uno nuevo solo para esto.
@permission_required_redirect('purchasing.change_purchase', '/purchases/')
def purchase_confirmar(request, pk):
    purchase = get_object_or_404(Purchase, pk=pk)
    if purchase.fase != Purchase.BORRADOR:
        messages.error(request, f'La compra #{purchase.id} ya no está en Borrador.')
    else:
        purchase.fase = Purchase.CONFIRMADA
        purchase.save(update_fields=['fase'])
        messages.success(request, f'Compra #{purchase.id} confirmada.')
    return redirect('purchasing:purchase_detail', pk=purchase.pk)


@permission_required_redirect('purchasing.change_purchase', '/purchases/')
def purchase_marcar_recibida(request, pk):
    purchase = get_object_or_404(
        Purchase.objects.prefetch_related('details__product'), pk=pk
    )
    if purchase.fase != Purchase.CONFIRMADA:
        messages.error(request, f'La compra #{purchase.id} debe estar Confirmada antes de marcarla como recibida.')
        return redirect('purchasing:purchase_detail', pk=purchase.pk)

    # Acá es donde entra la mercadería de verdad: se mueve desde
    # purchase_create (donde corría al crear la compra, antes de que
    # existiera el flujo Borrador/Confirmada/Recibida) — cada línea SUBE el
    # stock del producto y actualiza su last_cost.
    for detail in purchase.details.all():
        product = detail.product
        product.stock += detail.quantity
        product.last_cost = detail.unit_cost
        product.save()

    purchase.fase = Purchase.RECIBIDA
    purchase.save(update_fields=['fase'])
    messages.success(request, f'Compra #{purchase.id} marcada como recibida. Stock actualizado.')
    return redirect('purchasing:purchase_detail', pk=purchase.pk)


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

    config = ConfiguracionSistema.get_solo()
    story.append(Paragraph(config.empresa_nombre, title_style))
    story.append(Paragraph('Sistema de Gestión de Ventas y Facturación', sub_style))
    datos_empresa = ' | '.join(
        d for d in [config.empresa_ruc and f'RUC: {config.empresa_ruc}', config.empresa_direccion, config.empresa_telefono] if d
    )
    if datos_empresa:
        story.append(Paragraph(datos_empresa, sub_style))
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
        ['', f'IVA ({config.iva_porcentaje}%):', f'${purchase.tax}'],
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
    story.append(Paragraph(f'Registro interno de compra — {config.empresa_nombre}', sub_style))

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
@permission_required_redirect('purchasing.access_purchase_module', '/purchases/')
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