import logging
from functools import wraps
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect
from django.utils import timezone

logger = logging.getLogger('audit')


def permission_required_redirect(perm, redirect_url='/'):
    """
    Decorador que exige el permiso Django real (has_perm) del usuario,
    ligado a los roles gestionados en Seguridad > Gestión de Permisos.
    Mismo patrón que admin_required pero parametrizado por permiso.
    """
    def decorator(view_func):
        @login_required
        @wraps(view_func)
        def wrapper(request, *args, **kwargs):
            if request.user.has_perm(perm):
                return view_func(request, *args, **kwargs)
            messages.error(request, 'No tienes permiso para realizar esta acción.')
            return redirect(redirect_url)
        return wrapper
    return decorator


def audit_action(action_name):
    """
    Decorador que registra las acciones del usuario para auditoría.
    """

    def decorator(view_func):
        @wraps(view_func)
        def wrapper(request, *args, **kwargs):
            user = request.user.username if request.user.is_authenticated else 'Anonymous'
            ip = request.META.get('REMOTE_ADDR', 'unknown')
            method = request.method
            timestamp = timezone.now().strftime('%Y-%m-%d %H:%M:%S')
            path = request.path

            logger.info(
                f'[AUDIT] {timestamp} | User: {user} | '
                f'Action: {action_name} | Method: {method} | '
                f'Path: {path} | IP: {ip}'
            )
            print(
                f'\n[AUDIT] {timestamp} | User: {user} | '
                f'Action: {action_name} | Method: {method} | '
                f'Path: {path} | IP: {ip}'
            )

            response = view_func(request, *args, **kwargs)

            if method == 'POST':
                print(f'[AUDIT] {timestamp} | COMPLETED: {action_name} by {user}')

            return response

        return wrapper
    return decorator