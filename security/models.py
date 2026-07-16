from django.db import models
from django.contrib.auth.models import User

# El User de Django (django.contrib.auth.models.User) no trae campo de
# teléfono. En vez de reemplazar el User por uno personalizado (invasivo,
# requiere migrar todo el proyecto desde cero), se agrega un modelo aparte
# conectado 1-a-1: cada User puede tener a lo sumo un UserProfile.
# Mismo patrón que Customer/CustomerProfile en billing/models.py.


class UserProfile(models.Model):
    """Datos extendidos del usuario. OneToOne con User."""
    # related_name='profile' permite acceder como user.profile desde cualquier
    # User. Si el usuario no tiene perfil creado, user.profile lanza
    # RelatedObjectDoesNotExist (por eso el código usa getattr(user, 'profile', None)
    # en los lugares donde el perfil es opcional, ej. usuarios creados antes de este cambio).
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    phone = models.CharField(max_length=20, verbose_name='Teléfono / WhatsApp')

    class Meta:
        verbose_name = 'Perfil de Usuario'
        verbose_name_plural = 'Perfiles de Usuario'
        # Botón "Enviar Acceso por WhatsApp" en la lista/detalle de usuarios —
        # abre un link wa.me con el acceso ya redactado, no envía nada
        # automático (ver whatsapp_acceso_url más abajo).
        permissions = [('send_whatsapp_userprofile', 'Puede enviar acceso al sistema por WhatsApp')]

    def __str__(self):
        return f'Perfil: {self.user.username}'

    @property
    def whatsapp_acceso_url(self):
        """
        Link "wa.me" con un mensaje ya redactado recordándole al usuario cómo
        acceder al sistema (URL + su usuario) — al tocarlo se abre WhatsApp
        con el chat de ese usuario y el mensaje listo para enviar (se
        presiona "Enviar" a mano, no se manda nada automático). None si no
        tiene teléfono registrado.
        """
        if not self.phone:
            return None
        from urllib.parse import quote
        from django.conf import settings
        mensaje = (
            f'Hola {self.user.first_name}, este es tu acceso al sistema de TecnoStock S.A.:\n'
            f'{settings.SITE_URL}\n'
            f'Tu usuario es: {self.user.username}\n'
            f'Si no recuerdas tu contraseña, usa la opción "Recuperar credenciales" en la pantalla de inicio de sesión.'
        )
        return f'https://wa.me/{self.phone.lstrip("+")}?text={quote(mensaje)}'
