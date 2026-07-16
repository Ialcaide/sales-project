import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine
from sqlmodel.pool import StaticPool

import config
import main
from database import get_session


@pytest.fixture()
def session():
    engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    with Session(engine) as db_session:
        yield db_session


@pytest.fixture()
def client(session):
    def _get_session_override():
        yield session

    main.app.dependency_overrides[get_session] = _get_session_override
    yield TestClient(main.app)
    main.app.dependency_overrides.clear()


@pytest.fixture()
def api_key_headers():
    return {'X-API-Key': config.API_KEY}


@pytest.fixture()
def payload_dict():
    """Payload genérico válido — consumidor final, una línea, contado."""
    return {
        'referencia_externa': 'billing.invoice:1',
        'fecha_emision': '2026-07-15',
        'fecha_emision_ddmmyyyy': '15/07/2026',
        'emisor': {
            'ruc': '1234567890001',
            'razon_social': 'TECNOSTOCK S.A.',
            'nombre_comercial': 'TecnoStock',
            'direccion_matriz': 'Av. Siempre Viva 123',
            'obligado_contabilidad': True,
            'establecimiento': '001',
            'punto_emision': '001',
        },
        'comprador': {'es_consumidor_final': True},
        'lineas': [
            {'codigo': '1', 'descripcion': 'Mouse inalámbrico', 'cantidad': '2', 'precio_unitario': '10.00', 'codigo_barras': '7501234567890'},
        ],
        'iva_porcentaje': '15.00',
        'subtotal': '20.00',
        'iva_valor': '3.00',
        'total': '23.00',
        'forma_pago': {'codigo_sri': '01', 'es_credito': False},
    }
