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