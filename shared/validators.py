from django.core.exceptions import ValidationError


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