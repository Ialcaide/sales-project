import re

from django.core.exceptions import ValidationError

# '+' opcional seguido de 7 a 15 dígitos (formato internacional simple, sin
# validar el plan de numeración de cada país). Se usa tanto para
# UserProfile.phone (security) como para Customer.phone/Supplier.phone
# (billing) — cualquier número que vaya a usarse con WhatsApp (Twilio) debe
# pasar por acá primero.
PHONE_RE = re.compile(r'^\+?\d{7,15}$')

# Prefijo por defecto para normalizar números que llegan sin código de país
# (ej. capturados como "0987654321"). Cambiar acá si el negocio opera en
# otro país — es el único lugar donde está harcodeado.
DEFAULT_COUNTRY_CODE = '+593'

# Pasaporte: documento extranjero, alfanumérico — no sigue el algoritmo de
# cédula/RUC ecuatoriano (ver validate_cedula_ec), así que solo se valida
# longitud/caracteres razonables, sin checksum.
PASAPORTE_RE = re.compile(r'^[A-Za-z0-9]{5,20}$')


def normalize_phone(phone):
    """
    Deja un teléfono listo para WhatsApp (formato E.164: '+' + código de país
    + número, sin espacios). Si ya trae '+', se respeta tal cual (podría ser
    de otro país). Si no, se asume Ecuador: se le quita el 0 inicial típico
    de los celulares locales (ej. 0987654321) y se antepone +593.
    No valida el resultado — para eso usar validate_phone() después.
    """
    phone = (phone or '').strip().replace(' ', '').replace('-', '')
    if not phone or phone.startswith('+'):
        return phone
    if phone.startswith('0'):
        phone = phone[1:]
    return f'{DEFAULT_COUNTRY_CODE}{phone}'


def validate_phone(phone):
    """Valida que el teléfono (ya normalizado o no) tenga forma internacional simple."""
    if not PHONE_RE.match(phone or ''):
        raise ValidationError(
            'Ingresa un número de teléfono válido (solo dígitos, con o sin "+" al inicio, entre 7 y 15 dígitos).',
            code='invalid_phone',
        )
    return phone


def validate_cedula_ec(value):
    """
    Valida cédula ecuatoriana (10 dígitos) o RUC (13 dígitos)
    usando el algoritmo oficial del Registro Civil de Ecuador.
    """

    if not value.isdigit():
        raise ValidationError(
            'La identificación solo debe contener números.',
            code='invalid_chars'
        )

    if len(value) not in (10, 13):
        raise ValidationError(
            'La identificación debe tener 10 dígitos (cédula) o 13 dígitos (RUC).',
            code='invalid_length'
        )

    province = int(value[:2])
    if province < 1 or province > 24:
        raise ValidationError(
            f'Código de provincia inválido: {province}. Debe estar entre 01 y 24.',
            code='invalid_province'
        )

    third_digit = int(value[2])
    if third_digit >= 6:
        raise ValidationError(
            'El tercer dígito debe ser menor a 6 para personas naturales.',
            code='invalid_third'
        )

    coefficients = [2, 1, 2, 1, 2, 1, 2, 1, 2]
    total = 0

    for i in range(9):
        result = int(value[i]) * coefficients[i]
        if result > 9:
            result -= 9
        total += result

    verifier = 10 - (total % 10)
    if verifier == 10:
        verifier = 0

    if verifier != int(value[9]):
        raise ValidationError(
            'Número de identificación inválido. El dígito verificador no coincide.',
            code='invalid_verifier'
        )

    return value


def validate_pasaporte(value):
    """Pasaporte extranjero: alfanumérico, entre 5 y 20 caracteres, sin
    espacios ni símbolos. No hay un algoritmo de verificación único entre
    países (a diferencia de la cédula/RUC ecuatoriana), así que esto es
    solo una validación de forma razonable."""
    if not PASAPORTE_RE.match(value or ''):
        raise ValidationError(
            'El pasaporte debe tener entre 5 y 20 caracteres alfanuméricos (sin espacios ni símbolos).',
            code='invalid_pasaporte',
        )
    return value