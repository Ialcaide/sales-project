from django import forms
from django.core.exceptions import ValidationError
from .models import CobroFactura


class CobroFacturaForm(forms.ModelForm):
    """
    No incluye el campo 'factura': la vista fija a qué factura pertenece el
    cobro (ver cobros/views.py -> cobro_create/cobro_update), así que acá
    solo se editan fecha/valor/observación. 'factura' se recibe aparte para
    poder validar el valor contra el saldo disponible.
    """
    class Meta:
        model = CobroFactura
        # 'forma_pago' NO es un campo de este formulario: este form es
        # exclusivamente para cobros en EFECTIVO (el modelo lo deja en su
        # default 'efectivo' al instanciar un CobroFactura nuevo, ver
        # CobroFactura.forma_pago en cobros/models.py). Pagar con PayPal es
        # un flujo completamente aparte — ver cobro_paypal_iniciar en
        # cobros/views.py, que sí cobra de verdad y crea el CobroFactura con
        # forma_pago=PAYPAL directamente, sin pasar por este formulario. Así
        # queda una sola forma real de pagar con PayPal, no dos.
        fields = ['fecha', 'valor', 'monto_recibido', 'observacion']
        widgets = {
            # format='%Y-%m-%d' fuerza ISO sin importar el locale (es-ec usa
            # dd/mm/aaaa por defecto): un <input type="date"> del navegador
            # solo acepta el valor inicial en formato ISO, si no lo muestra
            # en blanco aunque el dato exista.
            'fecha': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}, format='%Y-%m-%d'),
            'valor': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'min': '0.01'}),
            'monto_recibido': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'min': '0'}),
            'observacion': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
        }

    def __init__(self, *args, factura=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.factura = factura or getattr(self.instance, 'factura', None)
        # Al editar un cobro ya existente, la fecha queda fija a la que se
        # registró originalmente (solo se corrigen valor/observación).
        # disabled=True hace que Django ignore cualquier valor enviado por
        # el cliente para este campo y use siempre el valor inicial (el que
        # ya tenía la instancia), sin importar qué llegue en el POST.
        if self.instance.pk:
            self.fields['fecha'].disabled = True

    def clean_valor(self):
        valor = self.cleaned_data.get('valor')
        if valor is not None and valor <= 0:
            raise ValidationError('El valor del cobro debe ser mayor a 0.')
        return valor

    def clean_fecha(self):
        # Mismo criterio que PagoCompraForm.clean_fecha (pagos/forms.py):
        # el cobro no puede fecharse antes de que la factura existiera, ni
        # después del plazo de crédito (Invoice.fecha_limite_pago, cuando la
        # factura tiene meses_credito definido).
        fecha = self.cleaned_data.get('fecha')
        if fecha is not None and self.factura is not None:
            fecha_factura = self.factura.invoice_date.date()
            if fecha < fecha_factura:
                raise ValidationError(
                    f'La fecha del cobro no puede ser anterior a la fecha de la factura ({fecha_factura:%d/%m/%Y}).'
                )
            fecha_limite = self.factura.fecha_limite_pago
            if fecha_limite and fecha > fecha_limite:
                raise ValidationError(
                    f'La fecha del cobro no puede ser posterior al plazo de crédito ({fecha_limite:%d/%m/%Y}).'
                )
        return fecha

    def clean(self):
        cleaned_data = super().clean()
        valor = cleaned_data.get('valor')
        if valor is not None and self.factura is not None:
            if not self.factura.is_active:
                raise ValidationError('No se puede registrar un cobro sobre una factura anulada.')

            # Si se está editando un cobro existente, su propio valor anterior
            # ya está descontado del saldo actual, hay que devolverlo antes
            # de comparar (si no, nunca se podría dejar el mismo valor).
            saldo_disponible = self.factura.saldo
            if self.instance.pk:
                saldo_disponible += self.instance.valor
            if valor > saldo_disponible:
                raise ValidationError({
                    'valor': f'El cobro (${valor}) no puede ser mayor al saldo pendiente (${saldo_disponible}).'
                })

            # Cuota mínima: mismo criterio que PagoCompraForm.clean() — para
            # terminar de cobrar dentro de los meses pactados hay que abonar
            # al menos total_a_pagar/meses_credito en cada cobro, salvo que
            # ese abono sea justo el que liquida el saldo restante.
            cuota_minima = self.factura.cuota_minima
            if cuota_minima and valor < min(cuota_minima, saldo_disponible):
                raise ValidationError({
                    'valor': (
                        f'El cobro mínimo para cancelar esta factura en {self.factura.meses_credito} '
                        f'meses es de ${cuota_minima} (o el saldo restante, ${saldo_disponible}).'
                    )
                })

            # En efectivo hay que saber cuánto entregó el cliente para
            # calcular el cambio (ver CobroFactura.cambio) — no puede ser
            # menor al valor que se está cobrando. forma_pago no es un campo
            # de este form: self.instance.forma_pago ya es 'efectivo' (default
            # del modelo) para un cobro nuevo, o lo que ya tenía si se está
            # editando uno pagado por PayPal (ver Meta.fields más arriba).
            if self.instance.forma_pago == CobroFactura.EFECTIVO:
                monto_recibido = cleaned_data.get('monto_recibido')
                if monto_recibido is None:
                    raise ValidationError({
                        'monto_recibido': 'Indica cuánto dinero te entregó el cliente para calcular el cambio.'
                    })
                if monto_recibido < valor:
                    raise ValidationError({
                        'monto_recibido': f'El monto recibido (${monto_recibido}) no puede ser menor al cobro (${valor}).'
                    })
            else:
                cleaned_data['monto_recibido'] = None
        return cleaned_data
