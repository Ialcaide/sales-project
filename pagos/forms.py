from datetime import date

from django import forms
from django.core.exceptions import ValidationError
from .models import PagoCompra


class PagoCompraForm(forms.ModelForm):
    """
    No incluye el campo 'compra': la vista fija a qué compra pertenece el
    pago (ver pagos/views.py -> pago_create/pago_update), así que acá solo
    se editan fecha/valor/observación. 'compra' se recibe aparte para poder
    validar el valor contra el saldo disponible.
    """
    class Meta:
        model = PagoCompra
        fields = [
            'fecha', 'valor', 'forma_pago', 'observacion',
            'tarjeta_titular', 'tarjeta_cvv', 'tarjeta_expiracion',
        ]
        widgets = {
            # format='%Y-%m-%d' fuerza ISO sin importar el locale (es-ec usa
            # dd/mm/aaaa por defecto): un <input type="date"> del navegador
            # solo acepta el valor inicial en formato ISO, si no lo muestra
            # en blanco aunque el dato exista (ej. al editar un pago).
            'fecha': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}, format='%Y-%m-%d'),
            'valor': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'min': '0.01'}),
            'forma_pago': forms.Select(attrs={'class': 'form-select'}),
            'observacion': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
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

    def __init__(self, *args, compra=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.compra = compra or getattr(self.instance, 'compra', None)
        # Opcional en el form (aunque el modelo lo requiere): si no se manda,
        # clean_forma_pago() lo completa con el default 'efectivo'.
        self.fields['forma_pago'].required = False
        if self.instance.pk:
            # La forma de pago de un pago ya registrado no se puede
            # cambiar al editar — sobre todo para PAYPAL, que ya disparó un
            # payout real: permitir cambiarla acá dejaría un registro que
            # no coincide con lo que de verdad se envió/recibió, sin volver
            # a mandar (ni poder deshacer) ningún dinero real.
            self.fields['forma_pago'].disabled = True
        # Los 3 campos de tarjeta solo son obligatorios si forma_pago='tarjeta'
        # (no se puede expresar eso con required=True fijo) — se valida en
        # clean() más abajo, igual que billing/forms.py -> InvoiceForm.
        self.fields['tarjeta_titular'].required = False
        self.fields['tarjeta_cvv'].required = False
        self.fields['tarjeta_expiracion'].required = False

    def clean_forma_pago(self):
        return self.cleaned_data.get('forma_pago') or PagoCompra.EFECTIVO

    def clean_valor(self):
        valor = self.cleaned_data.get('valor')
        if valor is not None and valor <= 0:
            raise ValidationError('El valor del pago debe ser mayor a 0.')
        return valor

    def clean_fecha(self):
        fecha = self.cleaned_data.get('fecha')
        if fecha is not None and self.compra is not None:
            fecha_compra = self.compra.purchase_date.date()
            if fecha < fecha_compra:
                raise ValidationError(
                    f'La fecha del pago no puede ser anterior a la fecha de la compra ({fecha_compra:%d/%m/%Y}).'
                )
            fecha_limite = self.compra.fecha_limite_pago
            if fecha_limite and fecha > fecha_limite:
                raise ValidationError(
                    f'La fecha del pago no puede ser posterior al plazo de crédito ({fecha_limite:%d/%m/%Y}).'
                )
        return fecha

    def clean(self):
        cleaned_data = super().clean()
        valor = cleaned_data.get('valor')
        if valor is not None and self.compra is not None:
            # Si se está editando un pago existente, su propio valor anterior
            # ya está descontado del saldo actual, hay que devolverlo antes
            # de comparar (si no, nunca se podría dejar el mismo valor).
            saldo_disponible = self.compra.saldo
            if self.instance.pk:
                saldo_disponible += self.instance.valor
            if valor > saldo_disponible:
                raise ValidationError({
                    'valor': f'El pago (${valor}) no puede ser mayor al saldo pendiente (${saldo_disponible}).'
                })

            # Cuota mínima: para terminar de pagar dentro de los meses
            # pactados hay que abonar al menos total_a_pagar/meses_credito en
            # cada pago — salvo que ese abono sea justo el que liquida el
            # saldo restante (última cuota, puede ser menor).
            cuota_minima = self.compra.cuota_minima
            if cuota_minima and valor < min(cuota_minima, saldo_disponible):
                raise ValidationError({
                    'valor': (
                        f'El pago mínimo para cancelar esta compra en {self.compra.meses_credito} '
                        f'meses es de ${cuota_minima} (o el saldo restante, ${saldo_disponible}).'
                    )
                })

        # Captura informativa de tarjeta — no hay pasarela de pago real (no
        # Stripe ni similar), así que estos 3 campos solo dejan constancia
        # de que se pagó por un datáfono externo. Nunca se pide/guarda el
        # número completo de la tarjeta. Mismo criterio que
        # billing/forms.py -> InvoiceForm.clean().
        if cleaned_data.get('forma_pago') == PagoCompra.TARJETA:
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
