import re

from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User, Group, Permission

from .models import UserProfile

PHONE_RE = re.compile(r'^\+?\d{7,15}$')

class UserRegisterForm(UserCreationForm):
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
        # Solo el campo con el error debe quedar vacío al reenviar el formulario;
        # sin esto, Django borra password1/password2 aunque el error esté en otro campo.
        self.fields['password1'].widget = forms.PasswordInput(
            attrs={'class': 'form-control', 'autocomplete': 'new-password'}, render_value=True
        )
        self.fields['password2'].widget = forms.PasswordInput(
            attrs={'class': 'form-control', 'autocomplete': 'new-password'}, render_value=True
        )

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
        user = super().save(commit)
        if commit:
            user.groups.add(self.cleaned_data['role'])
            UserProfile.objects.create(user=user, phone=self.cleaned_data['phone'])
        return user

class UserUpdateForm(forms.ModelForm):
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
        if self.instance.pk:
            profile = getattr(self.instance, 'profile', None)
            if profile:
                self.fields['phone'].initial = profile.phone

    def save(self, commit=True):
        user = super().save(commit)
        if commit:
            UserProfile.objects.update_or_create(
                user=user, defaults={'phone': self.cleaned_data['phone']}
            )
        return user

class RecoverCredentialsForm(forms.Form):
    CHANNEL_CHOICES = [
        ('email', 'Correo electrónico'),
        ('whatsapp', 'WhatsApp'),
    ]
    email = forms.EmailField(label='Correo electrónico', widget=forms.EmailInput(attrs={'class': 'form-control-custom'}))
    channel = forms.ChoiceField(label='Enviar por', choices=CHANNEL_CHOICES, widget=forms.RadioSelect)

class GroupForm(forms.ModelForm):
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
    class Meta:
        model = Permission
        fields = ['name', 'codename', 'content_type']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'codename': forms.TextInput(attrs={'class': 'form-control'}),
            'content_type': forms.Select(attrs={'class': 'form-select'}),
        }