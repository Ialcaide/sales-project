from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from caja.models import MovimientoCaja, SesionCaja
from configuracion.models import ConfiguracionSistema
from paypal_pagos.client import PayPalError
from paypal_pagos.services import crear_pago_proveedor
from purchasing.models import Purchase
from shared.decorators import permission_required_redirect
from shared.notifications import send_email_with_attachment, send_whatsapp_message
from shared.pagination import build_extra_qs, get_page_range

from .forms import PagoCompraForm
from .models import PagoCompra


# Pantalla "Consultar compras pendientes": solo compras a crédito que
# todavía tienen saldo por cobrar del proveedor.
@permission_required_redirect('pagos.access_pagocompra_module', '/')
def purchase_pending_list(request):
    query = request.GET.get('q', '')

    purchases = Purchase.objects.select_related('supplier').filter(
        tipo_pago=Purchase.CREDITO, estado=Purchase.PENDIENTE
    )
    if query:
        purchases = purchases.filter(document_number__icontains=query)

    paginator = Paginator(purchases, 10)
    page_obj = paginator.get_page(request.GET.get('page'))

    context = {
        'items': page_obj,
        'page_obj': page_obj,
        'page_range': get_page_range(page_obj),
        'extra_qs': build_extra_qs(request),
        'query': query,
    }
    return render(request, 'pagos/purchase_pending_list.html', context)


# Registrar un abono sobre UNA compra puntual (se llega acá desde el botón
# "Registrar pago" de purchase_pending_list, con el id de esa compra en la URL).
@permission_required_redirect('pagos.add_pagocompra', '/pagos/pendientes/')
def pago_create(request, compra_id):
    compra = get_object_or_404(Purchase, pk=compra_id, tipo_pago=Purchase.CREDITO)

    if compra.estado == Purchase.PAGADA:
        messages.info(request, f'La compra #{compra.id:04d} ya está cancelada.')
        return redirect('pagos:purchase_pending_list')

    if request.method == 'POST':
        form = PagoCompraForm(request.POST, compra=compra)
        if form.is_valid():
            forma_pago = form.cleaned_data.get('forma_pago')
            # EFECTIVO y TARJETA exigen una SesionCaja abierta (venta de
            # mostrador), mismo criterio espejo que billing/views.py ->
            # invoice_create — pero TARJETA no genera MovimientoCaja: ese
            # dinero no entra físicamente a la caja, va a un datáfono externo.
            sesion_caja = None
            if forma_pago in (PagoCompra.EFECTIVO, PagoCompra.TARJETA):
                sesion_caja = SesionCaja.objects.filter(
                    usuario=request.user, estado=SesionCaja.ABIERTA
                ).first()
                if not sesion_caja:
                    messages.error(
                        request,
                        'Debes abrir una caja antes de registrar un pago en efectivo o tarjeta a un proveedor.'
                    )
                    return render(request, 'pagos/pago_form.html', {
                        'form': form, 'compra': compra, 'title': 'Registrar Pago',
                    })

            # PAYPAL acá es un pago REAL (Payouts, dinero saliendo al
            # proveedor) — a diferencia de EFECTIVO/TARJETA, no hace falta
            # caja abierta (el dinero nunca pasa por la caja física), pero
            # SÍ hay que confirmar que el envío se hizo de verdad ANTES de
            # guardar el PagoCompra: igual que billing nunca crea la Invoice
            # hasta que el pago está resuelto, acá no se registra el pago
            # si el payout falla.
            paypal_payout_id = None
            if forma_pago == PagoCompra.PAYPAL:
                referencia = f'pago-compra-{compra.id}-{timezone.now():%Y%m%d%H%M%S%f}'
                try:
                    paypal_payout_id, _status = crear_pago_proveedor(
                        compra.supplier, form.cleaned_data['valor'], referencia,
                    )
                except PayPalError as e:
                    messages.error(request, str(e))
                    return render(request, 'pagos/pago_form.html', {
                        'form': form, 'compra': compra, 'title': 'Registrar Pago',
                    })

            pago = form.save(commit=False)
            pago.compra = compra
            # Los campos de tarjeta solo se guardan si de verdad se pagó con
            # tarjeta — evita que quede una constancia de tarjeta "fantasma"
            # si el usuario la llenó y después cambió la forma de pago antes
            # de enviar (mismo criterio que billing/views.py -> _finalizar_venta).
            if forma_pago != PagoCompra.TARJETA:
                pago.tarjeta_titular = pago.tarjeta_cvv = pago.tarjeta_expiracion = None
            pago.paypal_payout_id = paypal_payout_id
            try:
                with transaction.atomic():
                    pago.save()
                    if sesion_caja and forma_pago == PagoCompra.EFECTIVO:
                        MovimientoCaja.objects.create(
                            sesion=sesion_caja, tipo=MovimientoCaja.EGRESO, monto=pago.valor,
                            concepto=f'Pago compra #{compra.id:04d} - {compra.supplier.name}',
                            pago_compra=pago,
                        )
            except ValidationError as e:
                messages.error(request, ' '.join(e.messages))
            else:
                compra.refresh_from_db()
                messages.success(
                    request,
                    f'Pago de ${pago.valor} registrado. Saldo restante: ${compra.saldo}'
                )
                _enviar_comprobante_pago(pago, compra)
                return redirect('pagos:purchase_pending_list')
    else:
        form = PagoCompraForm(compra=compra)

    return render(request, 'pagos/pago_form.html', {
        'form': form, 'compra': compra, 'title': 'Registrar Pago',
    })


# Historial completo de pagos (todas las compras), con filtro opcional por
# número de documento de la compra.
@permission_required_redirect('pagos.access_pagocompra_module', '/')
def pago_list(request):
    query = request.GET.get('q', '')
    compra_id = request.GET.get('compra', '')

    pagos = PagoCompra.objects.select_related('compra', 'compra__supplier').all()
    if query:
        pagos = pagos.filter(compra__document_number__icontains=query)

    compra_filtro = None
    if compra_id:
        pagos = pagos.filter(compra_id=compra_id)
        compra_filtro = get_object_or_404(Purchase, pk=compra_id)

    paginator = Paginator(pagos, 10)
    page_obj = paginator.get_page(request.GET.get('page'))

    context = {
        'items': page_obj,
        'page_obj': page_obj,
        'page_range': get_page_range(page_obj),
        'extra_qs': build_extra_qs(request),
        'query': query,
        'compra_filtro': compra_filtro,
    }
    return render(request, 'pagos/pago_list.html', context)


@permission_required_redirect('pagos.change_pagocompra', '/pagos/historial/')
def pago_update(request, pk):
    pago = get_object_or_404(PagoCompra, pk=pk)
    compra = pago.compra

    if request.method == 'POST':
        form = PagoCompraForm(request.POST, instance=pago, compra=compra)
        if form.is_valid():
            pago = form.save(commit=False)
            if form.cleaned_data.get('forma_pago') != PagoCompra.TARJETA:
                pago.tarjeta_titular = pago.tarjeta_cvv = pago.tarjeta_expiracion = None
            try:
                with transaction.atomic():
                    pago.save()
            except ValidationError as e:
                messages.error(request, ' '.join(e.messages))
            else:
                messages.success(request, 'Pago actualizado correctamente.')
                return redirect('pagos:pago_list')
    else:
        form = PagoCompraForm(instance=pago, compra=compra)

    return render(request, 'pagos/pago_form.html', {
        'form': form, 'compra': compra, 'title': 'Editar Pago', 'pago': pago,
    })


# Arma el PDF del comprobante de UN pago (constancia de abono) y devuelve
# los bytes crudos — lo usan tanto pago_pdf (descarga manual) como
# pago_create/pago_update (adjunto del correo al proveedor), para no
# duplicar el diseño del comprobante en dos lugares.
def _build_pago_pdf(pago):
    from reportlab.lib.pagesizes import letter
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib import colors
    from reportlab.lib.units import cm
    import io

    compra = pago.compra

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
        [Paragraph('<b>COMPROBANTE DE PAGO</b>', ParagraphStyle('', parent=styles['Normal'], fontSize=14, fontName='Helvetica-Bold', textColor=colors.HexColor('#4e54c8'))),
         Paragraph(f'<b>Pago N°:</b> {pago.id:04d}', bold)],
        ['', Paragraph(f'<b>Fecha de Pago:</b> {pago.fecha.strftime("%d/%m/%Y")}', normal)],
        [Paragraph('<b>Proveedor:</b>', bold), Paragraph(f'{compra.supplier.name}', normal)],
        [Paragraph('<b>Compra N°:</b>', bold), Paragraph(f'{compra.id:04d} ({compra.document_number})', normal)],
        [Paragraph('<b>Forma de Pago:</b>', bold), Paragraph(pago.get_forma_pago_display(), normal)],
        [Paragraph('<b>Observación:</b>', bold), Paragraph(f'{pago.observacion or "-"}', normal)],
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
        ['', 'Total de la Compra:', f'${compra.total}'],
        ['', 'Valor de este Pago:', f'${pago.valor}'],
        ['', 'Saldo Pendiente:', f'${compra.saldo}'],
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
    story.append(Paragraph(f'Registro interno de pago a proveedor — {config.empresa_nombre}', sub_style))

    doc.build(story)
    buffer.seek(0)
    return buffer.read()


def _enviar_comprobante_pago(pago, compra):
    """
    Notifica el pago al proveedor por los dos canales disponibles: correo
    con el comprobante PDF adjunto, y WhatsApp con un resumen de texto (la
    API simple de Twilio no adjunta archivos sin alojarlos en una URL
    pública, así que por WhatsApp va solo el texto). Ninguno de los dos es
    requisito para que el pago se registre.
    """
    if compra.estado == Purchase.PAGADA:
        estado_msg = 'Con este abono, la compra ha quedado completamente cancelada.'
    else:
        estado_msg = f'El saldo pendiente de la compra es de ${compra.saldo}.'

    config = ConfiguracionSistema.get_solo()

    if compra.supplier.email:
        pdf_bytes = _build_pago_pdf(pago)
        subject = f'Comprobante de pago #{pago.id:04d} — {config.empresa_nombre}'
        body = (
            f'Estimado/a {compra.supplier.name},\n\n'
            f'Adjuntamos el comprobante del pago de ${pago.valor} registrado sobre la compra '
            f'#{compra.id:04d} ({compra.document_number}).\n'
            f'{estado_msg}\n\n'
            f'Atentamente,\n'
            f'{config.empresa_nombre}'
        )
        # OJO: no se pasa comprobante_url — es una vista interna protegida
        # por permiso (pagos.view_pagocompra), no tiene sentido para el
        # proveedor (no es un usuario del sistema); el PDF ya va adjunto acá.
        send_email_with_attachment(
            compra.supplier.email, subject, body,
            f'pago_{pago.id:04d}.pdf', pdf_bytes,
            html_template='pago_proveedor_realizado.html',
            html_context={
                'usuario': compra.supplier.name, 'proveedor_nombre': compra.supplier.name,
                'compra_numero': f'{compra.id:04d}', 'monto': f'${pago.valor}',
                'metodo_pago': pago.get_forma_pago_display(), 'fecha': pago.fecha.strftime('%d/%m/%Y'),
                'saldo_restante': None if compra.estado == Purchase.PAGADA else f'${compra.saldo}',
            },
        )

    if compra.supplier.phone:
        whatsapp_body = (
            f'{config.empresa_nombre} — Comprobante de pago #{pago.id:04d}\n'
            f'Compra #{compra.id:04d} ({compra.document_number}): pago de ${pago.valor} registrado.\n'
            f'{estado_msg}'
        )
        send_whatsapp_message(compra.supplier.phone, whatsapp_body)


@permission_required_redirect('pagos.view_pagocompra', '/pagos/historial/')
def pago_pdf(request, pk):
    from django.http import HttpResponse

    pago = get_object_or_404(PagoCompra.objects.select_related('compra', 'compra__supplier'), pk=pk)
    pdf_bytes = _build_pago_pdf(pago)
    response = HttpResponse(pdf_bytes, content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="pago_{pago.id:04d}.pdf"'
    return response


@permission_required_redirect('pagos.delete_pagocompra', '/pagos/historial/')
def pago_delete(request, pk):
    pago = get_object_or_404(PagoCompra, pk=pk)

    if request.method == 'POST':
        if pago.compra.estado == Purchase.PAGADA:
            messages.error(request, 'No se puede eliminar un pago de una compra ya cancelada.')
            return redirect('pagos:pago_list')
        try:
            with transaction.atomic():
                pago.delete()
        except ValidationError as e:
            messages.error(request, ' '.join(e.messages))
        else:
            messages.success(request, 'Pago eliminado correctamente.')
        return redirect('pagos:pago_list')

    return render(request, 'pagos/pago_confirm_delete.html', {'object': pago})
