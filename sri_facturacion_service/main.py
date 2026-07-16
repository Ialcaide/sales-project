"""
API HTTP de este microservicio (FastAPI). Mantiene EXACTAMENTE el mismo
contrato que ya consume `sales_project/facturacion_electronica/services.py`
y `ride.py` (mismas rutas, mismo header `X-API-Key`, misma forma de
respuesta) — ver esos dos archivos para el lado cliente de este contrato.
"""
import secrets
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Response
from sqlmodel import Session

import config
import services
from client import SRIError
from database import get_session, init_db
from firma import FirmaError
from ride import build_ride_pdf
from schemas import ComprobantePayload


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title='sri_facturacion_service', lifespan=lifespan)


def verificar_api_key(x_api_key: Optional[str] = Header(default=None)):
    if not config.API_KEY or not x_api_key or not secrets.compare_digest(x_api_key, config.API_KEY):
        raise HTTPException(status_code=401, detail='API key inválida o ausente.')


@app.get('/')
def index():
    return {'servicio': 'sri_facturacion_service', 'estado': 'ok'}


@app.post('/api/comprobantes/', dependencies=[Depends(verificar_api_key)], status_code=201)
def crear_comprobante(payload: ComprobantePayload, session: Session = Depends(get_session)):
    comprobante = services.procesar_comprobante(session, payload.to_stored_dict())
    return {'comprobante': comprobante.to_dict()}


@app.get('/api/comprobantes/{clave_acceso}/', dependencies=[Depends(verificar_api_key)])
def detalle_comprobante(clave_acceso: str, session: Session = Depends(get_session)):
    comprobante = services.obtener_por_clave(session, clave_acceso)
    if comprobante is None:
        raise HTTPException(status_code=404, detail='No existe un comprobante con esa clave de acceso.')
    return {'comprobante': comprobante.to_dict()}


@app.get('/api/comprobantes/{clave_acceso}/estado-sri/', dependencies=[Depends(verificar_api_key)])
def estado_sri(clave_acceso: str, session: Session = Depends(get_session)):
    try:
        return services.consultar_estado_sri(session, clave_acceso)
    except SRIError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e


@app.get('/api/comprobantes/{clave_acceso}/ride/', dependencies=[Depends(verificar_api_key)])
def ride_pdf(clave_acceso: str, session: Session = Depends(get_session)):
    comprobante = services.obtener_por_clave(session, clave_acceso)
    if comprobante is None:
        raise HTTPException(status_code=404, detail='No existe un comprobante con esa clave de acceso.')
    try:
        pdf_bytes = build_ride_pdf(comprobante)
    except FirmaError as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
    return Response(content=pdf_bytes, media_type='application/pdf')
