from datetime import date
from decimal import Decimal

from django import forms
from django.forms import inlineformset_factory
from .models import Bodega, Purchase, PurchaseDetail
from billing.models import Product


class BodegaQuickCreateForm(forms.ModelForm):
    """
    Alta rápida de bodega desde el modal del paso 1 del wizard de compra
    (ver static/js/purchase-wizard.js) — mismo patrón que
    CustomerQuickCreateForm/SupplierQuickCreateForm (billing/forms.py):
    responde JSON en vez de redirigir, para inyectar la bodega nueva en el
    <select> de purchase_form.html sin recargar la página. Es el ÚNICO lugar
    para crear bodegas hoy — Bodega no tiene un CRUD propio, y sin esto el
    <select> del wizard queda sin opciones hasta que alguien la cree desde
    /admin/.
    """
    class Meta:
        model = Bodega
        fields = ['nombre']
        widgets = {
            'nombre': forms.TextInput(attrs={'class': 'form-control'}),
        }


class PurchaseForm(forms.ModelForm):
    """Cabecera: proveedor, N° documento, tipo de pago y (si es crédito) a
    cuántos meses se difiere, más bodega/adjunto/retención. La fecha estimada
    de entrega YA NO se pide acá — es un cálculo automático (purchase_date +
    24h, ver Purchase.fecha_entrega_estimada) que se muestra como aviso, no
    como campo editable. Las líneas van en el formset de abajo. La
    validación cruzada tipo_pago/meses_credito vive en Purchase.clean()
    (models.py), que corre sola al llamar form.is_valid()."""
    class Meta:
        model = Purchase
        fields = [
            'supplier', 'document_number', 'tipo_pago', 'meses_credito',
            'bodega', 'factura_adjunta', 'retencion_porcentaje',
            'forma_pago', 'tarjeta_titular', 'tarjeta_cvv', 'tarjeta_expiracion',
        ]
        widgets = {
            'supplier': forms.Select(attrs={'class': 'form-select'}),
            'document_number': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ej: FAC-001'}),
            'tipo_pago': forms.Select(attrs={'class': 'form-select'}),
            'meses_credito': forms.NumberInput(attrs={
                'class': 'form-control', 'min': 1, 'max': Purchase.MESES_CREDITO_MAX,
                'placeholder': 'Ej: 3',
            }),
            'bodega': forms.Select(attrs={'class': 'form-select'}),
            'factura_adjunta': forms.ClearableFileInput(attrs={'class': 'form-control', 'accept': '.pdf,.xml,image/*'}),
            'retencion_porcentaje': forms.NumberInput(attrs={'class': 'form-control', 'min': '0', 'max': '100', 'step': '0.01'}),
            'forma_pago': forms.Select(attrs={'class': 'form-select'}),
            'tarjeta_titular': forms.TextInput(attrs={
                'class': 'form-control', 'placeholder': 'Nombre tal como aparece en la tarjeta',
            }),
            'tarjeta_cvv': forms.TextInput(attrs={
                'class': 'form-control', 'maxlength': 4, 'inputmode': 'numeric', 'placeholder': 'Ej: 123',
                'autocomplete': 'off',
            }),
            'tarjeta_expiracion': forms.DateInput(
                attrs={'class': 'form-control', 'type': 'date'}, format='%Y-%m-%d'
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['bodega'].queryset = self.fields['bodega'].queryset.filter(is_active=True)
        self.fields['bodega'].required = False
        self.fields['factura_adjunta'].required = False
        self.fields['retencion_porcentaje'].required = False
        # forma_pago es obligatorio solo para compras al CONTADO — eso se
        # exige en Purchase.clean() (modelo), no acá, mismo criterio que
        # billing.Invoice. Los 3 campos de tarjeta solo son obligatorios si
        # forma_pago='tarjeta' (se valida en clean() de abajo).
        self.fields['forma_pago'].required = False
        self.fields['tarjeta_titular'].required = False
        self.fields['tarjeta_cvv'].required = False
        self.fields['tarjeta_expiracion'].required = False
        # PayPal solo se ofrece como forma de pago si está configurado
        # (PAYPAL_CLIENT_ID/SECRET en el .env) — mismo criterio que
        # billing/forms.py -> InvoiceForm.__init__.
        from django.conf import settings
        if not (settings.PAYPAL_CLIENT_ID and settings.PAYPAL_CLIENT_SECRET):
            self.fields['forma_pago'].choices = [
                c for c in self.fields['forma_pago'].choices if c[0] != Purchase.PAYPAL
            ]
        # Solo sugiere el % configurado (ConfiguracionSistema) en compras
        # NUEVAS — al editar una existente se respeta el valor que ya tiene.
        if not self.instance.pk:
            from configuracion.models import ConfiguracionSistema
            self.fields['retencion_porcentaje'].initial = ConfiguracionSistema.get_solo().retencion_porcentaje_default

    def clean_retencion_porcentaje(self):
        # A diferencia de descuento_porcentaje (PurchaseDetailForm, abajo),
        # este campo lo genera un ModelForm automático sin min_value/
        # max_value propios — sin este clean, el widget solo lo limita en el
        # navegador (atributo HTML min/max, saltable con DevTools o un POST
        # directo), y un -5% o un 250% se guardarían tal cual.
        valor = self.cleaned_data.get('retencion_porcentaje')
        if valor is not None and not (Decimal('0') <= valor <= Decimal('100')):
            raise forms.ValidationError('La retención debe estar entre 0% y 100%.')
        return valor

    def clean(self):
        cleaned_data = super().clean()
        # Captura informativa de tarjeta — no hay pasarela de pago real (no
        # Stripe ni similar), así que estos 3 campos solo dejan constancia
        # de que se pagó por un datáfono externo. Nunca se pide/guarda el
        # número completo de la tarjeta. Mismo criterio que
        # billing/forms.py -> InvoiceForm.clean().
        if cleaned_data.get('forma_pago') == Purchase.TARJETA:
            titular = cleaned_data.get('tarjeta_titular')
            cvv = cleaned_data.get('tarjeta_cvv')
            expira = cleaned_data.get('tarjeta_expiracion')
            if not titular or not titular.strip():
                raise forms.ValidationError({'tarjeta_titular': 'Indica el nombre del titular de la tarjeta.'})
            if not cvv or not cvv.isdigit() or len(cvv) not in (3, 4):
                raise forms.ValidationError({
                    'tarjeta_cvv': 'Ingresa el CVV/CVC de la tarjeta (3 o 4 números).'
                })
            if not expira:
                raise forms.ValidationError({'tarjeta_expiracion': 'Indica la fecha de expiración de la tarjeta.'})
            elif expira < date.today():
                raise forms.ValidationError({'tarjeta_expiracion': 'La tarjeta está vencida.'})
        return cleaned_data


# product/quantity/unit_cost se declaran a mano (en vez de dejar que
# ModelForm los infiera solos) para poder poner required=False: así, si el
# usuario deja una fila del formset completamente vacía (no agregó ese
# producto), no truena con "este campo es obligatorio" — simplemente esa fila
# se ignora al guardar (ver purchasing/views.py, donde se filtran las filas
# sin producto antes de procesar).
class PurchaseDetailForm(forms.ModelForm):
    product = forms.ModelChoiceField(
        queryset=Product.objects.filter(is_active=True),
        required=False,
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    quantity = forms.IntegerField(
        required=False,
        min_value=1,
        widget=forms.NumberInput(attrs={'class': 'form-control', 'min': 1})
    )
    unit_cost = forms.DecimalField(
        required=False,
        min_value=0,
        widget=forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'})
    )
    descuento_porcentaje = forms.DecimalField(
        required=False,
        min_value=0,
        max_value=100,
        widget=forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'min': '0', 'max': '100'})
    )

    class Meta:
        model = PurchaseDetail
        fields = ['product', 'quantity', 'unit_cost', 'descuento_porcentaje']

    def has_changed(self):
        # Si no se seleccionó producto en el formulario enviado, asumimos que no ha cambiado
        # para que Django ignore esta fila vacía del formset al validar y guardar.
        if not self.data:
            return super().has_changed()
        if not self.data.get(self.add_prefix('product')):
            return False
        return super().has_changed()



PurchaseDetailFormSet = inlineformset_factory(
    Purchase,
    PurchaseDetail,
    form=PurchaseDetailForm,
    extra=1,           # 1 fila vacía al abrir el formulario (el JS agrega más en vivo)
    can_delete=True,   # agrega la casilla "Eliminar" a cada fila
    validate_min=False,
    min_num=0,         # no exige un mínimo de filas acá (la vista valida "al menos 1 producto" a mano)
)