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

from datetime import date
from django.core.exceptions import ValidationError
from django.forms import inlineformset_factory
from .models import Customer, Invoice, InvoiceDetail, Supplier

class InvoiceForm(forms.ModelForm):
    """
    Cliente y tipo de pago — los productos de la factura los maneja el
    formset de abajo. 'consumidor_final' no es un campo del modelo: cuando
    se marca, el cliente elegido en el <select> se ignora y se reemplaza en
    clean() por el registro genérico Customer.get_or_create_consumidor_final()
    (ver billing/models.py), y no se admite tipo_pago='credito' (una venta
    de mostrador siempre es pago inmediato).
    """
    consumidor_final = forms.BooleanField(
        required=False, label='Consumidor Final (venta sin registrar datos del cliente)',
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'}),
    )

    class Meta:
        model = Invoice
        fields = [
            'customer', 'tipo_pago', 'forma_pago', 'meses_credito', 'monto_recibido',
            'tarjeta_titular', 'tarjeta_cvv', 'tarjeta_expiracion',
        ]
        widgets = {
            'customer': forms.Select(attrs={'class': 'form-select'}),
            'tipo_pago': forms.Select(attrs={'class': 'form-select'}),
            'forma_pago': forms.Select(attrs={'class': 'form-select'}),
            'meses_credito': forms.NumberInput(attrs={
                'class': 'form-control', 'min': 1, 'max': Invoice.MESES_CREDITO_MAX,
                'placeholder': 'Ej: 3',
            }),
            'monto_recibido': forms.NumberInput(attrs={
                'class': 'form-control', 'step': '0.01', 'min': '0', 'placeholder': 'Ej: 50.00',
            }),
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
        # El cliente solo es obligatorio si NO se marca "Consumidor Final".
        self.fields['customer'].required = False
        # Los 3 campos de tarjeta solo son obligatorios si forma_pago='tarjeta'
        # (no se puede expresar eso con required=True fijo) — se valida en
        # clean() más abajo.
        self.fields['tarjeta_titular'].required = False
        self.fields['tarjeta_cvv'].required = False
        self.fields['tarjeta_expiracion'].required = False
        # PayPal solo se ofrece como forma de pago si está configurado
        # (PAYPAL_CLIENT_ID/SECRET en el .env) — mismo criterio que el botón
        # equivalente en cobros/templates/cobros/cobro_form.html.
        from django.conf import settings
        if not (settings.PAYPAL_CLIENT_ID and settings.PAYPAL_CLIENT_SECRET):
            self.fields['forma_pago'].choices = [
                c for c in self.fields['forma_pago'].choices if c[0] != Invoice.PAYPAL
            ]

    def clean(self):
        cleaned_data = super().clean()
        consumidor_final = cleaned_data.get('consumidor_final')
        customer = cleaned_data.get('customer')
        tipo_pago = cleaned_data.get('tipo_pago')
        forma_pago = cleaned_data.get('forma_pago')

        if consumidor_final:
            if tipo_pago == Invoice.CREDITO:
                raise ValidationError({
                    'tipo_pago': 'Consumidor Final no admite crédito, solo pago inmediato (contado).'
                })
            cleaned_data['customer'] = Customer.get_or_create_consumidor_final()
        elif not customer:
            raise ValidationError({
                'customer': 'Selecciona un cliente o marca la opción "Consumidor Final".'
            })

        # Captura informativa de tarjeta — no hay pasarela de pago real (no
        # Stripe ni similar), así que estos 3 campos solo dejan constancia
        # de que se cobró por un datáfono externo. Nunca se pide/guarda el
        # número completo de la tarjeta.
        if forma_pago == Invoice.TARJETA:
            titular = cleaned_data.get('tarjeta_titular')
            cvv = cleaned_data.get('tarjeta_cvv')
            expira = cleaned_data.get('tarjeta_expiracion')
            if not titular or not titular.strip():
                raise ValidationError({'tarjeta_titular': 'Indica el nombre del titular de la tarjeta.'})
            if not cvv or not cvv.isdigit() or len(cvv) not in (3, 4):
                raise ValidationError({
                    'tarjeta_cvv': 'Ingresa el CVV/CVC de la tarjeta (3 o 4 números).'
                })
            if not expira:
                raise ValidationError({'tarjeta_expiracion': 'Indica la fecha de expiración de la tarjeta.'})
            elif expira < date.today():
                raise ValidationError({'tarjeta_expiracion': 'La tarjeta está vencida.'})

        return cleaned_data


class CustomerQuickCreateForm(forms.ModelForm):
    """
    Alta rápida de cliente desde el modal del paso 1 del wizard de factura
    (ver billing/views.py -> customer_quick_create). Mismos campos que
    CustomerCreateView, sin is_active (nace activo) — reutiliza
    Customer.clean() (normalización de teléfono, validación de cédula) sin
    duplicar nada, vía full_clean() en form.is_valid().
    """
    class Meta:
        model = Customer
        fields = ['tipo_identificacion', 'dni', 'first_name', 'last_name', 'email', 'phone', 'address']
        widgets = {
            'tipo_identificacion': forms.Select(attrs={'class': 'form-select'}),
            'dni': forms.TextInput(attrs={'class': 'form-control'}),
            'first_name': forms.TextInput(attrs={'class': 'form-control'}),
            'last_name': forms.TextInput(attrs={'class': 'form-control'}),
            'email': forms.EmailInput(attrs={'class': 'form-control'}),
            'phone': forms.TextInput(attrs={'class': 'form-control'}),
            'address': forms.TextInput(attrs={'class': 'form-control'}),
        }


class SupplierQuickCreateForm(forms.ModelForm):
    """
    Alta rápida de proveedor desde el modal del paso 1 del wizard de compra
    (ver billing/views.py -> supplier_quick_create). Mismos campos que
    SupplierCreateView, sin is_active (nace activo) — mismo patrón que
    CustomerQuickCreateForm de arriba.
    """
    class Meta:
        model = Supplier
        fields = ['name', 'contact_name', 'email', 'phone', 'address']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'contact_name': forms.TextInput(attrs={'class': 'form-control'}),
            'email': forms.EmailInput(attrs={'class': 'form-control'}),
            'phone': forms.TextInput(attrs={'class': 'form-control'}),
            'address': forms.TextInput(attrs={'class': 'form-control'}),
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
        fields = ['name', 'description', 'brand', 'group', 'suppliers', 'unit_price', 'stock',
                  'stock_minimo', 'barcode', 'fecha_vencimiento', 'image', 'is_active']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'brand': forms.Select(attrs={'class': 'form-select'}),
            'group': forms.Select(attrs={'class': 'form-select'}),
            'suppliers': forms.SelectMultiple(attrs={'class': 'form-select'}),
            'unit_price': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'stock': forms.NumberInput(attrs={'class': 'form-control'}),
            'stock_minimo': forms.NumberInput(attrs={'class': 'form-control', 'min': '0'}),
            'barcode': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Opcional'}),
            'fecha_vencimiento': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}, format='%Y-%m-%d'),
            'image': forms.ClearableFileInput(attrs={'class': 'form-control'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Solo sugiere el umbral configurado (ConfiguracionSistema.stock_minimo_default)
        # en productos NUEVOS — al editar uno existente se respeta el valor que ya tiene.
        if not self.instance.pk:
            from configuracion.models import ConfiguracionSistema
            self.fields['stock_minimo'].initial = ConfiguracionSistema.get_solo().stock_minimo_default

    def clean_unit_price(self):
        unit_price = self.cleaned_data.get('unit_price')
        if unit_price is not None and unit_price <= 0:
            raise forms.ValidationError('El precio unitario debe ser mayor a 0.')
        return unit_price