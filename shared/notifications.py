import logging
from datetime import date

from django.conf import settings
from django.core.mail import send_mail, EmailMultiAlternatives
from django.template.loader import render_to_string

logger = logging.getLogger(__name__)

# Estas funciones son el ÚNICO lugar del proyecto donde se envían
# correos/WhatsApp — cualquier vista que necesite notificar a alguien llama
# a una de estas, nunca arma el envío por su cuenta. Todas devuelven
# True/False y NUNCA dejan que una excepción se escape hacia quien las llamó:
# así, si falla el envío (o falta configurar el .env), la operación principal
# (crear una factura, un usuario, etc.) se completa igual — el correo/WhatsApp
# es un "extra", no algo que deba tumbar el resto del flujo.
#
# HTML opcional (templates/emails/*.html): las 3 funciones de correo aceptan
# `html_template`/`html_context` opcionales. Sin ellos, el correo sale como
# texto plano (comportamiento de siempre, cero cambios para quien no los
# pase). Con ellos, el `body` de texto sigue siendo el mensaje "real" (lo que
# ven los clientes de correo sin soporte HTML, y lo que siguen leyendo los
# tests existentes vía `mail.outbox[0].body`) y la plantilla HTML se adjunta
# como *alternativa* — la mayoría de los clientes de correo van a mostrar la
# versión HTML. Quien llama sigue siendo responsable del CONTENIDO (acá no se
# decide qué dice cada correo, eso vive en cada app); esta función solo sabe
# renderizar y enviar.
#
# html_context NO necesita traer empresa_nombre/site_url/current_year/
# support_email — _contexto_base() ya los agrega siempre.


def _contexto_base(extra=None):
    from configuracion.models import ConfiguracionSistema
    config = ConfiguracionSistema.get_solo()
    context = {
        'empresa_nombre': config.empresa_nombre,
        'site_url': settings.SITE_URL,
        'current_year': date.today().year,
        'support_email': settings.DEFAULT_FROM_EMAIL,
    }
    context.update(extra or {})
    return context


def _adjuntar_html(email, html_template, html_context):
    if not html_template:
        return
    html_body = render_to_string(f'emails/{html_template}', _contexto_base(html_context))
    email.attach_alternative(html_body, 'text/html')


def get_admin_recipients():
    """Usuarios activos con correo cargado que son administradores (mismo
    criterio que security/views.py -> admin_required: superusuario o
    pertenece al grupo 'Administrador') — para los correos que avisan a un
    administrador de un evento (alta de usuario/cliente/proveedor, compra a
    proveedor, stock bajo, etc.). Devuelve una lista de (nombre_completo, email)."""
    from django.contrib.auth.models import User
    from django.db.models import Q

    admins = User.objects.filter(
        Q(is_superuser=True) | Q(groups__name='Administrador'),
        is_active=True,
    ).exclude(email='').distinct()
    return [
        ((f'{a.first_name} {a.last_name}'.strip() or a.username), a.email)
        for a in admins
    ]


def send_credentials_email(to_email, subject, body, html_template=None, html_context=None):
    """Envía un correo por SMTP (Gmail, configurado en settings.py). Devuelve True/False."""
    if not to_email:
        return False
    try:
        if html_template:
            email = EmailMultiAlternatives(subject, body, settings.DEFAULT_FROM_EMAIL, [to_email])
            _adjuntar_html(email, html_template, html_context)
            email.send(fail_silently=False)
        else:
            send_mail(subject, body, settings.DEFAULT_FROM_EMAIL, [to_email], fail_silently=False)
        return True
    except Exception:
        logger.exception('No se pudo enviar el correo a %s', to_email)
        return False


def send_email_with_attachment(
    to_email, subject, body, attachment_name, attachment_content, attachment_mimetype='application/pdf',
    html_template=None, html_context=None,
):
    """
    Igual que send_credentials_email, pero con un archivo adjunto (ej. el PDF
    de una factura). Devuelve True/False, igual que las demás.
    """
    if not to_email:
        return False
    try:
        email = EmailMultiAlternatives(subject, body, settings.DEFAULT_FROM_EMAIL, [to_email])
        _adjuntar_html(email, html_template, html_context)
        email.attach(attachment_name, attachment_content, attachment_mimetype)
        email.send(fail_silently=False)
        return True
    except Exception:
        logger.exception('No se pudo enviar el correo con adjunto a %s', to_email)
        return False


def send_email_with_attachments(to_email, subject, body, attachments, html_template=None, html_context=None):
    """
    Igual que send_email_with_attachment, pero con VARIOS adjuntos (ej. el
    PDF de la factura + el RIDE + el XML autorizado del SRI, ver
    billing/views.py -> _finalizar_venta). `attachments` es una lista de
    tuplas (nombre, contenido, mimetype). Devuelve True/False.
    """
    if not to_email:
        return False
    try:
        email = EmailMultiAlternatives(subject, body, settings.DEFAULT_FROM_EMAIL, [to_email])
        _adjuntar_html(email, html_template, html_context)
        for nombre, contenido, mimetype in attachments:
            email.attach(nombre, contenido, mimetype)
        email.send(fail_silently=False)
        return True
    except Exception:
        logger.exception('No se pudo enviar el correo con adjuntos a %s', to_email)
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
