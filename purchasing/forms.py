from django import forms
from django.forms import inlineformset_factory
from .models import Purchase, PurchaseDetail
from billing.models import Product


class PurchaseForm(forms.ModelForm):
    """Cabecera: solo proveedor y número de documento. Las líneas van en el formset de abajo."""
    class Meta:
        model = Purchase
        fields = ['supplier', 'document_number']
        widgets = {
            'supplier': forms.Select(attrs={'class': 'form-select'}),
            'document_number': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ej: FAC-001'}),
        }


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

    class Meta:
        model = PurchaseDetail
        fields = ['product', 'quantity', 'unit_cost']


PurchaseDetailFormSet = inlineformset_factory(
    Purchase,
    PurchaseDetail,
    form=PurchaseDetailForm,
    extra=1,           # 1 fila vacía al abrir el formulario (el JS agrega más en vivo)
    can_delete=True,   # agrega la casilla "Eliminar" a cada fila
    validate_min=False,
    min_num=0,         # no exige un mínimo de filas acá (la vista valida "al menos 1 producto" a mano)
)