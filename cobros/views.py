from django.conf import settings
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render

from billing.models import Invoice
from caja.models import MovimientoCaja, SesionCaja
from configuracion.models import ConfiguracionSistema
from shared.decorators import permission_required_redirect
from shared.notifications import send_email_with_attachment, send_whatsapp_message
from shared.pagination import build_extra_qs, get_page_range

from .forms import CobroFacturaForm
from .models import CobroFactura


# Arma el PDF del comprobante de UN cobro (constancia de abono) y devuelve
# los bytes crudos — lo usan tanto cobro_pdf (descarga manual) como
# cobro_create (adjunto del correo al cliente), mismo patrón que
# pagos/views.py -> _build_pago_pdf, para no duplicar el diseño.
def _build_cobro_pdf(cobro):
    from reportlab.lib.pagesizes import letter
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib import colors
    from reportlab.lib.units import cm
    import io

    factura = cobro.factura

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter,
        topMargin=2*cm, bottomMargin=2*cm,
        leftMargin=2*cm, rightMargin=2*cm)

    styles = getSampleStyleSheet()
    story = []

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

    info_data = [
        [Paragraph('<b>COMPROBANTE DE COBRO</b>', ParagraphStyle('', parent=styles['Normal'], fontSize=14, fontName='Helvetica-Bold', textColor=colors.HexColor('#4e54c8'))),
         Paragraph(f'<b>Cobro N°:</b> {cobro.id:04d}', bold)],
        ['', Paragraph(f'<b>Fecha de Cobro:</b> {cobro.fecha.strftime("%d/%m/%Y")}', normal)],
        [Paragraph('<b>Cliente:</b>', bold), Paragraph(f'{factura.customer.full_name}', normal)],
        [Paragraph('<b>Factura N°:</b>', bold), Paragraph(f'{factura.id:04d}', normal)],
        [Paragraph('<b>Forma de Pago:</b>', bold), Paragraph(cobro.get_forma_pago_display(), normal)],
        [Paragraph('<b>Observación:</b>', bold), Paragraph(f'{cobro.observacion or "-"}', normal)],
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

    totales_data = [
        ['', 'Total de la Factura:', f'${factura.total}'],
        ['', 'Valor de este Cobro:', f'${cobro.valor}'],
        ['', 'Saldo Pendiente:', f'${factura.saldo}'],
    ]
    totales_table = Table(totales_data, colWidths=[6*cm, 6*cm, 5*cm])
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
    story.append(Paragraph(f'Registro interno de cobro a cliente — {config.empresa_nombre}', sub_style))

    doc.build(story)
    buffer.seek(0)
    return buffer.read()


def _enviar_comprobante_cobro(cobro, factura):
    """
    Notifica el cobro al cliente por los dos canales disponibles (igual que
    security/views.py -> RegisterView con las credenciales): correo con el
    comprobante PDF adjunto, y WhatsApp con un resumen de texto (la API
    simple de Twilio no adjunta archivos sin alojarlos en una URL pública,
    así que por WhatsApp va solo el texto). Ninguno de los dos es requisito
    para que el cobro se registre — si fallan o no hay contacto, no rompen el flujo.
    """
    if factura.estado == Invoice.PAGADA:
        estado_msg = '¡Con este abono, tu factura ha quedado completamente cancelada!'
    else:
        estado_msg = f'Tu saldo pendiente actual es de ${factura.saldo}.'

    config = ConfiguracionSistema.get_solo()

    if factura.customer.email:
        pdf_bytes = _build_cobro_pdf(cobro)
        subject = f'Comprobante de cobro #{cobro.id:04d} — {config.empresa_nombre}'
        body = (
            f'Estimado/a {factura.customer.full_name},\n\n'
            f'Adjuntamos el comprobante de tu abono de ${cobro.valor} a la factura #{factura.id:04d}.\n'
            f'{estado_msg}\n\n'
            f'Gracias por tu pago.\n\n'
            f'Atentamente,\n'
            f'{config.empresa_nombre}'
        )
        # OJO: no se pasa factura_url — invoice_detail es una vista interna
        # protegida por permiso, el cliente no tiene con qué iniciar sesión
        # para verla; el PDF ya va adjunto acá.
        send_email_with_attachment(
            factura.customer.email, subject, body,
            f'cobro_{cobro.id:04d}.pdf', pdf_bytes,
            html_template='confirmacion_pago.html',
            html_context={
                'usuario': factura.customer.full_name, 'factura_numero': f'{factura.id:04d}',
                'monto': f'${cobro.valor}', 'metodo_pago': cobro.get_forma_pago_display(),
                'fecha': cobro.fecha.strftime('%d/%m/%Y'),
                'estado': 'Pagada por completo' if factura.estado == Invoice.PAGADA else 'Pago parcial registrado',
            },
        )

    if factura.customer.phone:
        whatsapp_body = (
            f'{config.empresa_nombre} — Comprobante de cobro #{cobro.id:04d}\n'
            f'Factura #{factura.id:04d}: abono de ${cobro.valor} registrado.\n'
            f'{estado_msg}\n'
            f'Gracias por tu pago.'
        )
        send_whatsapp_message(factura.customer.phone, whatsapp_body)


# Pantalla "Consultar facturas pendientes": solo facturas a crédito, activas
# (no anuladas) y que todavía tienen saldo por cobrar del cliente.
@permission_required_redirect('cobros.access_cobrofactura_module', '/')
def invoice_pending_list(request):
    query = request.GET.get('q', '')

    invoices = Invoice.objects.select_related('customer').filter(
        tipo_pago=Invoice.CREDITO, estado=Invoice.PENDIENTE, is_active=True
    )
    if query:
        invoices = invoices.filter(customer__last_name__icontains=query)

    paginator = Paginator(invoices, 10)
    page_obj = paginator.get_page(request.GET.get('page'))

    context = {
        'items': page_obj,
        'page_obj': page_obj,
        'page_range': get_page_range(page_obj),
        'extra_qs': build_extra_qs(request),
        'query': query,
    }
    return render(request, 'cobros/invoice_pending_list.html', context)


# Registrar un abono sobre UNA factura puntual (se llega acá desde el botón
# "Registrar Cobro" de invoice_pending_list, con el id de esa factura en la URL).
@permission_required_redirect('cobros.add_cobrofactura', '/cobros/pendientes/')
def cobro_create(request, factura_id):
    factura = get_object_or_404(Invoice, pk=factura_id, tipo_pago=Invoice.CREDITO)

    if not factura.is_active:
        messages.error(request, f'La factura #{factura.id:04d} está anulada, no admite cobros.')
        return redirect('cobros:invoice_pending_list')

    if factura.estado == Invoice.PAGADA:
        messages.info(request, f'La factura #{factura.id:04d} ya está cancelada.')
        return redirect('cobros:invoice_pending_list')

    if request.method == 'POST':
        form = CobroFacturaForm(request.POST, factura=factura)
        if form.is_valid():
            forma_pago = form.cleaned_data.get('forma_pago')
            # Este formulario manual es para EFECTIVO/TARJETA (pagar con
            # PayPal usa el botón de más abajo -> cobro_paypal_iniciar, que
            # sí cobra de verdad) — ambas exigen una SesionCaja abierta,
            # mismo criterio espejo que billing/views.py -> invoice_create y
            # pagos/views.py -> pago_create. Solo EFECTIVO crea
            # MovimientoCaja: con tarjeta el dinero no entra físicamente a
            # la caja, va a un datáfono externo.
            sesion_caja = SesionCaja.objects.filter(
                usuario=request.user, estado=SesionCaja.ABIERTA
            ).first()
            if not sesion_caja:
                messages.error(
                    request,
                    'Debes abrir una caja antes de registrar un cobro en efectivo o tarjeta.'
                )
                return render(request, 'cobros/cobro_form.html', {
                    'form': form, 'factura': factura, 'title': 'Registrar Cobro',
                    'paypal_configurado': bool(settings.PAYPAL_CLIENT_ID and settings.PAYPAL_CLIENT_SECRET),
                })

            cobro = form.save(commit=False)
            cobro.factura = factura
            # Igual que pagos/views.py -> pago_create: evita que quede una
            # constancia de tarjeta "fantasma" si se llenó y después se
            # cambió la forma de pago antes de enviar.
            if forma_pago != CobroFactura.TARJETA:
                cobro.tarjeta_titular = cobro.tarjeta_cvv = cobro.tarjeta_expiracion = None
            try:
                with transaction.atomic():
                    cobro.save()
                    if forma_pago == CobroFactura.EFECTIVO:
                        MovimientoCaja.objects.create(
                            sesion=sesion_caja, tipo=MovimientoCaja.INGRESO, monto=cobro.valor,
                            concepto=f'Cobro factura #{factura.id:04d} - {factura.customer}',
                            cobro_factura=cobro,
                        )
            except ValidationError as e:
                messages.error(request, ' '.join(e.messages))
            else:
                factura.refresh_from_db()
                cambio_msg = f' Cambio a devolver: ${cobro.cambio}.' if cobro.cambio is not None else ''
                messages.success(
                    request,
                    f'Cobro de ${cobro.valor} registrado.{cambio_msg} Saldo restante: ${factura.saldo}'
                )
                _enviar_comprobante_cobro(cobro, factura)
                return redirect('cobros:invoice_pending_list')
    else:
        form = CobroFacturaForm(factura=factura)

    return render(request, 'cobros/cobro_form.html', {
        'form': form, 'factura': factura, 'title': 'Registrar Cobro',
        'paypal_configurado': bool(settings.PAYPAL_CLIENT_ID and settings.PAYPAL_CLIENT_SECRET),
    })


# Alternativa al form manual de arriba: el cliente paga su saldo pendiente
# (o una parte) directo con PayPal. No se crea ningún CobroFactura acá — solo
# se arma la orden en PayPal y se redirige al checkout; el CobroFactura real
# se crea cuando el pago se captura de verdad (ver paypal_pagos/services.py).
@permission_required_redirect('cobros.add_cobrofactura', '/cobros/pendientes/')
def cobro_paypal_iniciar(request, factura_id):
    factura = get_object_or_404(Invoice, pk=factura_id, tipo_pago=Invoice.CREDITO)

    if not factura.is_active:
        messages.error(request, f'La factura #{factura.id:04d} está anulada, no admite cobros.')
        return redirect('cobros:invoice_pending_list')
    if factura.estado == Invoice.PAGADA:
        messages.info(request, f'La factura #{factura.id:04d} ya está cancelada.')
        return redirect('cobros:invoice_pending_list')

    if request.method != 'POST':
        return redirect('cobros:cobro_create', factura_id=factura.id)

    from decimal import Decimal, InvalidOperation

    from paypal_pagos.client import PayPalError
    from paypal_pagos.services import crear_orden_cobro

    monto_raw = request.POST.get('monto', '').strip()
    try:
        monto = Decimal(monto_raw) if monto_raw else factura.saldo
    except InvalidOperation:
        messages.error(request, 'Monto inválido.')
        return redirect('cobros:cobro_create', factura_id=factura.id)

    if monto <= 0 or monto > factura.saldo:
        messages.error(request, f'El monto debe estar entre $0.01 y el saldo pendiente (${factura.saldo}).')
        return redirect('cobros:cobro_create', factura_id=factura.id)

    try:
        orden = crear_orden_cobro(factura, monto, request.user)
    except PayPalError as e:
        messages.error(request, str(e))
        return redirect('cobros:cobro_create', factura_id=factura.id)

    return redirect(orden.approval_url)


# Historial completo de cobros (todas las facturas), con filtro opcional por
# factura específica (?factura=<id>) o por apellido del cliente.
@permission_required_redirect('cobros.access_cobrofactura_module', '/')
def cobro_list(request):
    query = request.GET.get('q', '')
    factura_id = request.GET.get('factura', '')

    cobros = CobroFactura.objects.select_related('factura', 'factura__customer').all()
    if query:
        cobros = cobros.filter(factura__customer__last_name__icontains=query)

    factura_filtro = None
    if factura_id:
        cobros = cobros.filter(factura_id=factura_id)
        factura_filtro = get_object_or_404(Invoice, pk=factura_id)

    paginator = Paginator(cobros, 10)
    page_obj = paginator.get_page(request.GET.get('page'))

    context = {
        'items': page_obj,
        'page_obj': page_obj,
        'page_range': get_page_range(page_obj),
        'extra_qs': build_extra_qs(request),
        'query': query,
        'factura_filtro': factura_filtro,
    }
    return render(request, 'cobros/cobro_list.html', context)


@permission_required_redirect('cobros.change_cobrofactura', '/cobros/historial/')
def cobro_update(request, pk):
    cobro = get_object_or_404(CobroFactura, pk=pk)
    factura = cobro.factura

    if request.method == 'POST':
        form = CobroFacturaForm(request.POST, instance=cobro, factura=factura)
        if form.is_valid():
            try:
                with transaction.atomic():
                    form.save()
            except ValidationError as e:
                messages.error(request, ' '.join(e.messages))
            else:
                messages.success(request, 'Cobro actualizado correctamente.')
                return redirect('cobros:cobro_list')
    else:
        form = CobroFacturaForm(instance=cobro, factura=factura)

    return render(request, 'cobros/cobro_form.html', {
        'form': form, 'factura': factura, 'title': 'Editar Cobro', 'cobro': cobro,
    })


@permission_required_redirect('cobros.view_cobrofactura', '/cobros/historial/')
def cobro_pdf(request, pk):
    from django.http import HttpResponse

    cobro = get_object_or_404(
        CobroFactura.objects.select_related('factura', 'factura__customer'), pk=pk
    )
    pdf_bytes = _build_cobro_pdf(cobro)
    response = HttpResponse(pdf_bytes, content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="cobro_{cobro.id:04d}.pdf"'
    return response


@permission_required_redirect('cobros.delete_cobrofactura', '/cobros/historial/')
def cobro_delete(request, pk):
    cobro = get_object_or_404(CobroFactura, pk=pk)

    if request.method == 'POST':
        if cobro.factura.estado == Invoice.PAGADA:
            messages.error(request, 'No se puede eliminar un cobro que deje el saldo inconsistente (la factura ya está cancelada).')
            return redirect('cobros:cobro_list')
        try:
            with transaction.atomic():
                cobro.delete()
        except ValidationError as e:
            messages.error(request, ' '.join(e.messages))
        else:
            messages.success(request, 'Cobro eliminado correctamente.')
        return redirect('cobros:cobro_list')

    return render(request, 'cobros/cobro_confirm_delete.html', {'object': cobro})
