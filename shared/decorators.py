import logging
from functools import wraps
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect
from django.utils import timezone

logger = logging.getLogger('audit')

# Un decorador envuelve una vista (función) con lógica extra que corre
# ANTES/DESPUÉS de ella. La forma "decorador con argumentos" (permission_required_redirect,
# audit_action) siempre se ve así: función que RECIBE los argumentos ->
# adentro, una función 'decorator' que RECIBE la vista -> adentro, la
# función 'wrapper' que de verdad se ejecuta en cada request:
#
#   @permission_required_redirect('billing.add_product', '/products/')
#   def product_create(request): ...
#
# equivale a: product_create = permission_required_redirect('billing.add_product', '/products/')(product_create)
# — Python arma esa cadena de llamadas solo con el @.


def permission_required_redirect(perm, redirect_url='/'):
    """
    Decorador que exige el permiso Django real (has_perm) del usuario,
    ligado a los roles gestionados en Seguridad > Gestión de Permisos.
    Es el equivalente para vistas por FUNCIÓN de
    shared.mixins.PermissionRequiredRedirectMixin (que es para vistas por CLASE).

    Uso:
        @permission_required_redirect('billing.delete_brand', '/brands/')
        def brand_delete(request, pk): ...
    """
    def decorator(view_func):
        @login_required  # si no hay sesión, redirige al login antes de llegar a has_perm()
        @wraps(view_func)  # conserva el nombre/docstring original de la vista (útil para debug)
        def wrapper(request, *args, **kwargs):
            if request.user.has_perm(perm):
                return view_func(request, *args, **kwargs)
            messages.error(request, 'No tienes permiso para realizar esta acción.')
            return redirect(redirect_url)
        return wrapper
    return decorator


def audit_action(action_name):
    """
    Decorador que registra en el log (y en consola) quién hizo qué acción,
    cuándo, con qué método HTTP, en qué ruta y desde qué IP. Puramente
    informativo — no bloquea nada, solo deja rastro. Usado en las vistas de
    Brand como ejemplo (ver billing/views.py).
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
