"""
Genera la "clave de acceso" de 49 dígitos que exige el SRI para cada
comprobante electrónico (factura, nota de crédito, etc.) — es el
identificador único del comprobante, y también codifica varios datos suyos
(fecha, tipo, RUC emisor, ambiente, establecimiento/punto de emisión,
secuencial). No depende de red ni de certificado: es aritmética pura, así
que se puede testear con total confianza sin nada externo.

Copiado tal cual de sales_project/facturacion_electronica/claveacceso.py —
esta pieza nunca dependió de ningún modelo de ese proyecto, por eso se
traslada sin ningún cambio.

Estructura (48 dígitos + 1 dígito verificador = 49):
  fecha emisión (ddmmyyyy)   8
  tipo de comprobante        2   (factura = '01')
  RUC del emisor            13
  tipo de ambiente           1   ('1' pruebas, '2' producción)
  establecimiento + punto    6   (3 + 3)
  secuencial                 9
  código numérico            8   (arbitrario, lo define el emisor)
  tipo de emisión            1   ('1' = normal)
  dígito verificador         1   (módulo 11 sobre los 48 anteriores)
"""
import random

AMBIENTE_PRUEBAS = '1'
AMBIENTE_PRODUCCION = '2'

TIPO_EMISION_NORMAL = '1'

FACTURA = '01'


def digito_verificador_modulo11(clave_48_digitos):
    """
    Algoritmo módulo 11 del SRI: se recorre la clave de derecha a izquierda
    multiplicando cada dígito por factores que ciclan 2,3,4,5,6,7. El
    verificador es 11 - (suma % 11), con los casos especiales 11->0 y 10->1.
    """
    factores = [2, 3, 4, 5, 6, 7]
    suma = 0
    for i, digito in enumerate(reversed(clave_48_digitos)):
        factor = factores[i % len(factores)]
        suma += int(digito) * factor
    residuo = suma % 11
    verificador = 11 - residuo
    if verificador == 11:
        return 0
    if verificador == 10:
        return 1
    return verificador


def generar_codigo_numerico():
    """8 dígitos arbitrarios que identifican esta emisión concreta del
    comprobante (permite reintentar con una clave distinta si hiciera falta)."""
    return f'{random.randint(0, 99999999):08d}'


def generar_clave_acceso(
    fecha_emision, ruc, establecimiento, punto_emision, secuencial,
    tipo_comprobante=FACTURA, ambiente=AMBIENTE_PRUEBAS,
    codigo_numerico=None, tipo_emision=TIPO_EMISION_NORMAL,
):
    """
    fecha_emision: date/datetime. ruc: 13 dígitos. establecimiento/punto_emision:
    3 dígitos cada uno. secuencial: número o string, se rellena a 9 dígitos.
    Devuelve la clave de acceso completa (49 dígitos, string).
    """
    if codigo_numerico is None:
        codigo_numerico = generar_codigo_numerico()

    if len(ruc) != 13 or not ruc.isdigit():
        raise ValueError(f'RUC inválido para la clave de acceso: {ruc!r} (deben ser 13 dígitos).')
    if len(establecimiento) != 3 or not establecimiento.isdigit():
        raise ValueError(f'Establecimiento inválido: {establecimiento!r} (deben ser 3 dígitos).')
    if len(punto_emision) != 3 or not punto_emision.isdigit():
        raise ValueError(f'Punto de emisión inválido: {punto_emision!r} (deben ser 3 dígitos).')
    if len(codigo_numerico) != 8 or not codigo_numerico.isdigit():
        raise ValueError(f'Código numérico inválido: {codigo_numerico!r} (deben ser 8 dígitos).')

    clave_48 = (
        f'{fecha_emision:%d%m%Y}'
        f'{tipo_comprobante}'
        f'{ruc}'
        f'{ambiente}'
        f'{establecimiento}{punto_emision}'
        f'{int(secuencial):09d}'
        f'{codigo_numerico}'
        f'{tipo_emision}'
    )
    if len(clave_48) != 48:
        raise ValueError(f'La clave de 48 dígitos no quedó con la longitud esperada: {clave_48!r} ({len(clave_48)} dígitos).')

    verificador = digito_verificador_modulo11(clave_48)
    return f'{clave_48}{verificador}'
