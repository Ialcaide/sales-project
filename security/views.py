from django.conf import settings
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.models import User, Group, Permission
from django.contrib.auth.tokens import default_token_generator
from django.contrib.auth.views import LoginView, LogoutView
from django.contrib.auth.decorators import login_required
from django.urls import reverse_lazy, reverse
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from django.views.generic import CreateView, UpdateView, DeleteView, DetailView, FormView
from django.core.paginator import Paginator
from django.db import models

from shared.mixins import GroupRequiredMixin
from shared.notifications import send_credentials_email, send_whatsapp_message
from billing.export_mixins import ExportMixin
from .forms import UserRegisterForm, UserUpdateForm, GroupForm, PermissionForm, RecoverCredentialsForm


def _full_name(user):
    return f'{user.first_name} {user.last_name}'.strip() or user.username


def _account_created_message(user, password, role):
    login_url = f'{settings.SITE_URL}{reverse("security:login")}'
    body = (
        f'Estimado/a {_full_name(user)},\n\n'
        f'Su cuenta ha sido creada exitosamente en el Sistema de Ventas TecnoStock.\n\n'
        f'A continuación, sus credenciales de acceso:\n\n'
        f'Usuario: {user.username}\n'
        f'Contraseña: {password}\n'
        f'Rol asignado: {role.name}\n\n'
        f'Por favor, ingrese al sistema a través del siguiente enlace:\n'
        f'{login_url}\n\n'
        f'Le recomendamos cambiar su contraseña después de su primer inicio de sesión.\n\n'
        f'Atentamente,\n'
        f'Administración — Sistema de Ventas TecnoStock'
    )
    subject = 'Creación de Cuenta — Sistema de Ventas TecnoStock'
    return subject, body


def _account_updated_message(user):
    login_url = f'{settings.SITE_URL}{reverse("security:login")}'
    roles = ', '.join(g.name for g in user.groups.all()) or 'Sin rol asignado'
    body = (
        f'Estimado/a {_full_name(user)},\n\n'
        f'Le informamos que su cuenta en el Sistema de Ventas TecnoStock ha sido actualizada '
        f'por el administrador.\n\n'
        f'Datos actuales de su cuenta:\n\n'
        f'Usuario: {user.username}\n'
        f'Correo: {user.email}\n'
        f'Rol(es): {roles}\n'
        f'Estado: {"Activo" if user.is_active else "Inactivo"}\n\n'
        f'Puede ingresar al sistema a través del siguiente enlace:\n'
        f'{login_url}\n\n'
        f'Si usted no reconoce este cambio, contacte al administrador del sistema.\n\n'
        f'Atentamente,\n'
        f'Administración — Sistema de Ventas TecnoStock'
    )
    subject = 'Actualización de Cuenta — Sistema de Ventas TecnoStock'
    return subject, body


class AdminOnlyMixin(LoginRequiredMixin, GroupRequiredMixin):
    group_required = ['Administrador']
    group_redirect_url = '/'


def admin_required(view_func):
    """Decorador que verifica que el usuario sea Administrador."""
    @login_required
    def wrapper(request, *args, **kwargs):
        if request.user.is_superuser or request.user.groups.filter(name='Administrador').exists():
            return view_func(request, *args, **kwargs)
        messages.error(request, 'No tienes permiso para acceder a esta opción.')
        return redirect('/')
    return wrapper


class RegisterView(AdminOnlyMixin, CreateView):
    form_class = UserRegisterForm
    template_name = 'security/register.html'
    success_url = reverse_lazy('security:user_list')

    def form_valid(self, form):
        password = form.cleaned_data['password1']
        phone = form.cleaned_data['phone']
        role = form.cleaned_data['role']
        response = super().form_valid(form)

        subject, body = _account_created_message(self.object, password, role)
        email_sent = send_credentials_email(self.object.email, subject, body)
        whatsapp_sent = send_whatsapp_message(phone, body)

        if email_sent and whatsapp_sent:
            messages.success(self.request, f'Usuario "{self.object.username}" creado. Credenciales enviadas por correo y WhatsApp.')
        elif email_sent:
            messages.warning(self.request, f'Usuario "{self.object.username}" creado. Credenciales enviadas por correo (WhatsApp no disponible por ahora).')
        else:
            messages.warning(self.request, f'Usuario "{self.object.username}" creado, pero no se pudo enviar las credenciales automáticamente.')
        return response


class SecurityLoginView(LoginView):
    template_name = 'registration/login.html'


class SecurityLogoutView(LogoutView):
    pass


class RecoverCredentialsView(FormView):
    form_class = RecoverCredentialsForm
    template_name = 'security/recover_credentials.html'
    success_url = reverse_lazy('security:login')

    def form_valid(self, form):
        email = form.cleaned_data['email']
        channel = form.cleaned_data['channel']
        user = User.objects.filter(email__iexact=email, is_active=True).first()

        if user:
            uid = urlsafe_base64_encode(force_bytes(user.pk))
            token = default_token_generator.make_token(user)
            reset_url = (
                f'{settings.SITE_URL}'
                f'{reverse("password_reset_confirm", kwargs={"uidb64": uid, "token": token})}'
            )
            body = (
                f'Estimado/a {_full_name(user)},\n\n'
                f'Solicitó recuperar el acceso al Sistema de Ventas TecnoStock. '
                f'Ingrese al siguiente enlace para restablecer su contraseña:\n\n'
                f'{reset_url}\n\n'
                f'Si usted no solicitó esto, ignore este mensaje.\n\n'
                f'Atentamente,\n'
                f'Administración — Sistema de Ventas TecnoStock'
            )
            if channel == 'whatsapp':
                profile = getattr(user, 'profile', None)
                if profile and profile.phone:
                    send_whatsapp_message(profile.phone, body)
                else:
                    messages.error(self.request, 'Este usuario no tiene un número de WhatsApp registrado. Intenta con correo.')
                    return self.render_to_response(self.get_context_data(form=form))
            else:
                send_credentials_email(user.email, 'Recuperación de Credenciales — Sistema de Ventas TecnoStock', body)

        messages.success(self.request, 'Si los datos son correctos, te hemos enviado instrucciones para recuperar tu acceso.')
        return super().form_valid(form)


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


class UserDetailView(AdminOnlyMixin, DetailView):
    model = User
    template_name = 'security/user_detail.html'
    context_object_name = 'viewed_user'


class UserUpdateView(AdminOnlyMixin, UpdateView):
    model = User
    form_class = UserUpdateForm
    template_name = 'security/user_form.html'
    success_url = reverse_lazy('security:user_list')

    def form_valid(self, form):
        response = super().form_valid(form)

        subject, body = _account_updated_message(self.object)
        email_sent = send_credentials_email(self.object.email, subject, body)
        profile = getattr(self.object, 'profile', None)
        whatsapp_sent = send_whatsapp_message(profile.phone if profile else '', body)

        if email_sent or whatsapp_sent:
            messages.success(self.request, f'Usuario "{self.object.username}" actualizado. Se notificó el cambio al usuario.')
        else:
            messages.success(self.request, f'Usuario "{self.object.username}" actualizado.')
        return response


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


MODEL_TRANSLATIONS = {
    'brand': 'marca',
    'product group': 'grupo de productos',
    'productgroup': 'grupo de productos',
    'supplier': 'proveedor',
    'product': 'producto',
    'customer': 'cliente',
    'invoice': 'factura',
    'purchase': 'compra',
    'user': 'usuario',
    'group': 'rol / grupo',
    'permission': 'permiso',
    'content type': 'tipo de contenido',
    'session': 'sesión',
    'log entry': 'registro de auditoría',
    'logentry': 'registro de auditoría',
    'customerprofile': 'perfil de cliente',
    'invoicedetail': 'detalle de factura',
    'purchasedetail': 'detalle de compra',
}

def translate_permission_name(name):
    if not name:
        return name
    parts = name.split(' ')
    if len(parts) >= 3 and parts[0] == 'Can':
        action = parts[1]
        model_name = ' '.join(parts[2:])
        
        action_es = action
        if action == 'add':
            action_es = 'Puede agregar'
        elif action == 'change':
            action_es = 'Puede modificar'
        elif action == 'delete':
            action_es = 'Puede eliminar'
        elif action == 'view':
            action_es = 'Puede ver'
            
        model_es = MODEL_TRANSLATIONS.get(model_name.lower(), model_name)
        return f'{action_es} {model_es.lower()}'
    return name


ACTION_LABELS = {'view': 'Ver', 'add': 'Agregar', 'change': 'Editar', 'delete': 'Eliminar'}
ACTION_ICONS = {'view': 'bi-eye', 'add': 'bi-plus-circle', 'change': 'bi-pencil', 'delete': 'bi-trash'}
ACTION_ORDER = ['view', 'add', 'change', 'delete']


def _permission_action(codename):
    prefix = codename.split('_', 1)[0]
    return prefix if prefix in ACTION_LABELS else None


# === PERMISOS ===
@admin_required
def permission_list(request):
    groups = Group.objects.all().order_by('name')
    all_users = User.objects.filter(is_active=True).order_by('username')

    # Acción rápida: otorgar TODOS los permisos a un usuario
    if request.method == 'POST' and request.POST.get('grant_all_user_id'):
        try:
            target_user = User.objects.get(id=request.POST['grant_all_user_id'])
            target_user.user_permissions.set(Permission.objects.all())
            messages.success(request, f'Se otorgaron todos los permisos a "{target_user.username}".')
        except User.DoesNotExist:
            messages.error(request, 'Usuario no encontrado.')
        return redirect(request.get_full_path())

    # Guardar los permisos marcados para el rol/usuario seleccionado
    if request.method == 'POST' and request.POST.get('target_type'):
        target_type = request.POST.get('target_type')
        target_id = request.POST.get('target_id')
        submitted_ids = [int(pid) for pid in request.POST.getlist('perm_ids')]

        if target_type == 'group':
            target_obj = get_object_or_404(Group, id=target_id)
            target_obj.permissions.set(submitted_ids)
            messages.success(request, f'Permisos actualizados para el rol "{target_obj.name}".')
        else:
            target_obj = get_object_or_404(User, id=target_id)
            target_obj.user_permissions.set(submitted_ids)
            messages.success(request, f'Permisos actualizados para el usuario "{target_obj.username}".')

        return redirect(f"{reverse('security:permission_list')}?target_type={target_type}&target_id={target_id}")

    user_q = request.GET.get('user_q', '')
    target_type = request.GET.get('target_type', 'group')
    target_id = request.GET.get('target_id', '')

    filtered_users = all_users
    if user_q:
        filtered_users = filtered_users.filter(
            models.Q(username__icontains=user_q) |
            models.Q(first_name__icontains=user_q) |
            models.Q(last_name__icontains=user_q)
        )

    # Determinar el rol/usuario seleccionado (por defecto, el primer rol)
    target = None
    if target_type == 'user' and target_id:
        target = User.objects.filter(id=target_id).first()
    elif target_type == 'group' and target_id:
        target = Group.objects.filter(id=target_id).first()
    if target is None:
        target = groups.first()
        target_type = 'group'

    assigned_ids = set()
    if target is not None:
        if target_type == 'group':
            assigned_ids = set(target.permissions.values_list('id', flat=True))
        else:
            assigned_ids = set(target.user_permissions.values_list('id', flat=True))

    # Armar los cuadros por modelo, cada uno con sus casillas Ver/Agregar/Editar/Eliminar
    permissions = Permission.objects.select_related('content_type').order_by(
        'content_type__app_label', 'content_type__model', 'codename'
    )
    model_cards = {}
    for p in permissions:
        ct = p.content_type
        key = (ct.app_label, ct.model)
        if key not in model_cards:
            model_cards[key] = {
                'label': MODEL_TRANSLATIONS.get(ct.model.lower(), ct.model).capitalize(),
                'app_label': ct.app_label,
                'items': [],
            }
        action = _permission_action(p.codename)
        model_cards[key]['items'].append({
            'id': p.id,
            'label': ACTION_LABELS.get(action, translate_permission_name(p.name)),
            'icon': ACTION_ICONS.get(action, 'bi-key'),
            'order': ACTION_ORDER.index(action) if action in ACTION_ORDER else 99,
            'checked': p.id in assigned_ids,
        })
    for card in model_cards.values():
        card['items'].sort(key=lambda i: i['order'])
    model_cards = dict(sorted(model_cards.items(), key=lambda kv: kv[1]['label']))

    export = request.GET.get('export', '')
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
            return exporter.export_to_pdf(permissions)
        else:
            return exporter.export_to_excel(permissions)

    context = {
        'groups': groups,
        'all_users': all_users,
        'filtered_users': filtered_users,
        'user_q': user_q,
        'target_type': target_type,
        'target': target,
        'model_cards': model_cards,
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


@admin_required
def security_dashboard(request):
    total_users = User.objects.count()
    total_groups = Group.objects.count()
    total_permissions = Permission.objects.count()

    recent_users = User.objects.prefetch_related('groups').order_by('-id')[:5]

    context = {
        'total_users': total_users,
        'total_groups': total_groups,
        'total_permissions': total_permissions,
        'recent_users': recent_users,
    }
    return render(request, 'security/dashboard.html', context)