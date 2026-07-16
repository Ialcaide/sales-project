"""
Orquesta el flujo completo de un comprobante: reservar secuencial/clave de
acceso, armar el XML, firmarlo, enviarlo al SRI, y consultar su
autorización — mismo flujo que tenía la versión Django original de este
mismo servicio, portado a sesiones SQLModel síncronas en vez del ORM de
Django. `main.py` es la única capa que traduce esto a HTTP; este módulo no
sabe nada de FastAPI.
"""
import datetime
import logging

from sqlmodel import Session, select

import config
from claveacceso import AMBIENTE_PRODUCCION, AMBIENTE_PRUEBAS, FACTURA, generar_clave_acceso
from client import SRIError, consultar_autorizacion, enviar_recepcion
from firma import FirmaError, cargar_certificado, firmar_xml
from models import ComprobanteElectronico, SecuencialSRI
from xml_builder import construir_xml_factura

logger = logging.getLogger(__name__)

# Traduce el estado que devuelve el web service de autorización del SRI
# (texto libre en español) al estado local que este servicio guarda.
_ESTADOS_SRI = {
    'AUTORIZADO': ComprobanteElectronico.AUTORIZADO,
    'NO AUTORIZADO': ComprobanteElectronico.NO_AUTORIZADO,
    'EN PROCESO': ComprobanteElectronico.EN_PROCESO,
    'NO_ENCONTRADO': ComprobanteElectronico.EN_PROCESO,
}


def _marcar_error(session: Session, comprobante: ComprobanteElectronico, mensaje: str) -> ComprobanteElectronico:
    comprobante.estado = ComprobanteElectronico.ERROR
    comprobante.mensajes = (comprobante.mensajes or []) + [mensaje]
    comprobante.actualizado_en = datetime.datetime.now(datetime.timezone.utc)
    session.add(comprobante)
    session.commit()
    session.refresh(comprobante)
    return comprobante


def _reservar_comprobante(session: Session, payload: dict) -> ComprobanteElectronico:
    """Reserva un secuencial nuevo y calcula la clave de acceso. El ambiente
    SIEMPRE lo decide la configuración propia de este servicio
    (config.SRI_AMBIENTE) — nunca el payload del cliente: si el emisor no
    controla contra qué WSDL del SRI (pruebas/producción) se manda el
    comprobante, la clave de acceso podría quedar codificada con un
    ambiente distinto al que realmente se usó para enviarlo."""
    emisor = payload['emisor']
    establecimiento = emisor['establecimiento']
    punto_emision = emisor['punto_emision']

    secuencial = SecuencialSRI.siguiente(session, establecimiento, punto_emision, tipo_comprobante=FACTURA)
    ambiente = AMBIENTE_PRODUCCION if config.SRI_AMBIENTE == 'produccion' else AMBIENTE_PRUEBAS
    fecha_emision = datetime.date.fromisoformat(payload['fecha_emision'])

    clave_acceso = generar_clave_acceso(
        fecha_emision, emisor['ruc'], establecimiento, punto_emision, secuencial,
        tipo_comprobante=FACTURA, ambiente=ambiente,
    )

    comprobante = ComprobanteElectronico(
        referencia_externa=payload['referencia_externa'],
        payload=payload,
        tipo_comprobante=FACTURA,
        ambiente=ambiente,
        establecimiento=establecimiento,
        punto_emision=punto_emision,
        secuencial=f'{secuencial:09d}',
        clave_acceso=clave_acceso,
        estado=ComprobanteElectronico.GENERADO,
    )
    session.add(comprobante)
    session.commit()
    session.refresh(comprobante)
    return comprobante


def _consultar_y_guardar_autorizacion(session: Session, comprobante: ComprobanteElectronico) -> ComprobanteElectronico:
    try:
        estado, numero_autorizacion, fecha_autorizacion, xml_autorizado, mensajes = consultar_autorizacion(
            comprobante.clave_acceso,
        )
    except SRIError as e:
        return _marcar_error(session, comprobante, str(e))

    comprobante.estado = _ESTADOS_SRI.get(estado, ComprobanteElectronico.EN_PROCESO)
    comprobante.numero_autorizacion = numero_autorizacion
    if fecha_autorizacion:
        comprobante.fecha_autorizacion = fecha_autorizacion
    if xml_autorizado:
        comprobante.xml_autorizado = xml_autorizado
    if mensajes:
        comprobante.mensajes = mensajes
    comprobante.actualizado_en = datetime.datetime.now(datetime.timezone.utc)
    session.add(comprobante)
    session.commit()
    session.refresh(comprobante)
    return comprobante


def _generar_firmar_y_enviar(session: Session, comprobante: ComprobanteElectronico, payload: dict) -> ComprobanteElectronico:
    try:
        xml_bytes = construir_xml_factura(payload, comprobante)
        comprobante.xml_generado = xml_bytes.decode('utf-8')
        comprobante.estado = ComprobanteElectronico.GENERADO
        session.add(comprobante)
        session.commit()

        private_key, certificate = cargar_certificado(config.SRI_CERTIFICADO_PATH, config.SRI_CERTIFICADO_PASSWORD)
        xml_firmado = firmar_xml(xml_bytes, private_key, certificate)
        comprobante.xml_firmado = xml_firmado.decode('utf-8')
        comprobante.estado = ComprobanteElectronico.FIRMADO
        session.add(comprobante)
        session.commit()

        estado_envio, mensajes = enviar_recepcion(xml_firmado)
        comprobante.mensajes = mensajes
        comprobante.estado = (
            ComprobanteElectronico.RECIBIDA if estado_envio == 'RECIBIDA' else ComprobanteElectronico.DEVUELTA
        )
        comprobante.actualizado_en = datetime.datetime.now(datetime.timezone.utc)
        session.add(comprobante)
        session.commit()
        session.refresh(comprobante)
    except (FirmaError, SRIError, ValueError) as e:
        logger.exception('No se pudo generar/firmar/enviar el comprobante %s', comprobante.referencia_externa)
        return _marcar_error(session, comprobante, str(e))

    if comprobante.estado == ComprobanteElectronico.RECIBIDA:
        comprobante = _consultar_y_guardar_autorizacion(session, comprobante)
    return comprobante


def procesar_comprobante(session: Session, payload: dict) -> ComprobanteElectronico:
    """Punto de entrada de POST /api/comprobantes/. Idempotente por
    referencia_externa con manejo inteligente de estados:
    - Si ya existe y está AUTORIZADO, EN_PROCESO o FIRMADO → lo devuelve tal cual
      (no quema un segundo secuencial ni vuelve a enviar innecesariamente).
    - Si ya existe pero está DEVUELTA o ERROR → reintenta el flujo completo de
      firma y envío con los datos actuales del payload (ej. fecha de hoy),
      reutilizando el mismo comprobante/secuencial/clave de acceso ya reservados.
    - Si no existe → crea uno nuevo desde cero."""
    ESTADOS_DEFINITIVOS_OK = {
        ComprobanteElectronico.AUTORIZADO,
        ComprobanteElectronico.EN_PROCESO,
        ComprobanteElectronico.RECIBIDA,
        ComprobanteElectronico.FIRMADO,
        ComprobanteElectronico.ENVIADO,
    }
    existente = session.exec(
        select(ComprobanteElectronico).where(ComprobanteElectronico.referencia_externa == payload['referencia_externa']),
    ).first()
    if existente is not None:
        if existente.estado in ESTADOS_DEFINITIVOS_OK:
            # Ya está en un estado que no requiere reintento — devolver tal cual.
            return existente
        # Estado DEVUELTA o ERROR: reintentar el envío con el payload actual
        # (que trae fecha_emision = hoy desde el cliente Django) reutilizando
        # el mismo comprobante ya reservado en BD.
        logger.info(
            'Reintentando comprobante %s (estado anterior: %s)',
            existente.referencia_externa, existente.estado,
        )
        return _generar_firmar_y_enviar(session, existente, payload)

    comprobante = _reservar_comprobante(session, payload)
    return _generar_firmar_y_enviar(session, comprobante, payload)



def obtener_por_clave(session: Session, clave_acceso: str) -> ComprobanteElectronico | None:
    return session.exec(
        select(ComprobanteElectronico).where(ComprobanteElectronico.clave_acceso == clave_acceso),
    ).first()


def consultar_estado_sri(session: Session, clave_acceso: str) -> dict:
    """GET /estado-sri/: consulta el SRI EN VIVO (nunca solo lo que ya está
    guardado) — se usa tanto para refrescar un comprobante propio EN_PROCESO
    como para la API pública de verificación por cualquier clave de acceso,
    exista o no en la base de este servicio (ver client.py::consultar_autorizacion,
    que no depende de tener un ComprobanteElectronico previo)."""
    estado, numero_autorizacion, fecha_autorizacion, _xml_autorizado, mensajes = consultar_autorizacion(clave_acceso)

    comprobante = obtener_por_clave(session, clave_acceso)
    if comprobante is not None:
        comprobante.estado = _ESTADOS_SRI.get(estado, ComprobanteElectronico.EN_PROCESO)
        comprobante.numero_autorizacion = numero_autorizacion
        if fecha_autorizacion:
            comprobante.fecha_autorizacion = fecha_autorizacion
        if mensajes:
            comprobante.mensajes = mensajes
        comprobante.actualizado_en = datetime.datetime.now(datetime.timezone.utc)
        session.add(comprobante)
        session.commit()

    return {
        'estado_sri': estado,
        'numero_autorizacion': numero_autorizacion,
        'fecha_autorizacion': fecha_autorizacion.isoformat() if fecha_autorizacion else None,
        'mensajes': mensajes,
    }
