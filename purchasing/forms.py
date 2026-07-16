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
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['bodega'].queryset = self.fields['bodega'].queryset.filter(is_active=True)
        self.fields['bodega'].required = False
        self.fields['factura_adjunta'].required = False
        self.fields['retencion_porcentaje'].required = False
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


PurchaseDetailFormSet = inlineformset_factory(
    Purchase,
    PurchaseDetail,
    form=PurchaseDetailForm,
    extra=1,           # 1 fila vacía al abrir el formulario (el JS agrega más en vivo)
    can_delete=True,   # agrega la casilla "Eliminar" a cada fila
    validate_min=False,
    min_num=0,         # no exige un mínimo de filas acá (la vista valida "al menos 1 producto" a mano)
)