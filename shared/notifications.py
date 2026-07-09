import logging

from django.conf import settings
from django.core.mail import send_mail, EmailMessage

logger = logging.getLogger(__name__)

# Estas funciones son el ÚNICO lugar del proyecto donde se envían
# correos/WhatsApp — cualquier vista que necesite notificar a alguien llama
# a una de estas, nunca arma el envío por su cuenta. Todas devuelven
# True/False y NUNCA dejan que una excepción se escape hacia quien las llamó:
# así, si falla el envío (o falta configurar el .env), la operación principal
# (crear una factura, un usuario, etc.) se completa igual — el correo/WhatsApp
# es un "extra", no algo que deba tumbar el resto del flujo.


def send_credentials_email(to_email, subject, body):
    """Envía un correo simple por SMTP (Gmail, configurado en settings.py). Devuelve True/False."""
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


def send_email_with_attachment(to_email, subject, body, attachment_name, attachment_content, attachment_mimetype='application/pdf'):
    """
    Igual que send_credentials_email, pero con un archivo adjunto (ej. el PDF
    de una factura). send_mail() no soporta adjuntos, por eso acá se usa
    EmailMessage directamente. Devuelve True/False, igual que las demás.
    """
    if not to_email:
        return False
    try:
        email = EmailMessage(subject, body, settings.DEFAULT_FROM_EMAIL, [to_email])
        email.attach(attachment_name, attachment_content, attachment_mimetype)
        email.send(fail_silently=False)
        return True
    except Exception:
        logger.exception('No se pudo enviar el correo con adjunto a %s', to_email)
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
