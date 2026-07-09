# Los Form/ModelForm son el puente entre el HTML (inputs, selects, labels) y
# los modelos de Python: definen qué campos se piden, cómo se validan, y con
# qué clase CSS se renderiza cada input (los 'widgets' de abajo).
#
# ModelForm (la mayoría de las clases de este archivo) genera el formulario
# automáticamente a partir de un modelo (Meta.model + Meta.fields) — no hay
# que declarar cada campo a mano, Django los infiere del modelo. Solo se
# declaran a mano los campos que necesitan algo especial (validación extra,
# widget distinto, o que no son parte del modelo, como 'password1'/'password2').

from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User
from .models import Brand

# NOTA: este formulario (y su vista SignUpView en views.py) es un flujo de
# auto-registro público que quedó de una versión anterior del proyecto y
# hoy no está enlazado desde ningún lugar de la interfaz — el alta de
# usuarios ahora la hace un administrador desde security/ (ver
# security.forms.UserRegisterForm). Se deja documentado para que no genere
# confusión si lo encuentras, pero no es el flujo real que usa el sistema.
class SignUpForm(UserCreationForm):
    email = forms.EmailField(required=True, widget=forms.EmailInput(attrs={'class':'form-control'}))
    first_name = forms.CharField(max_length=100, widget=forms.TextInput(attrs={'class':'form-control'}))
    last_name = forms.CharField(max_length=100, widget=forms.TextInput(attrs={'class':'form-control'}))
    class Meta:
        model = User
        fields = ['username','first_name','last_name','email','password1','password2']
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for f in self.fields: self.fields[f].widget.attrs['class'] = 'form-control'

class BrandForm(forms.ModelForm):
    class Meta:
        model = Brand
        fields = ['name', 'description', 'is_active'] #campos de productos
        widgets = {
            'name': forms.TextInput(attrs={'class':'form-control'}), #atributos separando por coma
            'description': forms.Textarea(attrs={'class':'form-control','rows':3}),
            'is_active': forms.CheckboxInput(attrs={'class':'form-check-input'}),
        }
        
    # clean_<campo>: validación de UN campo específico. Django la corre sola
    # al llamar form.is_valid(), y el error queda ligado a ese campo (se
    # muestra justo debajo de él, no en el formulario entero).
    def clean_name(self):
        name = self.cleaned_data.get('name')
        if not name or not name.strip():
            raise forms.ValidationError('El nombre de la marca es obligatorio.')
        return name.strip()

from django.forms import inlineformset_factory
from .models import Invoice, InvoiceDetail

class InvoiceForm(forms.ModelForm):
    """Solo pide el cliente — los productos de la factura los maneja el formset de abajo."""
    class Meta:
        model = Invoice
        fields = ['customer']
        widgets = {
            'customer': forms.Select(attrs={'class': 'form-select'}),
        }

# Un formset es "varios formularios del mismo tipo, repetidos" — acá, varias
# líneas de InvoiceDetail (producto + cantidad + precio) dentro de UNA sola
# factura. inlineformset_factory ata cada línea automáticamente a su Invoice
# padre (por la ForeignKey invoice -> InvoiceDetail.invoice).
#   extra=1        -> muestra 1 línea vacía además de las que ya existan
#   can_delete=True -> agrega una casilla "Eliminar" por línea
# En el template, JavaScript agrega más líneas en vivo (ver invoice_form.html),
# clonando esta misma estructura con un índice distinto (form-0, form-1, ...).
InvoiceDetailFormSet = inlineformset_factory(
    Invoice,
    InvoiceDetail,
    fields=['product', 'quantity', 'unit_price'],
    extra=1,
    can_delete=True,
    widgets={
        'product': forms.Select(attrs={'class': 'form-select'}),
        'quantity': forms.NumberInput(attrs={'class': 'form-control', 'min': 1}),
        'unit_price': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
    }
)

from .models import Product

class ProductForm(forms.ModelForm):
    class Meta:
        model = Product
        fields = ['name', 'description', 'brand', 'group', 'suppliers', 'unit_price', 'stock', 'image', 'is_active']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'brand': forms.Select(attrs={'class': 'form-select'}),
            'group': forms.Select(attrs={'class': 'form-select'}),
            'suppliers': forms.SelectMultiple(attrs={'class': 'form-select'}),
            'unit_price': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'stock': forms.NumberInput(attrs={'class': 'form-control'}),
            'image': forms.ClearableFileInput(attrs={'class': 'form-control'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }

    def clean_unit_price(self):
        unit_price = self.cleaned_data.get('unit_price')
        if unit_price is not None and unit_price <= 0:
            raise forms.ValidationError('El precio unitario debe ser mayor a 0.')
        return unit_price