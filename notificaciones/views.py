from django.contrib import messages
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render

from shared.decorators import permission_required_redirect
from shared.pagination import build_extra_qs, get_page_range

from .models import Notificacion


def _visibles_para(user):
    """Las dirigidas a este usuario + las generales (usuario=None)."""
    from django.db.models import Q
    return Notificacion.objects.filter(Q(usuario=user) | Q(usuario__isnull=True))


@permission_required_redirect('notificaciones.view_notificacion', '/')
def notificacion_list(request):
    tipo = request.GET.get('tipo', '')
    estado = request.GET.get('estado', '')  # 'leidas' / 'no_leidas' / ''

    notificaciones = _visibles_para(request.user)
    if tipo:
        notificaciones = notificaciones.filter(tipo=tipo)
    if estado == 'leidas':
        notificaciones = notificaciones.filter(leida=True)
    elif estado == 'no_leidas':
        notificaciones = notificaciones.filter(leida=False)

    paginator = Paginator(notificaciones, 15)
    page_obj = paginator.get_page(request.GET.get('page'))

    context = {
        'items': page_obj,
        'page_obj': page_obj,
        'page_range': get_page_range(page_obj),
        'extra_qs': build_extra_qs(request),
        'tipo': tipo,
        'estado': estado,
        'tipo_choices': Notificacion.TIPO_CHOICES,
    }
    return render(request, 'notificaciones/notificacion_list.html', context)


@permission_required_redirect('notificaciones.change_notificacion', '/')
def notificacion_marcar_leida(request, pk):
    notificacion = get_object_or_404(_visibles_para(request.user), pk=pk)
    if request.method == 'POST':
        notificacion.leida = True
        notificacion.save(update_fields=['leida'])
        if notificacion.url:
            return redirect(notificacion.url)
    return redirect('notificaciones:notificacion_list')


@permission_required_redirect('notificaciones.change_notificacion', '/')
def notificacion_marcar_todas_leidas(request):
    if request.method == 'POST':
        count = _visibles_para(request.user).filter(leida=False).update(leida=True)
        messages.success(request, f'{count} notificación(es) marcada(s) como leída(s).')
    return redirect('notificaciones:notificacion_list')
