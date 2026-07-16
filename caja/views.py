from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from notificaciones.services import notificar_caja_diferencia
from shared.decorators import permission_required_redirect
from shared.pagination import build_extra_qs, get_page_range

from .forms import MovimientoCajaForm, SesionCajaAbrirForm, SesionCajaCerrarForm
from .models import MovimientoCaja, SesionCaja


@permission_required_redirect('caja.add_sesioncaja', '/')
def caja_abrir(request):
    sesion_abierta = SesionCaja.objects.filter(usuario=request.user, estado=SesionCaja.ABIERTA).first()
    if sesion_abierta:
        messages.info(request, 'Ya tienes una caja abierta.')
        return redirect('caja:caja_detalle', pk=sesion_abierta.pk)

    if request.method == 'POST':
        form = SesionCajaAbrirForm(request.POST)
        if form.is_valid():
            sesion = form.save(commit=False)
            sesion.usuario = request.user
            sesion.save()
            messages.success(request, f'Caja #{sesion.id} abierta con ${sesion.monto_inicial}.')
            return redirect('caja:caja_detalle', pk=sesion.pk)
    else:
        form = SesionCajaAbrirForm()

    return render(request, 'caja/caja_abrir.html', {'form': form})


@permission_required_redirect('caja.view_sesioncaja', '/')
def caja_detalle(request, pk):
    sesion = get_object_or_404(SesionCaja, pk=pk)
    context = {
        'sesion': sesion,
        'movimientos': sesion.movimientos.all(),
    }
    return render(request, 'caja/caja_detalle.html', context)


@permission_required_redirect('caja.change_sesioncaja', '/')
def caja_cerrar(request, pk):
    sesion = get_object_or_404(SesionCaja, pk=pk)

    if sesion.estado == SesionCaja.CERRADA:
        messages.info(request, f'La caja #{sesion.id} ya estaba cerrada.')
        return redirect('caja:caja_detalle', pk=sesion.pk)

    if request.method == 'POST':
        form = SesionCajaCerrarForm(request.POST, instance=sesion)
        if form.is_valid():
            sesion = form.save(commit=False)
            sesion.estado = SesionCaja.CERRADA
            sesion.fecha_cierre = timezone.now()
            sesion.save()
            notificar_caja_diferencia(sesion)
            messages.success(
                request,
                f'Caja #{sesion.id} cerrada. Esperado: ${sesion.monto_esperado_cierre}, '
                f'contado: ${sesion.monto_contado_cierre}, diferencia: ${sesion.diferencia}.'
            )
            return redirect('caja:caja_detalle', pk=sesion.pk)
    else:
        form = SesionCajaCerrarForm(instance=sesion)

    return render(request, 'caja/caja_cerrar.html', {'form': form, 'sesion': sesion})


@permission_required_redirect('caja.add_movimientocaja', '/')
def movimiento_crear(request, pk):
    sesion = get_object_or_404(SesionCaja, pk=pk)

    if sesion.estado == SesionCaja.CERRADA:
        messages.error(request, 'No se pueden registrar movimientos en una caja ya cerrada.')
        return redirect('caja:caja_detalle', pk=sesion.pk)

    if request.method == 'POST':
        form = MovimientoCajaForm(request.POST)
        if form.is_valid():
            movimiento = form.save(commit=False)
            movimiento.sesion = sesion
            try:
                movimiento.save()
            except ValidationError as e:
                messages.error(request, ' '.join(e.messages))
            else:
                messages.success(request, f'{movimiento.get_tipo_display()} de ${movimiento.monto} registrado.')
                return redirect('caja:caja_detalle', pk=sesion.pk)
    else:
        form = MovimientoCajaForm()

    return render(request, 'caja/movimiento_form.html', {'form': form, 'sesion': sesion})


@permission_required_redirect('caja.access_sesioncaja_module', '/')
def caja_historial(request):
    query = request.GET.get('q', '')

    sesiones = SesionCaja.objects.select_related('usuario').all()
    if query:
        sesiones = sesiones.filter(usuario__username__icontains=query)

    paginator = Paginator(sesiones, 10)
    page_obj = paginator.get_page(request.GET.get('page'))

    context = {
        'items': page_obj,
        'page_obj': page_obj,
        'page_range': get_page_range(page_obj),
        'extra_qs': build_extra_qs(request),
        'query': query,
    }
    return render(request, 'caja/caja_historial.html', context)
