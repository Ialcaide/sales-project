from datetime import date

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
        # 'forma_pago' SÍ es un campo de este formulario, pero restringido a
        # Efectivo/Tarjeta en __init__ más abajo — PayPal sigue sin poder
        # elegirse acá NUNCA: eso sigue siendo un flujo completamente aparte
        # (ver cobro_paypal_iniciar en cobros/views.py, que sí cobra de
        # verdad y crea el CobroFactura con forma_pago=PAYPAL directamente).
        # Así queda una sola forma real de pagar con PayPal, no dos.
        fields = [
            'fecha', 'valor', 'forma_pago', 'monto_recibido', 'observacion',
            'tarjeta_titular', 'tarjeta_cvv', 'tarjeta_expiracion',
        ]
        widgets = {
            # format='%Y-%m-%d' fuerza ISO sin importar el locale (es-ec usa
            # dd/mm/aaaa por defecto): un <input type="date"> del navegador
            # solo acepta el valor inicial en formato ISO, si no lo muestra
            # en blanco aunque el dato exista.
            'fecha': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}, format='%Y-%m-%d'),
            'valor': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'min': '0.01'}),
            'forma_pago': forms.Select(attrs={'class': 'form-select'}),
            'monto_recibido': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'min': '0'}),
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
            # La forma de pago de un cobro ya registrado no se puede
            # reclasificar después (afectaría retroactivamente si generó o
            # no un MovimientoCaja) — disabled=True fuerza a que clean()
            # siga viendo el valor original sin importar qué llegue en el
            # POST, igual que ya hacía 'fecha'. Esto también preserva el
            # comportamiento de siempre para un cobro pagado por PayPal
            # (forma_pago='paypal' nunca aparece en las choices de abajo,
            # pero como el campo queda deshabilitado, editar ese cobro no
            # lo cambia a otra cosa).
            self.fields['forma_pago'].disabled = True
        # PayPal NUNCA es una opción ELEGIBLE en este form al crear (se
        # filtra de las choices en vez de dejar que ModelForm traiga las 3
        # del modelo) — pero si ya se está EDITANDO un cobro que de hecho
        # se pagó por PayPal, 'paypal' se deja en las choices (el campo ya
        # quedó disabled arriba, así que igual no se puede elegir a mano;
        # esto solo evita que la validación rechace el propio valor ya
        # guardado en la instancia al volver a limpiarlo en clean()).
        ya_es_paypal = self.instance.pk and self.instance.forma_pago == CobroFactura.PAYPAL
        if not ya_es_paypal:
            self.fields['forma_pago'].choices = [
                c for c in self.fields['forma_pago'].choices if c[0] != CobroFactura.PAYPAL
            ]
        self.fields['forma_pago'].required = False
        # Los 3 campos de tarjeta solo son obligatorios si forma_pago='tarjeta'
        # (no se puede expresar eso con required=True fijo) — se valida en
        # clean() más abajo, igual que billing/forms.py -> InvoiceForm.
        self.fields['tarjeta_titular'].required = False
        self.fields['tarjeta_cvv'].required = False
        self.fields['tarjeta_expiracion'].required = False

    def clean_forma_pago(self):
        return self.cleaned_data.get('forma_pago') or CobroFactura.EFECTIVO

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

            # forma_pago ya viene de clean_forma_pago() (posteado en un
            # cobro nuevo, o fijo al valor original si se está editando uno
            # existente — ver 'forma_pago'.disabled en __init__).
            forma_pago = cleaned_data.get('forma_pago')

            # En efectivo hay que saber cuánto entregó el cliente para
            # calcular el cambio (ver CobroFactura.cambio) — no puede ser
            # menor al valor que se está cobrando.
            if forma_pago == CobroFactura.EFECTIVO:
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

            # Captura informativa de tarjeta — no hay pasarela de pago real
            # (no Stripe ni similar), así que estos 3 campos solo dejan
            # constancia de que se cobró por un datáfono externo. Nunca se
            # pide/guarda el número completo de la tarjeta. Mismo criterio
            # que billing/forms.py -> InvoiceForm.clean().
            if forma_pago == CobroFactura.TARJETA:
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
