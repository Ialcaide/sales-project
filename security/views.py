import secrets
from datetime import datetime

from django.conf import settings
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.models import User, Group, Permission
from django.contrib.auth.password_validation import validate_password
from django.contrib.auth.tokens import default_token_generator
from django.contrib.auth.views import LoginView, LogoutView
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError as DjangoValidationError
from django.urls import reverse_lazy, reverse
from django.utils import timezone
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from django.views.generic import CreateView, UpdateView, DeleteView, DetailView, FormView
from django.core.paginator import Paginator
from django.db import models

from shared.mixins import GroupRequiredMixin
from shared.notifications import send_credentials_email, send_whatsapp_message
from shared.pagination import build_extra_qs, get_page_range
from billing.export_mixins import ExportMixin
from .forms import (
    UserRegisterForm, UserUpdateForm, GroupForm, PermissionForm,
    RecoverCredentialsForm, ProfileForm, PasswordChangeCodeForm,
)


# ---------------------------------------------------------------------------
# Helpers de mensajes: arman el asunto/cuerpo de los correos y WhatsApp que
# se envían automáticamente al crear/editar un usuario o recuperar acceso.
# Viven acá (no en shared/notifications.py) porque el CONTENIDO del mensaje
# es específico de este dominio (usuarios/credenciales); shared/notifications.py
# solo sabe "enviar un email" o "enviar un whatsapp", no le importa qué dice.
# ---------------------------------------------------------------------------

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


# AdminOnlyMixin: atajo para no repetir "LoginRequiredMixin, GroupRequiredMixin,
# group_required=['Administrador']" en cada vista de este archivo. Se usa en
# TODAS las vistas de Usuarios/Roles/Permisos, ya que solo un administrador
# debe poder gestionarlos.
class AdminOnlyMixin(LoginRequiredMixin, GroupRequiredMixin):
    group_required = ['Administrador']
    group_redirect_url = '/'


def admin_required(view_func):
    """Igual que AdminOnlyMixin, pero para vistas por función (FBV) en vez de por clase."""
    @login_required
    def wrapper(request, *args, **kwargs):
        if request.user.is_superuser or request.user.groups.filter(name='Administrador').exists():
            return view_func(request, *args, **kwargs)
        messages.error(request, 'No tienes permiso para acceder a esta opción.')
        return redirect('/')
    return wrapper


class RegisterView(AdminOnlyMixin, CreateView):
    """
    Alta de un usuario nuevo (solo administradores). NO es un registro público:
    no hay ningún link a esta vista para un visitante anónimo (el login usa
    "Recuperar credenciales" en su lugar, ver RecoverCredentialsView).
    """
    form_class = UserRegisterForm
    template_name = 'security/register.html'
    success_url = reverse_lazy('security:user_list')

    def form_valid(self, form):
        # cleaned_data solo existe DESPUÉS de que el formulario validó bien.
        # Guardamos la contraseña en texto plano ANTES de guardar el form
        # porque es la única vez que la tenemos disponible: super().form_valid()
        # ya la deja encriptada en la base de datos.
        password = form.cleaned_data['password1']
        phone = form.cleaned_data['phone']
        role = form.cleaned_data['role']
        response = super().form_valid(form)  # crea el User (form.save() + self.object = user)

        # Armamos el mensaje y lo mandamos por los dos canales. Cada envío
        # devuelve True/False (nunca lanza una excepción) para poder avisarle
        # al admin qué canal sí/no funcionó, sin romper la creación del usuario.
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
    """LoginView de Django, solo cambiando el template (mismo login que /accounts/login/)."""
    template_name = 'registration/login.html'


class SecurityLogoutView(LogoutView):
    pass


class RecoverCredentialsView(FormView):
    """
    "¿Olvidaste tu contraseña?" — pantalla pública (no requiere login). El
    usuario da su correo y elige canal; si existe una cuenta con ese correo,
    se genera un link de restablecimiento y se envía por ese canal.

    El link usa el mecanismo de tokens de Django (uidb64 + token), el MISMO
    que usa el flujo estándar django.contrib.auth.views.PasswordResetView —
    por eso apunta a la url 'password_reset_confirm' (ya la trae Django solo
    con tener 'django.contrib.auth.urls' incluido en config/urls.py). No
    reinventamos la generación/verificación del token, solo el paso de "cómo
    se lo avisamos al usuario" (correo o WhatsApp, a elección).
    """
    form_class = RecoverCredentialsForm
    template_name = 'security/recover_credentials.html'
    success_url = reverse_lazy('security:login')

    def form_valid(self, form):
        email = form.cleaned_data['email']
        channel = form.cleaned_data['channel']
        user = User.objects.filter(email__iexact=email, is_active=True).first()

        # OJO: si "user" es None (el correo no existe), NO se muestra ningún
        # error distinto — cae directo al messages.success() de abajo con el
        # mismo mensaje genérico. Es deliberado: así nadie puede usar este
        # formulario para "probar" qué correos están registrados en el sistema.
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


# === MI PERFIL (autoedición + cambio de contraseña con código por correo) ===
# El código de verificación NO se guarda en la base de datos: vive en
# request.session (con expiración), que es propia de cada usuario logueado.
# Es un mecanismo simple de un solo uso, suficiente para este flujo de dos
# pasos sin necesitar un modelo nuevo.
PASSWORD_CODE_SESSION_KEY = 'pwd_change_code'
PASSWORD_CODE_EXPIRES_KEY = 'pwd_change_expires'
PASSWORD_CODE_TTL_SECONDS = 600  # 10 minutos


class ProfileView(LoginRequiredMixin, UpdateView):
    """
    'Mi Perfil': cada usuario edita SUS PROPIOS datos (nombre, correo,
    teléfono). get_object() siempre devuelve request.user, sin leer ningún
    pk de la URL — así es imposible que un usuario edite el perfil de otro
    cambiando un número en la dirección.
    """
    model = User
    form_class = ProfileForm
    template_name = 'security/profile.html'
    success_url = reverse_lazy('security:profile')

    def get_object(self, queryset=None):
        return self.request.user

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['pending_code'] = bool(self.request.session.get(PASSWORD_CODE_SESSION_KEY))
        context['password_form'] = PasswordChangeCodeForm()
        return context

    def form_valid(self, form):
        messages.success(self.request, 'Tus datos se actualizaron correctamente.')
        return super().form_valid(form)


@login_required
def password_change_request(request):
    """Paso 1: genera un código de 6 dígitos, lo guarda en la sesión (con
    vencimiento) y lo envía al correo del propio usuario logueado."""
    if request.method != 'POST':
        return redirect('security:profile')

    code = ''.join(secrets.choice('0123456789') for _ in range(6))
    request.session[PASSWORD_CODE_SESSION_KEY] = code
    request.session[PASSWORD_CODE_EXPIRES_KEY] = (
        timezone.now() + timezone.timedelta(seconds=PASSWORD_CODE_TTL_SECONDS)
    ).isoformat()

    body = (
        f'Estimado/a {_full_name(request.user)},\n\n'
        f'Recibimos una solicitud para cambiar tu contraseña en el Sistema de Ventas TecnoStock.\n\n'
        f'Tu código de verificación es: {code}\n\n'
        f'Este código vence en 10 minutos. Ingrésalo junto con tu nueva contraseña en "Mi Perfil".\n\n'
        f'Si tú no solicitaste este cambio, ignora este mensaje: tu contraseña actual sigue funcionando.\n\n'
        f'Atentamente,\n'
        f'Administración — Sistema de Ventas TecnoStock'
    )
    sent = send_credentials_email(request.user.email, 'Código de verificación — Cambio de contraseña', body)
    if sent:
        messages.success(request, f'Te enviamos un código de verificación a {request.user.email}.')
    else:
        messages.error(request, 'No se pudo enviar el código. Intenta de nuevo más tarde.')
    return redirect('security:profile')


@login_required
def password_change_confirm(request):
    """Paso 2: valida el código + la nueva contraseña, y si todo está bien, la aplica."""
    if request.method != 'POST':
        return redirect('security:profile')

    stored_code = request.session.get(PASSWORD_CODE_SESSION_KEY)
    expires_raw = request.session.get(PASSWORD_CODE_EXPIRES_KEY)

    if not stored_code or not expires_raw:
        messages.error(request, 'No hay un código pendiente. Solicita uno nuevo.')
        return redirect('security:profile')

    if timezone.now() > datetime.fromisoformat(expires_raw):
        del request.session[PASSWORD_CODE_SESSION_KEY]
        del request.session[PASSWORD_CODE_EXPIRES_KEY]
        messages.error(request, 'El código venció. Solicita uno nuevo.')
        return redirect('security:profile')

    form = PasswordChangeCodeForm(request.POST)
    if not form.is_valid():
        for errors in form.errors.values():
            for error in errors:
                messages.error(request, error)
        return redirect('security:profile')

    if form.cleaned_data['code'] != stored_code:
        messages.error(request, 'El código ingresado es incorrecto.')
        return redirect('security:profile')

    # validate_password corre los mismos AUTH_PASSWORD_VALIDATORS que se
    # usan al registrar un usuario (largo mínimo, no común, no numérica, etc.)
    try:
        validate_password(form.cleaned_data['new_password1'], user=request.user)
    except DjangoValidationError as e:
        for error in e.messages:
            messages.error(request, error)
        return redirect('security:profile')

    request.user.set_password(form.cleaned_data['new_password1'])
    request.user.save()
    # Cambiar la contraseña invalida la sesión actual por defecto (por
    # seguridad, Django cierra sesión en todos lados). update_session_auth_hash
    # evita eso para la sesión ACTUAL, para que el usuario no se quede
    # deslogueado justo después de cambiar su propia contraseña.
    update_session_auth_hash(request, request.user)

    del request.session[PASSWORD_CODE_SESSION_KEY]
    del request.session[PASSWORD_CODE_EXPIRES_KEY]

    messages.success(request, 'Tu contraseña se actualizó correctamente.')
    return redirect('security:profile')


# === USUARIOS ===
# CRUD del modelo User de Django. Sigue el mismo patrón de "listado con
# filtros + paginación + exportar" que ya usan brand_list/product_list/etc.
# en billing/views.py — si entendiste uno, entendiste todos.
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
        'page_range': get_page_range(page_obj),
        'extra_qs': build_extra_qs(request),
        'query': query,
        'is_active': is_active,
        'selected_group': group_id,
        'groups': Group.objects.all(),
    }
    return render(request, 'security/user_list.html', context)


class UserDetailView(AdminOnlyMixin, DetailView):
    # context_object_name='viewed_user' (en vez del 'user' por defecto de
    # DetailView) porque 'user' ya está reservado en los templates para "el
    # usuario que tiene la sesión abierta" (lo inyecta el context processor
    # de auth). Si no lo renombramos, pisaría al usuario logueado en la navbar.
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

        # A diferencia de RegisterView, acá NO hay contraseña que avisar
        # (editar un usuario no cambia su contraseña) — solo se notifica que
        # su cuenta fue modificada, con sus datos actuales.
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
# Un "Rol" en la interfaz ES el modelo Group de django.contrib.auth — no se
# creó ningún modelo nuevo para esto, se reutiliza el que ya trae Django.
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
        'page_range': get_page_range(page_obj),
        'extra_qs': build_extra_qs(request),
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


class GroupDetailView(AdminOnlyMixin, DetailView):
    model = Group
    template_name = 'security/group_detail.html'
    context_object_name = 'role'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        role = self.object
        context['role_permissions'] = [
            {
                'name': translate_permission_name(p.name),
                'model': MODEL_TRANSLATIONS.get(p.content_type.model.lower(), p.content_type.model),
            }
            for p in role.permissions.select_related('content_type').order_by('content_type__model', 'codename')
        ]
        context['role_users'] = role.user_set.all().order_by('username')
        return context


# Django genera los permisos/nombres de modelo en inglés (ej. "Can add product").
# Este diccionario + translate_permission_name() traducen esos textos para
# que la pantalla de permisos se vea en español, sin tocar el dato real en
# la base (el codename 'add_product' no cambia, solo cómo se muestra).
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


# Django crea 4 permisos por cada modelo automáticamente: add_x, change_x,
# delete_x, view_x. Estos diccionarios traducen ese prefijo a la etiqueta e
# ícono que se muestra en cada casilla de la pantalla de permisos.
ACTION_LABELS = {'view': 'Ver', 'add': 'Agregar', 'change': 'Editar', 'delete': 'Eliminar'}
ACTION_ICONS = {'view': 'bi-eye', 'add': 'bi-plus-circle', 'change': 'bi-pencil', 'delete': 'bi-trash'}
ACTION_ORDER = ['view', 'add', 'change', 'delete']  # orden en que aparecen las casillas


def _permission_action(codename):
    """De 'add_product' extrae 'add'. Si el codename es uno personalizado
    (no sigue el patrón add_/change_/delete_/view_), devuelve None."""
    prefix = codename.split('_', 1)[0]
    return prefix if prefix in ACTION_LABELS else None


# === PERMISOS ===
# Esta es LA vista clave de todo el sistema de seguridad: la pantalla donde
# el administrador ve y marca qué puede hacer cada rol/usuario. Todo lo que
# se marca/desmarca acá se refleja de inmediato en el resto del sistema,
# porque las vistas de negocio (billing/purchasing) usan has_perm() —
# ver shared/mixins.py -> PermissionRequiredRedirectMixin.
#
# La misma función atiende 3 cosas distintas según cómo llegue el request:
#   1) GET normal              -> muestra el panel (roles/usuarios a la
#                                  izquierda, cuadros por modelo a la derecha)
#   2) POST con grant_all_user_id -> botón rápido "dar todos los permisos"
#   3) POST con target_type/target_id/perm_ids -> guardar lo marcado
@admin_required
def permission_list(request):
    groups = Group.objects.all().order_by('name')
    all_users = User.objects.filter(is_active=True).order_by('username')

    # --- Caso 2: acción rápida "otorgar TODOS los permisos a un usuario" ---
    # Solo aplica a usuarios (no a roles) y se usa cuando el filtro de la
    # izquierda deja exactamente un usuario visible (ver template).
    if request.method == 'POST' and request.POST.get('grant_all_user_id'):
        try:
            target_user = User.objects.get(id=request.POST['grant_all_user_id'])
            target_user.user_permissions.set(Permission.objects.all())
            messages.success(request, f'Se otorgaron todos los permisos a "{target_user.username}".')
        except User.DoesNotExist:
            messages.error(request, 'Usuario no encontrado.')
        return redirect(request.get_full_path())

    # --- Caso 3: guardar los permisos marcados para el rol/usuario seleccionado ---
    # El formulario manda TODAS las casillas marcadas de una sola vez
    # (perm_ids es una lista, una entrada por checkbox tildado). .set() hace
    # el trabajo completo: agrega las que faltan y quita las que ya no están
    # marcadas, en una sola llamada — no hay que calcular el "diff" a mano.
    if request.method == 'POST' and request.POST.get('target_type'):
        target_type = request.POST.get('target_type')
        target_id = request.POST.get('target_id')
        submitted_ids = [int(pid) for pid in request.POST.getlist('perm_ids')]

        if target_type == 'group':
            target_obj = get_object_or_404(Group, id=target_id)
            target_obj.permissions.set(submitted_ids)
            messages.success(request, f'Permisos actualizados para el rol "{target_obj.name}".')
        else:
            # Ojo: esto solo toca target_obj.user_permissions (los permisos
            # DIRECTOS del usuario). Los permisos que tiene por su rol viven
            # en el Group y no se tocan desde acá — por eso en el template
            # esas casillas aparecen bloqueadas (disabled) y nunca se
            # incluyen en perm_ids.
            target_obj = get_object_or_404(User, id=target_id)
            target_obj.user_permissions.set(submitted_ids)
            messages.success(request, f'Permisos actualizados para el usuario "{target_obj.username}".')

        return redirect(f"{reverse('security:permission_list')}?target_type={target_type}&target_id={target_id}")

    # --- A partir de acá: armar la pantalla para un GET normal ---
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

    # assigned_ids = qué casillas se muestran marcadas.
    # locked_ids = cuáles de esas están bloqueadas (vienen de un rol, no se
    # pueden editar directamente desde la vista de "usuario").
    assigned_ids = set()
    locked_ids = set()
    if target is not None:
        if target_type == 'group':
            assigned_ids = set(target.permissions.values_list('id', flat=True))
        else:
            # Un usuario ya tiene activos los permisos de su(s) rol(es), aunque no
            # estén asignados directamente a él — se muestran marcados y bloqueados
            # para que el panel refleje lo que el usuario realmente puede hacer.
            locked_ids = set(
                Permission.objects.filter(group__in=target.groups.all()).values_list('id', flat=True)
            )
            direct_ids = set(target.user_permissions.values_list('id', flat=True))
            assigned_ids = locked_ids | direct_ids

    # Armar los cuadros por modelo, cada uno con sus casillas Ver/Agregar/Editar/Eliminar.
    # content_type identifica a qué modelo pertenece cada Permission (ej.
    # "billing" + "product"), así que agrupamos por esa pareja (app_label, model)
    # para que Product y Purchase no terminen mezclados en el mismo cuadro.
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
            'locked': p.id in locked_ids,
        })
    # Dentro de cada cuadro, siempre en el orden Ver/Agregar/Editar/Eliminar
    # (y al final, cualquier permiso personalizado que no siga ese patrón).
    for card in model_cards.values():
        card['items'].sort(key=lambda i: i['order'])
    # Los cuadros en sí, ordenados alfabéticamente por su nombre traducido.
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


class PermissionDetailView(AdminOnlyMixin, DetailView):
    model = Permission
    template_name = 'security/permission_detail.html'
    context_object_name = 'permission'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        perm = self.object
        context['translated_name'] = translate_permission_name(perm.name)
        context['translated_model'] = MODEL_TRANSLATIONS.get(
            perm.content_type.model.lower(), perm.content_type.model
        )
        context['assigned_groups'] = perm.group_set.all().order_by('name')
        return context


# Pantalla de inicio de la app security (conteos generales + últimos usuarios).
# No confundir con home/views.py -> home(), que es el dashboard principal del
# sistema completo (facturas, stock, etc.) al que llega cualquier usuario logueado.
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