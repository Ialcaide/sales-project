import logging

from django.conf import settings
from django.core.mail import send_mail

logger = logging.getLogger(__name__)


def send_credentials_email(to_email, subject, body):
    """Envía un correo simple. Devuelve True/False según el resultado."""
    if not to_email:
        return False
    try:
        send_mail(
            subject,
            body,
            settings.DEFAULT_FROM_EMAIL,
            [to_email],
            fail_silently=False,
        )
        return True
    except Exception:
        logger.exception('No se pudo enviar el correo a %s', to_email)
        return False


def send_whatsapp_message(phone, body):
    """Envía un mensaje de WhatsApp vía Twilio. Devuelve True/False según el resultado.

    Si TWILIO_ACCOUNT_SID/AUTH_TOKEN/WHATSAPP_FROM no están configurados, no falla:
    registra un aviso y retorna False para que el resto del flujo continúe.
    """
    if not phone:
        return False
    if not (settings.TWILIO_ACCOUNT_SID and settings.TWILIO_AUTH_TOKEN and settings.TWILIO_WHATSAPP_FROM):
        logger.warning('Twilio no está configurado: se omitió el envío de WhatsApp a %s', phone)
        return False
    try:
        from twilio.rest import Client
        client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)
        client.messages.create(
            from_=settings.TWILIO_WHATSAPP_FROM,
            to=f'whatsapp:{phone}',
            body=body,
        )
        return True
    except Exception:
        logger.exception('No se pudo enviar el WhatsApp a %s', phone)
        return False
