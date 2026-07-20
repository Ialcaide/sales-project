"""
Cliente HTTP del microservicio de facturación electrónica (proyecto aparte,
desplegado en Railway — ver FACTURACION_ELECTRONICA_SERVICE_URL en
config/settings.py). Contrato real confirmado contra su openapi.json:
POST /facturas/ (crear) -> POST /facturas/{clave}/firmar ->
POST /facturas/{clave}/enviar, más GET /facturas/{clave} (consultar),
GET /facturas/{clave}/xml?version=firmado|autorizado, y
GET /facturas/{clave}/ride — NO existe un endpoint único de "generar
comprobante" ni de "estado-sri", hay que encadenar los tres pasos a mano
(ver _procesar_factura).

`generar_y_enviar_comprobante()` sigue sin dejar escapar una excepción NUNCA
(criterio "best effort"): un problema acá (el microservicio caído, mal
configurado, tarda demasiado) no debe revertir ni bloquear la venta ya
completada. `reintentar()`, en cambio, SÍ deja escapar SRIError a propósito
— es un botón manual, el usuario que lo toca espera ver el motivo real si
algo falla (ver facturacion_electronica/views.py -> comprobante_reintentar).
"""
import datetime
import logging

import requests
from django.conf import settings

from .models import ComprobanteElectronico

logger = logging.getLogger(__name__)


class SRIError(Exception):
    """Algo falló al hablar con sri_facturacion_service (red, timeout,
    respuesta con error) — mismo nombre que la excepción que antes vivía en
    client.py (esa lógica se movió al microservicio); se deja el mismo
    nombre acá para que facturacion_electronica/views.py no tenga que
    cambiar su `from . import client` / `client.SRIError`."""


# Traduce forma_pago/tipo_pago de billing.Invoice (un dato de ESTE proyecto)
# al enum FormaPago real del microservicio (POST /facturas/) — decisión de
# negocio confirmada explícitamente: 'tarjeta' siempre se factura como
# tarjeta_credito (mismo criterio que el código SRI 19 que ya se usaba
# antes), 'paypal' como dinero_electronico, y CREDITO (venta a plazos sin
# forma de pago inmediata — la API real no tiene ningún campo de
# plazo/cuotas) se manda igual que efectivo, sin_sistema_financiero.
FORMAS_PAGO_MICROSERVICIO = {
    'efectivo': 'sin_sistema_financiero',
    'tarjeta': 'tarjeta_credito',
    'paypal': 'dinero_electronico',
}

# Identificación estándar del SRI para ventas sin comprador identificado
# (Consumidor Final de mostrador) — ClienteFactura exige SIEMPRE
# identificacion + razon_social, a diferencia del contrato viejo que tenía
# un atajo {'es_consumidor_final': True}.
CONSUMIDOR_FINAL_IDENTIFICACION = '9999999999999'
CONSUMIDOR_FINAL_RAZON_SOCIAL = 'CONSUMIDOR FINAL'


def forma_pago_microservicio(invoice):
    if invoice.tipo_pago == invoice.CREDITO:
        return 'sin_sistema_financiero'
    return FORMAS_PAGO_MICROSERVICIO.get(invoice.forma_pago, 'sin_sistema_financiero')


def _cliente_payload(customer):
    if customer.es_consumidor_final:
        return {
            'tipo_identificacion': 'consumidor_final',
            'identificacion': CONSUMIDOR_FINAL_IDENTIFICACION,
            'razon_social': CONSUMIDOR_FINAL_RAZON_SOCIAL,
        }
    return {
        # Customer.tipo_identificacion ya usa los mismos valores
        # ('cedula'/'ruc'/'pasaporte') que el enum TipoIdentificacionCliente
        # del microservicio — no hace falta traducir.
        'tipo_identificacion': customer.tipo_identificacion,
        'identificacion': customer.dni,
        'razon_social': customer.full_name,
    }


# EstadoFactura (microservicio) -> ComprobanteElectronico.estado (este
# proyecto). 'rechazada' se mapea a NO_AUTORIZADO (el SRI no autorizó el
# comprobante) — RECIBIDA/DEVUELTA/EN_PROCESO ya no los produce ningún
# endpoint real, quedan como choices sin uso.
_ESTADOS_FACTURA = {
    'generada': ComprobanteElectronico.GENERADO,
    'firmada': ComprobanteElectronico.FIRMADO,
    'enviada': ComprobanteElectronico.ENVIADO,
    'autorizada': ComprobanteElectronico.AUTORIZADO,
    'rechazada': ComprobanteElectronico.NO_AUTORIZADO,
    'error': ComprobanteElectronico.ERROR,
}


def _llamar(metodo_http, path, **kwargs):
    """POST/GET genérico contra el microservicio (metodo_http es
    requests.get o requests.post): traduce cualquier falla (de red, o
    status fuera de 200/201) a SRIError con el detalle real, y devuelve el
    JSON ya parseado si todo salió bien. Usado por todo el flujo de
    facturas (_procesar_factura, consultar_autorizacion_*) — crear_empresa/
    subir_certificado/obtener_empresa_actual no lo usan, tienen su propio
    manejo porque no siempre mandan Authorization (crear_empresa) o mandan
    archivos (subir_certificado)."""
    try:
        response = metodo_http(
            _url(path), headers=_headers(), timeout=settings.FACTURACION_ELECTRONICA_SERVICE_TIMEOUT, **kwargs
        )
    except requests.RequestException as e:
        raise SRIError(f'No se pudo contactar al servicio de facturación electrónica: {e}') from e
    if response.status_code not in (200, 201):
        raise SRIError(_error_detalle(response))
    return response.json()


def _obtener_xml(clave_acceso, version):
    """GET /facturas/{clave_acceso}/xml?version=firmado|autorizado — a
    diferencia de ruta_xml_firmado/ruta_xml_autorizado (rutas de
    almacenamiento INTERNAS del microservicio, no accesibles desde acá),
    este endpoint devuelve el XML como texto plano listo para guardar/
    adjuntar (Content-Type: application/xml, NO un JSON envolviendo el
    xml). No crítico: si falla, se loguea y se sigue con el resto del
    flujo — la factura ya avanzó del lado del SRI, perder la copia
    impresa del XML no amerita tratar el reintento entero como fallido."""
    try:
        response = requests.get(
            _url(f'/facturas/{clave_acceso}/xml'), params={'version': version}, headers=_headers(),
            timeout=settings.FACTURACION_ELECTRONICA_SERVICE_TIMEOUT,
        )
    except requests.RequestException:
        logger.exception('No se pudo obtener el XML (%s) de la factura %s', version, clave_acceso)
        return ''
    if response.status_code != 200:
        logger.error(
            'El microservicio respondió %s al pedir el XML (%s) de %s', response.status_code, version, clave_acceso,
        )
        return ''
    return response.text


def _headers():
    from configuracion.models import EmpresaFacturacionElectronica
    empresa = EmpresaFacturacionElectronica.get_activa()
    api_key = empresa.api_key if empresa else ''
    return {
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {api_key}',
    }


def _url(path):
    return f'{settings.FACTURACION_ELECTRONICA_SERVICE_URL.rstrip("/")}{path}'


def _error_detalle(response):
    """Extrae el mensaje de error que manda el microservicio (ej. 'RUC no
    coincide con el certificado', 'Contraseña incorrecta') para mostrárselo
    tal cual al usuario — nunca un genérico "algo salió mal"."""
    try:
        data = response.json()
    except ValueError:
        return response.text or f'El servicio de facturación electrónica respondió con error {response.status_code}.'
    if isinstance(data, dict):
        return data.get('detail') or data.get('error') or data.get('message') or str(data)
    return str(data)


# Traduce el código de ambiente que usa ESTE proyecto (ConfiguracionSistema.
# AMBIENTE_CHOICES, '1'/'2' — mismo código que ya usa ComprobanteElectronico)
# al texto exacto que exige el schema del microservicio, y viceversa (ver
# obtener_empresa_actual/datos_empresa_desde_respuesta, que reciben ese texto
# de vuelta desde GET /empresas/me).
_AMBIENTES_MICROSERVICIO = {'1': 'pruebas', '2': 'produccion'}
_AMBIENTES_LOCAL = {texto: codigo for codigo, texto in _AMBIENTES_MICROSERVICIO.items()}


def crear_empresa(datos):
    """POST /empresas/ — da de alta la empresa/RUC en el microservicio (solo
    la PRIMERA vez que se conecta, ver configuracion/views.py ->
    conectar_facturacion_electronica). Sin api_key todavía (recién se la
    devuelve esta llamada), así que no manda Authorization. Deja escapar
    SRIError con el detalle EXACTO del microservicio (ej. RUC inválido) —
    es un flujo manual disparado desde Configuración, no "best effort".

    `datos` trae las claves "propias" de este proyecto (las mismas que arma
    configuracion/views.py: ruc, razon_social, direccion_matriz,
    establecimiento, punto_emision, ambiente) — acá se adaptan al schema
    EXACTO que espera el microservicio (codigo_establecimiento/
    codigo_punto_emision, ambiente como texto 'pruebas'/'produccion')."""
    payload = {
        'ruc': datos['ruc'],
        'razon_social': datos['razon_social'],
        'direccion_matriz': datos['direccion_matriz'],
        'codigo_establecimiento': datos['establecimiento'],
        'codigo_punto_emision': datos['punto_emision'],
        'ambiente': _AMBIENTES_MICROSERVICIO[datos['ambiente']],
    }
    try:
        response = requests.post(
            _url('/empresas/'), json=payload, timeout=settings.FACTURACION_ELECTRONICA_SERVICE_TIMEOUT,
        )
    except requests.RequestException as e:
        raise SRIError(f'No se pudo contactar al servicio de facturación electrónica: {e}') from e

    if response.status_code not in (200, 201):
        raise SRIError(_error_detalle(response))
    return response.json()


def subir_certificado(empresa_id, api_key, archivo, password):
    """POST /empresas/{id}/certificado — sube el .p12 y su contraseña para
    que el microservicio pueda firmar en nombre de esa empresa. La
    contraseña (y el archivo) viajan SOLO en este request; TecnoStock nunca
    los guarda (ver configuracion/views.py). Deja escapar SRIError con el
    detalle exacto (ej. contraseña incorrecta)."""
    headers = {'Authorization': f'Bearer {api_key}'} if api_key else {}
    try:
        response = requests.post(
            _url(f'/empresas/{empresa_id}/certificado'),
            files={'certificado': (archivo.name, archivo.read(), 'application/x-pkcs12')},
            data={'password': password},
            headers=headers,
            timeout=settings.FACTURACION_ELECTRONICA_SERVICE_TIMEOUT,
        )
    except requests.RequestException as e:
        raise SRIError(f'No se pudo contactar al servicio de facturación electrónica: {e}') from e

    if response.status_code not in (200, 201):
        raise SRIError(_error_detalle(response))
    return response.json()


# Claves "propias" de este proyecto -> claves del schema EmpresaUpdate del
# microservicio, para editar_empresa() (PATCH /empresas/{id}). El RUC NO
# está acá a propósito: no es editable, cambiarlo es dar de alta OTRA
# empresa, no editar esta (ver configuracion/forms.py -> EditarEmpresaActivaForm).
_CAMPOS_EMPRESA_UPDATE = {
    'razon_social': 'razon_social',
    'direccion_matriz': 'direccion_matriz',
    'establecimiento': 'codigo_establecimiento',
    'punto_emision': 'codigo_punto_emision',
}


def editar_empresa(empresa_id, datos):
    """PATCH /empresas/{empresa_id} — actualiza SOLO los campos presentes
    en `datos` (todos opcionales del lado del microservicio): permite tanto
    una edición completa (configuracion/views.py -> editar_empresa_activa)
    como mandar nada más que el ambiente (cambiar_ambiente_empresa_activa).
    Usa la api_key de la empresa ACTIVA (_headers()): esta función es para
    que un admin edite SU PROPIA empresa activa desde Configuración, no
    para editar una empresa arbitraria con una api_key ajena. Deja escapar
    SRIError con el detalle real (ej. datos inválidos)."""
    payload = {
        clave_microservicio: datos[clave_propia]
        for clave_propia, clave_microservicio in _CAMPOS_EMPRESA_UPDATE.items()
        if clave_propia in datos
    }
    if 'ambiente' in datos:
        payload['ambiente'] = _AMBIENTES_MICROSERVICIO[datos['ambiente']]
    return _llamar(requests.patch, f'/empresas/{empresa_id}', json=payload)


def obtener_empresa_actual(api_key):
    """GET /empresas/me — trae los datos de una empresa YA conectada del
    lado del microservicio a partir de su api_key, para engancharla acá SIN
    volver a darla de alta (ver configuracion/views.py ->
    vincular_empresa_existente). Útil cuando la empresa se creó por fuera de
    esta pantalla (ej. por script, directo contra el microservicio). Deja
    escapar SRIError con el detalle real si la api_key es inválida."""
    headers = {'Authorization': f'Bearer {api_key}'} if api_key else {}
    try:
        response = requests.get(
            _url('/empresas/me'), headers=headers, timeout=settings.FACTURACION_ELECTRONICA_SERVICE_TIMEOUT,
        )
    except requests.RequestException as e:
        raise SRIError(f'No se pudo contactar al servicio de facturación electrónica: {e}') from e

    if response.status_code != 200:
        raise SRIError(_error_detalle(response))
    return response.json()


def datos_empresa_desde_respuesta(data):
    """Convierte la respuesta del microservicio (mismas claves que espera
    POST /empresas/: codigo_establecimiento/codigo_punto_emision, ambiente
    como texto) a los campos de EmpresaFacturacionElectronica en este
    proyecto — la traducción inversa de la que hace crear_empresa()."""
    return {
        'ruc': data.get('ruc', ''),
        'razon_social': data.get('razon_social', ''),
        'direccion_matriz': data.get('direccion_matriz', ''),
        'codigo_establecimiento': data.get('codigo_establecimiento', ''),
        'codigo_punto_emision': data.get('codigo_punto_emision', ''),
        'ambiente': _AMBIENTES_LOCAL.get(data.get('ambiente'), '1'),
    }


def _payload_desde_invoice(invoice, config):
    """Arma el FacturaCreate que espera POST /facturas/ a partir de ESTE
    invoice/config. NO lleva bloque "emisor": el microservicio ya sabe qué
    empresa está facturando por la Authorization (api_key) que manda
    _headers() — mandarlo sería redundante, y el schema real ni lo acepta.
    Tampoco lleva subtotal/iva_valor/total: el microservicio los calcula
    solo a partir de cantidad×precio_unitario×porcentaje_iva por línea.

    porcentaje_iva va por línea de producto (así lo exige ProductoFactura),
    pero este proyecto no tiene una tarifa de IVA por producto — se manda
    el único porcentaje que sí existe (config.iva_porcentaje, global) en
    cada línea."""
    iva_porcentaje = int(config.iva_porcentaje)
    productos = [
        {
            'descripcion': detail.product.name,
            'cantidad': str(detail.quantity),
            'precio_unitario': str(detail.unit_price),
            'porcentaje_iva': iva_porcentaje,
        }
        for detail in invoice.details.all()
    ]

    return {
        'cliente': _cliente_payload(invoice.customer),
        # Se usa la fecha ACTUAL (hoy) en lugar de invoice.invoice_date porque
        # el SRI exige que el comprobante electrónico se emita el mismo día en
        # que se envía al web service (error 65: FECHA EMISIÓN EXTEMPORÁNEA si
        # la fecha es de un día anterior). La fecha impresa en el RIDE sigue
        # siendo la fecha original de la factura en billing.Invoice.
        'fecha_emision': datetime.date.today().isoformat(),
        'productos': productos,
        'forma_pago': forma_pago_microservicio(invoice),
    }


def _guardar_local(invoice, clave_acceso, data, empresa):
    """Crea/actualiza el ComprobanteElectronico LOCAL con lo último que
    devolvió el microservicio — FacturaRead al crear (trae 'xml', el sin
    firmar) o FacturaEstadoRead al firmar/enviar/consultar (trae
    ruta_xml_firmado/ruta_xml_autorizado, NO el contenido: se pide aparte
    con _obtener_xml). Sigue existiendo acá porque invoice_detail.html y
    los botones de reintentar/consultar leen este modelo directo, nunca le
    preguntan al microservicio en cada render."""
    from django.utils.dateparse import parse_datetime

    estado = _ESTADOS_FACTURA.get(data.get('estado'), ComprobanteElectronico.ERROR)
    defaults = {
        'clave_acceso': clave_acceso,
        'estado': estado,
        'secuencial': data.get('secuencial', ''),
        'numero_autorizacion': data.get('numero_autorizacion') or '',
        'mensajes': [data['mensaje_error']] if data.get('mensaje_error') else [],
    }
    if empresa is not None:
        defaults['establecimiento'] = empresa.codigo_establecimiento
        defaults['punto_emision'] = empresa.codigo_punto_emision
        defaults['ambiente'] = empresa.ambiente

    fecha_autorizacion_sri = data.get('fecha_autorizacion_sri')
    if fecha_autorizacion_sri:
        defaults['fecha_autorizacion'] = parse_datetime(fecha_autorizacion_sri)

    if 'xml' in data:  # viene de FacturaRead (recién creada, XML sin firmar)
        defaults['xml_generado'] = data['xml']
    if data.get('ruta_xml_firmado'):
        defaults['xml_firmado'] = _obtener_xml(clave_acceso, 'firmado')
    if data.get('ruta_xml_autorizado'):
        defaults['xml_autorizado'] = _obtener_xml(clave_acceso, 'autorizado')

    comprobante, _creado = ComprobanteElectronico.objects.update_or_create(
        invoice=invoice, defaults=defaults,
    )
    return comprobante


def _procesar_factura(invoice, config):
    """Punto de entrada COMPARTIDO por generar_y_enviar_comprobante() y
    reintentar(): crea la factura en el microservicio si hace falta
    (POST /facturas/), y la avanza (firmar -> enviar) todo lo que el
    estado REAL permita en esta pasada — nunca vuelve a crear una factura
    que ya existe del otro lado, ni asume que el estado local sigue
    vigente: si ya hay clave_acceso, primero consulta GET /facturas/{clave}
    para saber desde dónde retomar. Deja escapar SRIError (nunca
    requests.RequestException directo: _llamar ya lo traduce) — cada
    caller decide si lo absorbe (best effort) o lo deja escapar (manual)."""
    from configuracion.models import EmpresaFacturacionElectronica
    empresa = EmpresaFacturacionElectronica.get_activa()

    comprobante_previo = getattr(invoice, 'comprobante_electronico', None)
    clave_acceso = comprobante_previo.clave_acceso if comprobante_previo else ''

    if not clave_acceso:
        payload = _payload_desde_invoice(invoice, config)
        data = _llamar(requests.post, '/facturas/', json=payload)
        clave_acceso = data.get('clave_acceso')
        if not clave_acceso:
            raise SRIError('El microservicio no devolvió el clave_acceso al crear la factura.')
    else:
        data = _llamar(requests.get, f'/facturas/{clave_acceso}')

    comprobante = _guardar_local(invoice, clave_acceso, data, empresa)

    if comprobante.estado == ComprobanteElectronico.GENERADO:
        data = _llamar(requests.post, f'/facturas/{clave_acceso}/firmar')
        comprobante = _guardar_local(invoice, clave_acceso, data, empresa)

    if comprobante.estado == ComprobanteElectronico.FIRMADO:
        data = _llamar(requests.post, f'/facturas/{clave_acceso}/enviar')
        comprobante = _guardar_local(invoice, clave_acceso, data, empresa)

    return comprobante


def generar_y_enviar_comprobante(invoice):
    """Punto de entrada automático (se llama justo después de completar una
    venta, ver billing/views.py -> _finalizar_venta). Devuelve el
    ComprobanteElectronico en el estado al que se logró llegar en esta
    pasada, o None si no se pudo avanzar nada (microservicio caído, mal
    configurado, o algo que el propio microservicio rechazó) — "best
    effort": un problema acá NUNCA debe revertir ni bloquear la venta ya
    completada, así que acá SÍ se atrapa cualquier excepción, no solo
    SRIError (una falla inesperada tampoco debe tumbar la venta)."""
    comprobante = getattr(invoice, 'comprobante_electronico', None)
    if comprobante is not None:
        return comprobante

    from configuracion.models import ConfiguracionSistema
    config = ConfiguracionSistema.get_solo()

    try:
        return _procesar_factura(invoice, config)
    except Exception:
        logger.exception('No se pudo generar/avanzar el comprobante de la factura #%s', invoice.id)
        return None


def reintentar(invoice):
    """Vuelve a intentar el flujo para una factura sin comprobante, o cuyo
    comprobante quedó a medias (GENERADO/FIRMADO: se cortó entre pasos) o
    en un estado fallido (ERROR/NO_AUTORIZADO) — usado por el botón manual
    'Reintentar generación'. _procesar_factura ya retoma desde el estado
    REAL en el microservicio, nunca duplica la creación. A diferencia de la
    generación automática, ACÁ SÍ se deja escapar SRIError: es un botón
    manual, el usuario que lo toca espera ver el motivo si algo falla."""
    comprobante = getattr(invoice, 'comprobante_electronico', None)
    ESTADOS_REINTENTABLES = {
        ComprobanteElectronico.GENERADO, ComprobanteElectronico.FIRMADO,
        ComprobanteElectronico.ERROR, ComprobanteElectronico.NO_AUTORIZADO,
    }
    if comprobante is not None and comprobante.estado not in ESTADOS_REINTENTABLES:
        return comprobante

    from configuracion.models import ConfiguracionSistema
    config = ConfiguracionSistema.get_solo()
    return _procesar_factura(invoice, config)


def consultar_autorizacion_manual(comprobante):
    """Botón manual 'Consultar autorización' (para cuando la factura quedó
    ENVIADO esperando resolución del SRI) — nunca deja escapar una
    excepción."""
    from configuracion.models import EmpresaFacturacionElectronica
    empresa = EmpresaFacturacionElectronica.get_activa()
    try:
        data = _llamar(requests.get, f'/facturas/{comprobante.clave_acceso}')
    except SRIError as e:
        _marcar_error_local(comprobante, str(e))
        return comprobante

    return _guardar_local(comprobante.invoice, comprobante.clave_acceso, data, empresa)


def _marcar_error_local(comprobante, mensaje):
    comprobante.estado = ComprobanteElectronico.ERROR
    comprobante.mensajes = (comprobante.mensajes or []) + [mensaje]
    comprobante.save(update_fields=['estado', 'mensajes'])


def consultar_autorizacion_publica(clave_acceso):
    """Punto de entrada de la API de verificación
    (facturacion_electronica/views.py -> verificar_autorizacion_api):
    consulta el estado REAL en el microservicio (GET /facturas/{clave}) por
    CUALQUIER clave de acceso, exista o no un ComprobanteElectronico local
    para ella. Deja escapar SRIError — la vista decide el status HTTP (502)
    según su propio criterio, no es "best effort" como el resto de este
    módulo. Devuelve el `estado` TAL CUAL lo manda el microservicio
    (generada/firmada/enviada/autorizada/rechazada/error, no el choice
    interno de ComprobanteElectronico) — es el contrato público de esta
    función, ver verificar_autorizacion_api."""
    data = _llamar(requests.get, f'/facturas/{clave_acceso}')

    from django.utils.dateparse import parse_datetime
    fecha_autorizacion_sri = data.get('fecha_autorizacion_sri')
    fecha_autorizacion = parse_datetime(fecha_autorizacion_sri) if fecha_autorizacion_sri else None
    mensajes = [data['mensaje_error']] if data.get('mensaje_error') else []

    comprobante = ComprobanteElectronico.objects.filter(clave_acceso=clave_acceso).first()
    if comprobante is not None:
        from configuracion.models import EmpresaFacturacionElectronica
        empresa = EmpresaFacturacionElectronica.get_activa()
        _guardar_local(comprobante.invoice, clave_acceso, data, empresa)

    return data.get('estado'), data.get('numero_autorizacion') or '', fecha_autorizacion, mensajes


def enviar_ride_whatsapp(comprobante, telefono, nombre_cliente, pdf_bytes):
    """Le pide a sri_facturacion_service que mande el RIDE (ya descargado
    acá por el caller, ver facturacion_electronica/ride.py ->
    build_ride_pdf) al cliente por WhatsApp con un saludo — a diferencia de
    send_whatsapp_message (Twilio, solo texto), este camino SÍ entrega el
    PDF adjunto, vía Ultramsg (ver sri_facturacion_service/whatsapp_client.py).
    Deja escapar SRIError: es un botón manual, el usuario que lo toca
    espera ver si funcionó o no, no es "best effort" silencioso como el
    envío automático de correo/WhatsApp de _finalizar_venta."""
    import base64

    payload = {
        'telefono': telefono,
        'nombre_cliente': nombre_cliente,
        'factura_pdf_base64': base64.b64encode(pdf_bytes).decode('ascii'),
        'nombre_archivo': f'ride_{comprobante.clave_acceso}.pdf',
        'caption': 'Factura electrónica autorizada por el SRI.',
    }
    try:
        response = requests.post(
            _url('/enviar-factura-whatsapp'), json=payload, headers=_headers(),
            timeout=settings.FACTURACION_ELECTRONICA_SERVICE_TIMEOUT,
        )
    except requests.RequestException as e:
        raise SRIError(f'No se pudo contactar al servicio de facturación electrónica: {e}') from e

    if response.status_code != 200:
        detalle = response.json().get('detail', 'No se pudo enviar la factura por WhatsApp.')
        raise SRIError(detalle)
    return response.json()
