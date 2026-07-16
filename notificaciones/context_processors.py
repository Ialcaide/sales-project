from django.db.models import Q

from .models import Notificacion


def notificaciones(request):
    """Agrega el contador y las últimas notificaciones sin leer a todos los templates,
    para poder pintar la campanita del navbar sin que cada vista tenga que pasarlas."""
    if not request.user.is_authenticated:
        return {}

    qs = Notificacion.objects.filter(
        Q(usuario=request.user) | Q(usuario__isnull=True),
        leida=False,
    )
    return {
        'notificaciones_no_leidas': qs.count(),
        'notificaciones_recientes': qs[:5],
    }
