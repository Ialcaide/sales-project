from django.contrib import messages
from django.shortcuts import redirect

# Un "mixin" es una clase pensada para heredarse JUNTO con otra (nunca sola).
# Las CBV de Django (CreateView, UpdateView, etc.) llaman a self.dispatch()
# como primer paso al recibir cualquier request; estos mixins se meten antes
# en la cadena de herencia para revisar algo (login, grupo, permiso) y cortar
# la petición ANTES de que llegue a la vista real, si no corresponde.
#
# Por eso el orden de herencia importa, por ejemplo:
#   class ProductDeleteView(LoginRequiredMixin, PermissionRequiredRedirectMixin, DeleteView):
# Python revisa el dispatch() de LoginRequiredMixin primero, luego el de
# PermissionRequiredRedirectMixin, y solo al final llega al de DeleteView.


class StaffRequiredMixin:
    """
    Mixin que verifica si el usuario es miembro del staff (User.is_staff=True).
    Si no es staff, redirige con mensaje de error.
    Ya no se usa en las vistas de negocio (billing/purchasing) — esas ahora
    usan PermissionRequiredRedirectMixin, más preciso. Se deja disponible por
    si necesitas un chequeo simple de "es staff" en algo nuevo.
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
    Mixin que verifica si el usuario pertenece a alguno de los roles (grupos)
    indicados en group_required, ej. group_required = ['Administrador'].
    Los superusuarios siempre pasan, sin importar a qué grupo pertenezcan.

    Es un chequeo por NOMBRE de rol (más rígido). Para vistas nuevas se
    recomienda PermissionRequiredRedirectMixin en su lugar, que chequea el
    permiso real y se actualiza solo si cambias los permisos del rol desde
    la interfaz, sin tocar código.
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


class PermissionRequiredRedirectMixin:
    """
    Mixin que verifica el permiso Django real (has_perm) del usuario, ligado
    a los roles gestionados en Seguridad > Gestión de Permisos. Si no tiene
    el permiso, redirige con un mensaje de error en vez del 403 crudo que
    Django mostraría con PermissionRequiredMixin (el que trae Django de
    fábrica) — por eso este mixin propio, para mantener la misma experiencia
    de "mensaje + redirect" que StaffRequiredMixin/GroupRequiredMixin.

    Uso:
        class ProductDeleteView(LoginRequiredMixin, PermissionRequiredRedirectMixin, DeleteView):
            model = Product
            permission_required = 'billing.delete_product'
            permission_redirect_url = '/products/'

    has_perms() ya resuelve todo esto por vos (no hay que reimplementarlo):
    - Superusuario -> siempre True.
    - ¿Tiene el permiso asignado directo a su usuario? -> True.
    - ¿Alguno de sus roles (Group) tiene ese permiso? -> True.
    - Si ninguna de las anteriores -> False.
    """
    permission_required = None
    permission_redirect_url = '/'
    permission_error_message = 'No tienes permiso para realizar esta acción.'

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect('login')
        perms = self.permission_required
        if isinstance(perms, str):
            perms = (perms,)  # has_perms() espera una lista/tupla, aunque sea de un solo permiso
        if request.user.has_perms(perms):
            return super().dispatch(request, *args, **kwargs)
        messages.error(request, self.permission_error_message)
        return redirect(self.permission_redirect_url)
