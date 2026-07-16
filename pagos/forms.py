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
        fields = ['fecha', 'valor', 'forma_pago', 'observacion']
        widgets = {
            # format='%Y-%m-%d' fuerza ISO sin importar el locale (es-ec usa
            # dd/mm/aaaa por defecto): un <input type="date"> del navegador
            # solo acepta el valor inicial en formato ISO, si no lo muestra
            # en blanco aunque el dato exista (ej. al editar un pago).
            'fecha': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}, format='%Y-%m-%d'),
            'valor': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'min': '0.01'}),
            'forma_pago': forms.Select(attrs={'class': 'form-select'}),
            'observacion': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
        }

    def __init__(self, *args, compra=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.compra = compra or getattr(self.instance, 'compra', None)
        # Opcional en el form (aunque el modelo lo requiere): si no se manda,
        # clean_forma_pago() lo completa con el default 'efectivo'.
        self.fields['forma_pago'].required = False

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
        return cleaned_data
