from django.contrib import messages
from django.shortcuts import redirect


class StaffRequiredMixin:
    """
    Mixin que verifica si el usuario es miembro del staff.
    Si no es staff, redirige con mensaje de error.
    """

    staff_redirect_url = '/'
    staff_error_message = 'No tienes permiso para realizar esta acción. Se requiere acceso de staff.'

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_staff:
            messages.error(request, self.staff_error_message)
            return redirect(self.staff_redirect_url)
        return super().dispatch(request, *args, **kwargs)
    
class GroupRequiredMixin:
    """
    Mixin que verifica si el usuario pertenece a alguno
    de los roles (grupos) indicados en group_required.
    """
    group_required = []
    group_redirect_url = '/'
    group_error_message = 'You do not have permission to access this option.'

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect('login')
        if request.user.is_superuser:
            return super().dispatch(request, *args, **kwargs)
        if request.user.groups.filter(name__in=self.group_required).exists():
            return super().dispatch(request, *args, **kwargs)
        messages.error(request, self.group_error_message)
        return redirect(self.group_redirect_url)