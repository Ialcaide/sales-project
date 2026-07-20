from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase, override_settings

from billing.models import Brand


@override_settings(TELEGRAM_BOT_TOKEN='123:ABC', TELEGRAM_CHAT_ID='1')
class SignalsAvisanCambiosDeNegocioTests(TestCase):
    """Confirma que el signal global (notificaciones/signals.py) manda a
    Telegram para modelos de apps rastreadas, y no para los que no lo son."""

    @patch('notificaciones.signals.send_telegram_message')
    def test_crear_un_modelo_rastreado_manda_creo(self, mock_telegram):
        Brand.objects.create(name='Nike')
        mock_telegram.assert_called_once()
        mensaje = mock_telegram.call_args[0][0]
        self.assertIn('creó', mensaje)
        self.assertIn('Nike', mensaje)

    @patch('notificaciones.signals.send_telegram_message')
    def test_editar_un_modelo_rastreado_manda_edito(self, mock_telegram):
        brand = Brand.objects.create(name='Nike')
        mock_telegram.reset_mock()
        brand.name = 'Adidas'
        brand.save()
        mock_telegram.assert_called_once()
        self.assertIn('editó', mock_telegram.call_args[0][0])

    @patch('notificaciones.signals.send_telegram_message')
    def test_eliminar_un_modelo_rastreado_manda_elimino(self, mock_telegram):
        brand = Brand.objects.create(name='Nike')
        mock_telegram.reset_mock()
        brand.delete()
        mock_telegram.assert_called_once()
        self.assertIn('eliminó', mock_telegram.call_args[0][0])

    @patch('notificaciones.signals.send_telegram_message')
    def test_crear_usuario_manda_aviso_con_etiqueta_usuario(self, mock_telegram):
        User.objects.create_user(username='jperez', password='x')
        mock_telegram.assert_called_once()
        self.assertIn('Usuario', mock_telegram.call_args[0][0])

    @patch('notificaciones.signals.send_telegram_message')
    def test_login_manda_aviso_con_el_usuario(self, mock_telegram):
        User.objects.create_user(username='jperez', password='clave-segura-123')
        mock_telegram.reset_mock()
        self.client.login(username='jperez', password='clave-segura-123')
        mock_telegram.assert_called_once()
        self.assertIn('jperez', mock_telegram.call_args[0][0])

    @patch('notificaciones.signals.send_telegram_message')
    def test_no_avisa_para_modelos_de_apps_no_rastreadas(self, mock_telegram):
        from django.contrib.contenttypes.models import ContentType
        ContentType.objects.get_or_create(app_label='x', model='y')
        mock_telegram.assert_not_called()


@override_settings(TELEGRAM_BOT_TOKEN='', TELEGRAM_CHAT_ID='')
class SignalsSinTelegramConfiguradoTests(TestCase):
    @patch('notificaciones.signals.send_telegram_message')
    def test_no_llama_a_telegram_si_no_esta_configurado(self, mock_telegram):
        Brand.objects.create(name='Nike')
        mock_telegram.assert_not_called()
