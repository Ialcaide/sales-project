from django import forms

from .models import ConfiguracionSistema


class ConfiguracionSistemaForm(forms.ModelForm):
    class Meta:
        model = ConfiguracionSistema
        fields = [
            'empresa_nombre', 'empresa_ruc', 'empresa_direccion', 'empresa_telefono',
            'iva_porcentaje', 'moneda_simbolo',
            'stock_minimo_default', 'credito_porcentaje_por_compras',
            'dias_aviso_vencimiento_producto', 'dias_aviso_pago_compra', 'dias_credito_factura_default',
            'sri_establecimiento', 'sri_punto_emision', 'sri_obligado_contabilidad', 'sri_nombre_comercial',
        ]
        widgets = {
            'empresa_nombre': forms.TextInput(attrs={'class': 'form-control'}),
            'empresa_ruc': forms.TextInput(attrs={'class': 'form-control'}),
            'empresa_direccion': forms.TextInput(attrs={'class': 'form-control'}),
            'empresa_telefono': forms.TextInput(attrs={'class': 'form-control'}),
            'iva_porcentaje': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'min': 0}),
            'moneda_simbolo': forms.TextInput(attrs={'class': 'form-control'}),
            'stock_minimo_default': forms.NumberInput(attrs={'class': 'form-control', 'min': 0}),
            'credito_porcentaje_por_compras': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'min': 0}),
            'dias_aviso_vencimiento_producto': forms.NumberInput(attrs={'class': 'form-control', 'min': 0}),
            'dias_aviso_pago_compra': forms.NumberInput(attrs={'class': 'form-control', 'min': 0}),
            'dias_credito_factura_default': forms.NumberInput(attrs={'class': 'form-control', 'min': 0}),
            'sri_establecimiento': forms.TextInput(attrs={'class': 'form-control', 'maxlength': 3, 'placeholder': '001'}),
            'sri_punto_emision': forms.TextInput(attrs={'class': 'form-control', 'maxlength': 3, 'placeholder': '001'}),
            'sri_obligado_contabilidad': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'sri_nombre_comercial': forms.TextInput(attrs={'class': 'form-control'}),
        }
