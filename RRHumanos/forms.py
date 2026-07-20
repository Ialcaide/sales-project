from django import forms
from decimal import Decimal
from datetime import date
from django.core.exceptions import ValidationError
from .models import Prestamo, Empleado, TipoPrestamo

class EmpleadoForm(forms.ModelForm):
    class Meta:
        model = Empleado
        fields = ['user', 'nombres', 'sueldo', 'fecha_ingreso', 'fecha_fin_contrato', 'porcentaje_credito']
        widgets = {
            'user': forms.Select(attrs={'class': 'form-select'}),
            'nombres': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Nombres completos'}),
            'sueldo': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'placeholder': 'Sueldo mensual'}),
            'fecha_ingreso': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'fecha_fin_contrato': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'porcentaje_credito': forms.NumberInput(attrs={'class': 'form-control', 'min': 0, 'placeholder': 'Porcentaje de crédito'}),
        }
        labels = {
            'user': 'Usuario del Sistema',
            'nombres': 'Nombres Completos',
            'sueldo': 'Sueldo Mensual ($)',
            'fecha_ingreso': 'Fecha de Ingreso',
            'fecha_fin_contrato': 'Fecha de Fin de Contrato',
            'porcentaje_credito': 'Porcentaje de Crédito (%)',
        }

    def clean_sueldo(self):
        sueldo = self.cleaned_data.get('sueldo')
        if sueldo is not None and sueldo <= 0:
            raise ValidationError('El sueldo mensual debe ser mayor a 0.')
        return sueldo


class PrestamoForm(forms.ModelForm):
    class Meta:
        model = Prestamo
        fields = ['empleado', 'tipo_prestamo', 'fecha_prestamo', 'monto', 'numero_cuotas']
        widgets = {
            'empleado': forms.Select(attrs={'class': 'form-select'}),
            'tipo_prestamo': forms.Select(attrs={'class': 'form-select'}),
            'fecha_prestamo': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'monto': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'placeholder': 'Ej: 500.00'}),
            'numero_cuotas': forms.NumberInput(attrs={'class': 'form-control', 'min': 1, 'max': 60, 'placeholder': 'Ej: 12'}),
        }
        labels = {
            'empleado': 'Empleado',
            'tipo_prestamo': 'Tipo de Préstamo',
            'fecha_prestamo': 'Fecha del Préstamo',
            'monto': 'Monto Solicitado ($)',
            'numero_cuotas': 'Número de Cuotas',
        }
        error_messages = {
            'empleado': {
                'required': 'Debes seleccionar un empleado.',
            },
            'tipo_prestamo': {
                'required': 'Debes seleccionar el tipo de préstamo.',
            },
            'fecha_prestamo': {
                'required': 'La fecha del préstamo es requerida.',
            },
            'monto': {
                'required': 'El monto del préstamo es requerido.',
                'invalid': 'Ingresa un monto decimal válido.',
            },
            'numero_cuotas': {
                'required': 'El número de cuotas es requerido.',
                'invalid': 'Ingresa un número entero de cuotas.',
            },
        }

    def clean_monto(self):
        monto = self.cleaned_data.get('monto')
        if monto is not None and monto <= 0:
            raise ValidationError('El monto solicitado debe ser mayor a $0.00.')
        return monto

    def clean_numero_cuotas(self):
        cuotas = self.cleaned_data.get('numero_cuotas')
        if cuotas is not None:
            if cuotas < 1:
                raise ValidationError('El número de cuotas no puede ser menor a 1.')
            if cuotas > 60:
                raise ValidationError('El número de cuotas no puede superar las 60 cuotas.')
        return cuotas
