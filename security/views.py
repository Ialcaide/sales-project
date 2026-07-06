from django.shortcuts import render, redirect
from django.contrib.auth import login
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.models import User, Group, Permission
from django.contrib.auth.views import LoginView, LogoutView
from django.contrib.auth.decorators import login_required
from django.urls import reverse_lazy
from django.views.generic import CreateView, UpdateView, DeleteView
from django.core.paginator import Paginator
from django.db import models

from shared.mixins import GroupRequiredMixin
from billing.export_mixins import ExportMixin
from .forms import UserRegisterForm, UserUpdateForm, GroupForm, PermissionForm


class AdminOnlyMixin(LoginRequiredMixin, GroupRequiredMixin):
    group_required = ['Administrador']
    group_redirect_url = '/'


def admin_required(view_func):
    """Decorador que verifica que el usuario sea Administrador."""
    @login_required
    def wrapper(request, *args, **kwargs):
        if request.user.is_superuser or request.user.groups.filter(name='Administrador').exists():
            return view_func(request, *args, **kwargs)
        from django.contrib import messages
        messages.error(request, 'No tienes permiso para acceder a esta opción.')
        return redirect('/')
    return wrapper


class RegisterView(CreateView):
    form_class = UserRegisterForm
    template_name = 'security/register.html'
    success_url = reverse_lazy('home')

    def form_valid(self, form):
        response = super().form_valid(form)
        login(self.request, self.object)
        return response


class SecurityLoginView(LoginView):
    template_name = 'registration/login.html'


class SecurityLogoutView(LogoutView):
    pass


# === USUARIOS ===
@admin_required
def user_list(request):
    query = request.GET.get('q', '')
    is_active = request.GET.get('is_active', '')
    group_id = request.GET.get('group', '')
    export = request.GET.get('export', '')

    items = User.objects.prefetch_related('groups').all()

    if query:
        items = items.filter(
            models.Q(username__icontains=query) |
            models.Q(first_name__icontains=query) |
            models.Q(last_name__icontains=query) |
            models.Q(email__icontains=query)
        )
    if is_active == '1':
        items = items.filter(is_active=True)
    elif is_active == '0':
        items = items.filter(is_active=False)
    if group_id:
        items = items.filter(groups__id=group_id)

    items = items.distinct()

    if export in ('pdf', 'excel'):
        exporter = ExportMixin()
        exporter.export_filename = 'usuarios'
        exporter.export_title = 'Listado de Usuarios'
        exporter.export_headers = ['Usuario', 'Nombre', 'Correo', 'Roles', 'Activo']
        exporter.get_export_rows = lambda qs: [
            [
                u.username,
                f'{u.first_name} {u.last_name}'.strip() or '-',
                u.email or '-',
                ', '.join(g.name for g in u.groups.all()) or 'Sin rol',
                'Sí' if u.is_active else 'No',
            ]
            for u in qs
        ]
        if export == 'pdf':
            return exporter.export_to_pdf(items)
        else:
            return exporter.export_to_excel(items)

    paginator = Paginator(items, 10)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    context = {
        'page_obj': page_obj,
        'query': query,
        'is_active': is_active,
        'selected_group': group_id,
        'groups': Group.objects.all(),
    }
    return render(request, 'security/user_list.html', context)


class UserUpdateView(AdminOnlyMixin, UpdateView):
    model = User
    form_class = UserUpdateForm
    template_name = 'security/user_form.html'
    success_url = reverse_lazy('security:user_list')


class UserDeleteView(AdminOnlyMixin, DeleteView):
    model = User
    template_name = 'security/confirm_delete.html'
    success_url = reverse_lazy('security:user_list')


# === ROLES ===
@admin_required
def group_list(request):
    query = request.GET.get('q', '')
    export = request.GET.get('export', '')

    items = Group.objects.all()

    if query:
        items = items.filter(name__icontains=query)

    if export in ('pdf', 'excel'):
        exporter = ExportMixin()
        exporter.export_filename = 'roles'
        exporter.export_title = 'Listado de Roles'
        exporter.export_headers = ['Nombre del Rol', 'N° Permisos', 'N° Usuarios']
        exporter.get_export_rows = lambda qs: [
            [
                g.name,
                g.permissions.count(),
                g.user_set.count(),
            ]
            for g in qs
        ]
        if export == 'pdf':
            return exporter.export_to_pdf(items)
        else:
            return exporter.export_to_excel(items)

    paginator = Paginator(items, 10)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    context = {
        'page_obj': page_obj,
        'query': query,
    }
    return render(request, 'security/group_list.html', context)


class GroupCreateView(AdminOnlyMixin, CreateView):
    model = Group
    form_class = GroupForm
    template_name = 'security/group_form.html'
    success_url = reverse_lazy('security:group_list')


class GroupUpdateView(AdminOnlyMixin, UpdateView):
    model = Group
    form_class = GroupForm
    template_name = 'security/group_form.html'
    success_url = reverse_lazy('security:group_list')


class GroupDeleteView(AdminOnlyMixin, DeleteView):
    model = Group
    template_name = 'security/confirm_delete.html'
    success_url = reverse_lazy('security:group_list')


# === PERMISOS ===
@admin_required
def permission_list(request):
    query = request.GET.get('q', '')
    export = request.GET.get('export', '')

    items = Permission.objects.select_related('content_type').all()

    if query:
        items = items.filter(
            models.Q(name__icontains=query) |
            models.Q(codename__icontains=query) |
            models.Q(content_type__model__icontains=query)
        )

    if export in ('pdf', 'excel'):
        exporter = ExportMixin()
        exporter.export_filename = 'permisos'
        exporter.export_title = 'Listado de Permisos'
        exporter.export_headers = ['Nombre', 'Codename', 'Modelo']
        exporter.get_export_rows = lambda qs: [
            [p.name, p.codename, p.content_type.model]
            for p in qs
        ]
        if export == 'pdf':
            return exporter.export_to_pdf(items)
        else:
            return exporter.export_to_excel(items)

    paginator = Paginator(items, 15)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    context = {
        'page_obj': page_obj,
        'query': query,
    }
    return render(request, 'security/permission_list.html', context)


class PermissionCreateView(AdminOnlyMixin, CreateView):
    model = Permission
    form_class = PermissionForm
    template_name = 'security/permission_form.html'
    success_url = reverse_lazy('security:permission_list')


class PermissionUpdateView(AdminOnlyMixin, UpdateView):
    model = Permission
    form_class = PermissionForm
    template_name = 'security/permission_form.html'
    success_url = reverse_lazy('security:permission_list')


class PermissionDeleteView(AdminOnlyMixin, DeleteView):
    model = Permission
    template_name = 'security/confirm_delete.html'
    success_url = reverse_lazy('security:permission_list')