from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db.models import Sum
from django.shortcuts import get_object_or_404, redirect, render

from billing.models import Invoice
from caja.models import SesionCaja
from shared.decorators import permission_required_redirect
from shared.pagination import build_extra_qs, get_page_range

from .forms import DevolucionMotivoForm
from .models import DevolucionDetalle, DevolucionVenta, registrar_devolucion


@permission_required_redirect('devoluciones.add_devolucionventa', '/invoices/')
def devolucion_create(request, factura_id):
    factura = get_object_or_404(
        Invoice.objects.select_related('customer').prefetch_related('details__product'), pk=factura_id
    )

    if not factura.is_active:
        messages.error(request, f'La factura #{factura.id:04d} está anulada, no admite devoluciones.')
        return redirect('billing:invoice_detail', pk=factura.pk)

    # Cuánto se puede devolver de cada línea (lo vendido menos lo ya devuelto).
    lineas_disponibles = []
    for detail in factura.details.all():
        ya_devuelta = DevolucionDetalle.objects.filter(invoice_detail=detail).aggregate(
            total=Sum('quantity')
        )['total'] or 0
        disponible = detail.quantity - ya_devuelta
        if disponible > 0:
            lineas_disponibles.append({'detail': detail, 'disponible': disponible})

    if request.method == 'POST':
        form = DevolucionMotivoForm(request.POST)
        lineas = []
        for item in lineas_disponibles:
            detail = item['detail']
            cantidad = request.POST.get(f'cantidad_{detail.id}', '').strip()
            if cantidad:
                try:
                    cantidad = int(cantidad)
                except ValueError:
                    cantidad = 0
                if cantidad > 0:
                    lineas.append((detail, cantidad))

        if form.is_valid():
            sesion_caja = SesionCaja.objects.filter(usuario=request.user, estado=SesionCaja.ABIERTA).first()
            try:
                devolucion = registrar_devolucion(
                    factura=factura, motivo=form.cleaned_data['motivo'],
                    usuario=request.user, lineas=lineas, sesion_caja=sesion_caja,
                )
            except ValidationError as e:
                messages.error(request, ' '.join(e.messages))
            else:
                messages.success(
                    request,
                    f'Devolución #{devolucion.id:04d} registrada por ${devolucion.total}. '
                    f'Nuevo total de la factura: ${factura.total}.'
                )
                return redirect('billing:invoice_detail', pk=factura.pk)
    else:
        form = DevolucionMotivoForm()

    return render(request, 'devoluciones/devolucion_form.html', {
        'form': form, 'factura': factura, 'lineas_disponibles': lineas_disponibles,
    })


@permission_required_redirect('devoluciones.access_devolucionventa_module', '/')
def devolucion_list(request):
    query = request.GET.get('q', '')

    devoluciones = DevolucionVenta.objects.select_related('factura', 'factura__customer', 'usuario').all()
    if query:
        devoluciones = devoluciones.filter(factura__customer__last_name__icontains=query)

    paginator = Paginator(devoluciones, 10)
    page_obj = paginator.get_page(request.GET.get('page'))

    context = {
        'items': page_obj,
        'page_obj': page_obj,
        'page_range': get_page_range(page_obj),
        'extra_qs': build_extra_qs(request),
        'query': query,
    }
    return render(request, 'devoluciones/devolucion_list.html', context)


@permission_required_redirect('devoluciones.view_devolucionventa', '/')
def devolucion_detail(request, pk):
    devolucion = get_object_or_404(
        DevolucionVenta.objects.select_related('factura', 'factura__customer', 'usuario')
        .prefetch_related('detalles__invoice_detail__product'),
        pk=pk,
    )
    return render(request, 'devoluciones/devolucion_detail.html', {'devolucion': devolucion})
