from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User, Group, Permission

class UserRegisterForm(UserCreationForm):
    email = forms.EmailField(required=True)
    role = forms.ModelChoiceField(
        queryset=Group.objects.all(),
        required=True,
        label='Role',
        empty_label='-- Select a role --',
    )

    class Meta:
        model = User
        fields = ['username', 'first_name', 'last_name', 'email',
                  'password1', 'password2', 'role']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for f in self.fields:
            self.fields[f].widget.attrs['class'] = 'form-control'

    def save(self, commit=True):
        user = super().save(commit)
        if commit:
            user.groups.add(self.cleaned_data['role'])
        return user

class UserUpdateForm(forms.ModelForm):
    groups = forms.ModelMultipleChoiceField(
        queryset=Group.objects.all(),
        required=False,
        widget=forms.CheckboxSelectMultiple,
        label='Roles',
    )

    class Meta:
        model = User
        fields = ['username', 'first_name', 'last_name', 'email',
                  'is_active', 'groups']
        widgets = {
            'username': forms.TextInput(attrs={'class': 'form-control'}),
            'first_name': forms.TextInput(attrs={'class': 'form-control'}),
            'last_name': forms.TextInput(attrs={'class': 'form-control'}),
            'email': forms.EmailInput(attrs={'class': 'form-control'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }

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