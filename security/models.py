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

    def __str__(self):
        return f'Perfil: {self.user.username}'
