import re

from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User, Group, Permission

from .models import UserProfile

# Acepta un + opcional seguido de 7 a 15 dígitos (formato internacional simple).
PHONE_RE = re.compile(r'^\+?\d{7,15}$')


class UserRegisterForm(UserCreationForm):
    """
    Formulario que usa el administrador para dar de alta un usuario nuevo
    (security/views.py -> RegisterView). Extiende UserCreationForm (ya trae
    username/password1/password2 con la validación de contraseña de Django)
    y le agrega correo, teléfono y el rol (Group) que se le va a asignar.
    """
    email = forms.EmailField(required=True)
    phone = forms.CharField(required=True, label='Teléfono / WhatsApp')
    role = forms.ModelChoiceField(
        queryset=Group.objects.all(),
        required=True,
        label='Role',
        empty_label='-- Select a role --',
    )

    class Meta:
        model = User
        fields = ['username', 'first_name', 'last_name', 'email',
                  'password1', 'password2', 'phone', 'role']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for f in self.fields:
            self.fields[f].widget.attrs['class'] = 'form-control'
        # Por defecto Django SIEMPRE vacía los campos de contraseña al
        # reenviar un formulario con errores, sin importar en qué campo esté
        # el error real (ej. si falla el teléfono, igual borra las
        # contraseñas y el admin tiene que volver a escribirlas). Con
        # render_value=True se conserva lo que el admin ya escribió, y solo
        # queda vacío el campo que de verdad tiene el error.
        self.fields['password1'].widget = forms.PasswordInput(
            attrs={'class': 'form-control', 'autocomplete': 'new-password'}, render_value=True
        )
        self.fields['password2'].widget = forms.PasswordInput(
            attrs={'class': 'form-control', 'autocomplete': 'new-password'}, render_value=True
        )

    # Cada método clean_<campo> valida UN campo específico. Django los llama
    # automáticamente durante form.is_valid(), y el error queda ligado a ese
    # campo (se muestra justo debajo de él en el template, no en el formulario
    # entero) — así el usuario sabe exactamente qué corregir.

    def clean_first_name(self):
        first_name = self.cleaned_data.get('first_name', '').strip()
        if not first_name:
            raise forms.ValidationError('El nombre es obligatorio.')
        return first_name

    def clean_last_name(self):
        last_name = self.cleaned_data.get('last_name', '').strip()
        if not last_name:
            raise forms.ValidationError('El apellido es obligatorio.')
        return last_name

    def clean_email(self):
        email = self.cleaned_data.get('email', '').strip().lower()
        # User.email no es único a nivel de base de datos (Django no lo obliga
        # por defecto), así que hay que revisarlo a mano aquí.
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError('Ya existe un usuario registrado con este correo electrónico.')
        return email

    def clean_phone(self):
        phone = self.cleaned_data.get('phone', '').strip()
        if not PHONE_RE.match(phone):
            raise forms.ValidationError(
                'Ingresa un número de teléfono válido (solo dígitos, con o sin "+" al inicio, entre 7 y 15 dígitos).'
            )
        if UserProfile.objects.filter(phone=phone).exists():
            raise forms.ValidationError('Ya existe un usuario registrado con este número de teléfono.')
        return phone

    def save(self, commit=True):
        # UserCreationForm.save() ya crea el User con la contraseña encriptada.
        # Acá solo falta lo que NO es parte del modelo User: agregarlo al
        # grupo/rol elegido, y crear su UserProfile con el teléfono.
        user = super().save(commit)
        if commit:
            user.groups.add(self.cleaned_data['role'])
            UserProfile.objects.create(user=user, phone=self.cleaned_data['phone'])
        return user


class UserUpdateForm(forms.ModelForm):
    """Formulario para editar un usuario existente (username, datos, roles y teléfono)."""
    phone = forms.CharField(required=True, label='Teléfono / WhatsApp')
    groups = forms.ModelMultipleChoiceField(
        queryset=Group.objects.all(),
        required=False,
        widget=forms.CheckboxSelectMultiple,
        label='Roles',
    )

    class Meta:
        model = User
        fields = ['username', 'first_name', 'last_name', 'email',
                  'is_active', 'phone', 'groups']
        widgets = {
            'username': forms.TextInput(attrs={'class': 'form-control'}),
            'first_name': forms.TextInput(attrs={'class': 'form-control'}),
            'last_name': forms.TextInput(attrs={'class': 'form-control'}),
            'email': forms.EmailInput(attrs={'class': 'form-control'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # 'phone' no es un campo real del modelo User (vive en UserProfile,
        # un modelo aparte), así que hay que precargar su valor inicial a mano.
        # getattr(..., None) es necesario porque usuarios creados antes de
        # este campo pueden no tener UserProfile todavía.
        if self.instance.pk:
            profile = getattr(self.instance, 'profile', None)
            if profile:
                self.fields['phone'].initial = profile.phone

    def save(self, commit=True):
        user = super().save(commit)
        if commit:
            # update_or_create: si ya tenía perfil lo actualiza, si no, lo crea.
            UserProfile.objects.update_or_create(
                user=user, defaults={'phone': self.cleaned_data['phone']}
            )
        return user


class ProfileForm(forms.ModelForm):
    """
    Formulario de autoedición: cada usuario edita SUS PROPIOS datos (nombre,
    apellido, correo, teléfono). A diferencia de UserUpdateForm (que usa el
    administrador para editar a otros), acá NO hay campos de roles ni de
    is_active — un usuario no puede cambiarse su propio rol ni activarse/
    desactivarse a sí mismo.
    """
    phone = forms.CharField(required=True, label='Teléfono / WhatsApp')

    class Meta:
        model = User
        fields = ['first_name', 'last_name', 'email']
        widgets = {
            'first_name': forms.TextInput(attrs={'class': 'form-control'}),
            'last_name': forms.TextInput(attrs={'class': 'form-control'}),
            'email': forms.EmailInput(attrs={'class': 'form-control'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            profile = getattr(self.instance, 'profile', None)
            if profile:
                self.fields['phone'].initial = profile.phone

    def clean_email(self):
        email = self.cleaned_data.get('email', '').strip().lower()
        # exclude=self.instance.pk: si no excluyera al propio usuario, el
        # formulario rechazaría guardar sin cambiar nada (su correo actual
        # "ya está en uso"... ¡por él mismo!).
        if User.objects.filter(email__iexact=email).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError('Ya existe un usuario registrado con este correo electrónico.')
        return email

    def clean_phone(self):
        phone = self.cleaned_data.get('phone', '').strip()
        if not PHONE_RE.match(phone):
            raise forms.ValidationError(
                'Ingresa un número de teléfono válido (solo dígitos, con o sin "+" al inicio, entre 7 y 15 dígitos).'
            )
        if UserProfile.objects.filter(phone=phone).exclude(user=self.instance).exists():
            raise forms.ValidationError('Ya existe un usuario registrado con este número de teléfono.')
        return phone

    def save(self, commit=True):
        user = super().save(commit)
        if commit:
            UserProfile.objects.update_or_create(
                user=user, defaults={'phone': self.cleaned_data['phone']}
            )
        return user


class PasswordChangeCodeForm(forms.Form):
    """
    Segundo paso del cambio de contraseña: el usuario ya pidió el código
    (se le mandó por correo) y acá lo confirma junto con la nueva contraseña.
    No es un ModelForm porque no edita el modelo User directamente — eso lo
    hace la vista, una vez validado el código (ver security/views.py).
    """
    code = forms.CharField(
        label='Código de verificación', max_length=6,
        widget=forms.TextInput(attrs={'class': 'form-control', 'autocomplete': 'one-time-code', 'placeholder': '000000'}),
    )
    new_password1 = forms.CharField(label='Nueva contraseña', widget=forms.PasswordInput(attrs={'class': 'form-control'}))
    new_password2 = forms.CharField(label='Confirmar nueva contraseña', widget=forms.PasswordInput(attrs={'class': 'form-control'}))

    def clean(self):
        cleaned_data = super().clean()
        p1 = cleaned_data.get('new_password1')
        p2 = cleaned_data.get('new_password2')
        if p1 and p2 and p1 != p2:
            raise forms.ValidationError('Las dos contraseñas no coinciden.')
        return cleaned_data


class RecoverCredentialsForm(forms.Form):
    """
    Formulario de '¿Olvidaste tu contraseña?' (security/views.py -> RecoverCredentialsView).
    No es un ModelForm porque no crea ni edita nada directamente: solo pide el
    correo del usuario y por qué canal quiere recibir el link de recuperación.
    """
    CHANNEL_CHOICES = [
        ('email', 'Correo electrónico'),
        ('whatsapp', 'WhatsApp'),
    ]
    email = forms.EmailField(label='Correo electrónico', widget=forms.EmailInput(attrs={'class': 'form-control-custom'}))
    channel = forms.ChoiceField(label='Enviar por', choices=CHANNEL_CHOICES, widget=forms.RadioSelect)


class GroupForm(forms.ModelForm):
    """Crear/editar un Rol (Group de Django) y elegir sus permisos manualmente."""
    permissions = forms.ModelMultipleChoiceField(
        queryset=Permission.objects.select_related('content_type'),
        required=False,
        widget=forms.CheckboxSelectMultiple,
        label='Permissions',
    )

    class Meta:
        model = Group
        fields = ['name', 'permissions']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'}),
        }


class PermissionForm(forms.ModelForm):
    """
    Crea/edita la DEFINICIÓN de un permiso (name, codename, content_type).
    Distinto de "asignar" un permiso a un rol/usuario — eso se hace desde
    la vista permission_list, no desde este formulario.
    """
    class Meta:
        model = Permission
        fields = ['name', 'codename', 'content_type']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'codename': forms.TextInput(attrs={'class': 'form-control'}),
            'content_type': forms.Select(attrs={'class': 'form-select'}),
        }
