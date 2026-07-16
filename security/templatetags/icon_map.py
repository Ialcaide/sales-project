"""
Filtro puro de presentación: traduce los nombres de ícono Bootstrap-Icons
que `security/views.py` (ACTION_ICONS, sin tocar) sigue mandando a
permission_list.html, a su equivalente Lucide. Archivo nuevo — no modifica
ningún .py existente.
"""
from django import template

register = template.Library()

_BI_TO_LUCIDE = {
    'bi-door-open': 'door-open',
    'bi-eye': 'eye',
    'bi-plus-circle': 'circle-plus',
    'bi-pencil': 'pencil',
    'bi-trash': 'trash-2',
    'bi-file-earmark-pdf': 'file-text',
    'bi-file-earmark-excel': 'file-spreadsheet',
    'bi-whatsapp': 'message-circle',
    'bi-key': 'key',
}


@register.filter
def to_lucide(bi_icon_name):
    return _BI_TO_LUCIDE.get(bi_icon_name, 'circle')
