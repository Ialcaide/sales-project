from django.db import models
from django.contrib.auth.models import User


class UserProfile(models.Model):
    """Datos extendidos del usuario. OneToOne con User."""
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    phone = models.CharField(max_length=20, verbose_name='Teléfono / WhatsApp')

    class Meta:
        verbose_name = 'Perfil de Usuario'
        verbose_name_plural = 'Perfiles de Usuario'

    def __str__(self):
        return f'Perfil: {self.user.username}'
