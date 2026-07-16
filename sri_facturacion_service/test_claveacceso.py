import datetime

import pytest

from claveacceso import AMBIENTE_PRUEBAS, FACTURA, digito_verificador_modulo11, generar_clave_acceso, generar_codigo_numerico


def test_generar_codigo_numerico_tiene_8_digitos():
    codigo = generar_codigo_numerico()
    assert len(codigo) == 8
    assert codigo.isdigit()


def test_generar_clave_acceso_tiene_49_digitos():
    clave = generar_clave_acceso(
        datetime.date(2026, 7, 15), '1234567890001', '001', '001', 1,
        tipo_comprobante=FACTURA, ambiente=AMBIENTE_PRUEBAS, codigo_numerico='12345678',
    )
    assert len(clave) == 49
    assert clave.isdigit()


def test_generar_clave_acceso_el_digito_verificador_es_consistente():
    clave = generar_clave_acceso(
        datetime.date(2026, 7, 15), '1234567890001', '001', '001', 1,
        tipo_comprobante=FACTURA, ambiente=AMBIENTE_PRUEBAS, codigo_numerico='12345678',
    )
    assert str(digito_verificador_modulo11(clave[:48])) == clave[48]


def test_generar_clave_acceso_ruc_invalido():
    with pytest.raises(ValueError):
        generar_clave_acceso(datetime.date(2026, 7, 15), '123', '001', '001', 1)


def test_generar_clave_acceso_establecimiento_invalido():
    with pytest.raises(ValueError):
        generar_clave_acceso(datetime.date(2026, 7, 15), '1234567890001', '1', '001', 1)
