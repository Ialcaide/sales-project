from django import forms
from django.core.exceptions import ValidationError


class DevolucionMotivoForm(forms.Form):
    """
    Solo pide el motivo — qué líneas/cantidades se devuelven se arma a mano
    en la vista (devoluciones/views.py -> devolucion_create), porque la
    cantidad máxima disponible por línea varía según cuánto ya se devolvió
    antes, algo que un formset estático no puede validar por su cuenta.
    """
    motivo = forms.CharField(
        widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 3,
                                      'placeholder': 'Ej: Producto defectuoso, talla incorrecta...'}),
        label='Motivo de la devolución',
    )

    def clean_motivo(self):
        motivo = self.cleaned_data.get('motivo', '').strip()
        if not motivo:
            raise ValidationError('El motivo es obligatorio.')
        return motivo
