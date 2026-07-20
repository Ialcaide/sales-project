"""
El armado del PDF del RIDE vive en el microservicio de facturación
electrónica (GET /facturas/{clave_acceso}/ride), que es quien tiene los
datos completos del comprobante. Acá solo queda pedirle el PDF ya armado —
mismo nombre de función y misma firma (`build_ride_pdf(comprobante)`) que
antes, para que billing/views.py y facturacion_electronica/views.py sigan
llamándolo exactamente igual.
"""
import requests
from django.conf import settings

from .services import SRIError, _headers, _url


def build_ride_pdf(comprobante):
    """Devuelve los bytes del PDF del RIDE. A diferencia del resto de
    services.py (que es "best effort" y nunca lanza), esto SÍ puede lanzar
    SRIError — quien lo llama (el envío de correo en billing/views.py, o el
    botón de descarga en facturacion_electronica/views.py) ya está
    preparado para que un adjunto/descarga falle de forma visible en vez de
    fallar en silencio con un PDF vacío."""
    try:
        response = requests.get(
            _url(f'/facturas/{comprobante.clave_acceso}/ride'), headers=_headers(),
            timeout=settings.FACTURACION_ELECTRONICA_SERVICE_TIMEOUT,
        )
    except requests.RequestException as e:
        raise SRIError(f'No se pudo obtener el RIDE del servicio de facturación electrónica: {e}') from e

    if response.status_code != 200:
        raise SRIError('El servicio de facturación electrónica no pudo generar el RIDE.')

    return response.content
