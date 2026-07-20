from django import forms

from .models import ConfiguracionSistema


class ConfiguracionSistemaForm(forms.ModelForm):
    class Meta:
        model = ConfiguracionSistema
        fields = [
            'empresa_nombre', 'empresa_ruc', 'empresa_direccion', 'empresa_telefono',
            'iva_porcentaje', 'moneda_simbolo',
            'stock_minimo_default', 'credito_porcentaje_por_compras', 'retencion_porcentaje_default',
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
            'retencion_porcentaje_default': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'min': 0}),
            'dias_aviso_vencimiento_producto': forms.NumberInput(attrs={'class': 'form-control', 'min': 0}),
            'dias_aviso_pago_compra': forms.NumberInput(attrs={'class': 'form-control', 'min': 0}),
            'dias_credito_factura_default': forms.NumberInput(attrs={'class': 'form-control', 'min': 0}),
            'sri_establecimiento': forms.TextInput(attrs={'class': 'form-control', 'maxlength': 3, 'placeholder': '001'}),
            'sri_punto_emision': forms.TextInput(attrs={'class': 'form-control', 'maxlength': 3, 'placeholder': '001'}),
            'sri_obligado_contabilidad': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'sri_nombre_comercial': forms.TextInput(attrs={'class': 'form-control'}),
        }


class ConectarFacturacionElectronicaForm(forms.Form):
    """Formulario que da de alta una empresa NUEVA en el microservicio de
    facturación electrónica (ver configuracion/views.py ->
    conectar_facturacion_electronica) y la agrega a la lista de empresas
    conectadas, activándola. No es un ModelForm: certificado_p12 y
    certificado_password nunca se guardan, solo se reenvían al microservicio
    y se descartan al terminar el request."""

    ruc = forms.CharField(max_length=13, label='RUC', widget=forms.TextInput(attrs={'class': 'form-control'}))
    razon_social = forms.CharField(
        max_length=200, label='Razón social', widget=forms.TextInput(attrs={'class': 'form-control'}),
    )
    direccion_matriz = forms.CharField(
        max_length=255, label='Dirección matriz', widget=forms.TextInput(attrs={'class': 'form-control'}),
    )
    establecimiento = forms.CharField(
        max_length=3, label='Código de establecimiento',
        widget=forms.TextInput(attrs={'class': 'form-control', 'maxlength': 3, 'placeholder': '001'}),
    )
    punto_emision = forms.CharField(
        max_length=3, label='Código de punto de emisión',
        widget=forms.TextInput(attrs={'class': 'form-control', 'maxlength': 3, 'placeholder': '001'}),
    )
    ambiente = forms.ChoiceField(
        choices=ConfiguracionSistema.AMBIENTE_CHOICES, label='Ambiente',
        widget=forms.Select(attrs={'class': 'form-select'}),
    )
    certificado_p12 = forms.FileField(
        label='Certificado (.p12)', widget=forms.ClearableFileInput(attrs={'class': 'form-control'}),
    )
    certificado_password = forms.CharField(
        label='Contraseña del certificado',
        widget=forms.PasswordInput(attrs={'class': 'form-control', 'autocomplete': 'off'}, render_value=False),
    )


class EditarEmpresaActivaForm(forms.Form):
    """Modal 'Editar datos' de la empresa ACTIVA (ver configuracion/views.py
    -> editar_empresa_activa). El RUC NO es un campo de este form a
    propósito: se muestra deshabilitado en el template, nunca se manda en
    el PATCH — cambiar de RUC es dar de alta OTRA empresa, no editar esta.
    certificado_p12/certificado_password son opcionales y NUNCA vienen
    pre-cargados (ver configuracion/views.py): solo se usan si el admin
    decide renovar el certificado en el mismo modal, y se descartan
    apenas se reenvían al microservicio, igual que en
    ConectarFacturacionElectronicaForm."""

    razon_social = forms.CharField(
        max_length=200, label='Razón social', widget=forms.TextInput(attrs={'class': 'form-control'}),
    )
    direccion_matriz = forms.CharField(
        max_length=255, label='Dirección matriz', widget=forms.TextInput(attrs={'class': 'form-control'}),
    )
    establecimiento = forms.CharField(
        max_length=3, label='Código de establecimiento',
        widget=forms.TextInput(attrs={'class': 'form-control', 'maxlength': 3, 'placeholder': '001'}),
    )
    punto_emision = forms.CharField(
        max_length=3, label='Código de punto de emisión',
        widget=forms.TextInput(attrs={'class': 'form-control', 'maxlength': 3, 'placeholder': '001'}),
    )
    ambiente = forms.ChoiceField(
        choices=ConfiguracionSistema.AMBIENTE_CHOICES, label='Ambiente',
        widget=forms.Select(attrs={'class': 'form-select'}),
    )
    certificado_p12 = forms.FileField(
        label='Certificado (.p12)', required=False,
        widget=forms.ClearableFileInput(attrs={'class': 'form-control'}),
    )
    certificado_password = forms.CharField(
        label='Contraseña del certificado', required=False,
        widget=forms.PasswordInput(attrs={'class': 'form-control', 'autocomplete': 'off'}, render_value=False),
    )

    def clean(self):
        cleaned = super().clean()
        archivo = cleaned.get('certificado_p12')
        password = cleaned.get('certificado_password')
        if bool(archivo) != bool(password):
            raise forms.ValidationError(
                'Para renovar el certificado hacen falta el archivo .p12 Y su contraseña, los dos juntos.'
            )
        return cleaned


class VincularEmpresaExistenteForm(forms.Form):
    """Para una empresa que YA existe del lado del microservicio (ej.
    creada por script, fuera de esta pantalla) — solo pide su api_key y trae
    el resto de los datos con GET /empresas/me (ver configuracion/views.py ->
    vincular_empresa_existente), sin volver a darla de alta."""

    api_key = forms.CharField(
        label='API key de la empresa', widget=forms.PasswordInput(
            attrs={'class': 'form-control', 'autocomplete': 'off'}, render_value=False,
        ),
    )
