from django import forms
from django.core.exceptions import ValidationError

from .models import MovimientoCaja, SesionCaja


class SesionCajaAbrirForm(forms.ModelForm):
    class Meta:
        model = SesionCaja
        fields = ['monto_inicial']
        widgets = {
            'monto_inicial': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'min': '0'}),
        }

    def clean_monto_inicial(self):
        monto = self.cleaned_data.get('monto_inicial')
        if monto is not None and monto < 0:
            raise ValidationError('El monto inicial no puede ser negativo.')
        return monto


class SesionCajaCerrarForm(forms.ModelForm):
    class Meta:
        model = SesionCaja
        fields = ['monto_contado_cierre']
        widgets = {
            'monto_contado_cierre': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'min': '0'}),
        }

    def clean_monto_contado_cierre(self):
        monto = self.cleaned_data.get('monto_contado_cierre')
        if monto is None:
            raise ValidationError('Debes indicar cuánto contaste físicamente para poder cerrar la caja.')
        if monto < 0:
            raise ValidationError('El monto contado no puede ser negativo.')
        return monto


class MovimientoCajaForm(forms.ModelForm):
    class Meta:
        model = MovimientoCaja
        fields = ['tipo', 'monto', 'concepto']
        widgets = {
            'tipo': forms.Select(attrs={'class': 'form-select'}),
            'monto': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'min': '0.01'}),
            'concepto': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ej: Retiro para depósito, pago de gasto menor...'}),
        }

    def clean_monto(self):
        monto = self.cleaned_data.get('monto')
        if monto is not None and monto <= 0:
            raise ValidationError('El monto debe ser mayor a 0.')
        return monto
