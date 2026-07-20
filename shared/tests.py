from unittest.mock import Mock, patch

from django.test import TestCase, override_settings

from configuracion.models import EmpresaFacturacionElectronica
from shared.notifications import send_telegram_message, send_whatsapp_message


@override_settings(TELEGRAM_BOT_TOKEN='', TELEGRAM_CHAT_ID='')
class SendTelegramMessageSinConfigurarTests(TestCase):
    def test_devuelve_false_sin_romper_si_falta_configuracion(self):
        self.assertFalse(send_telegram_message('hola'))


@override_settings(TELEGRAM_BOT_TOKEN='123:ABC', TELEGRAM_CHAT_ID='-100123')
class SendTelegramMessageConfiguradoTests(TestCase):
    @patch('shared.notifications.requests.post')
    def test_envia_y_devuelve_true_si_la_api_responde_bien(self, mock_post):
        mock_post.return_value = Mock(status_code=200)
        mock_post.return_value.raise_for_status = Mock()

        resultado = send_telegram_message('Stock bajo: "Mouse" tiene 0 unidades.')

        self.assertTrue(resultado)
        mock_post.assert_called_once()
        url, kwargs = mock_post.call_args[0][0], mock_post.call_args[1]
        self.assertIn('123:ABC', url)
        self.assertEqual(kwargs['json']['chat_id'], '-100123')
        self.assertEqual(kwargs['json']['text'], 'Stock bajo: "Mouse" tiene 0 unidades.')

    @patch('shared.notifications.requests.post', side_effect=Exception('sin conexión'))
    def test_devuelve_false_si_la_llamada_falla(self, mock_post):
        self.assertFalse(send_telegram_message('hola'))


@override_settings(FACTURACION_ELECTRONICA_SERVICE_URL='')
class SendWhatsappMessageSinConfigurarTests(TestCase):
    def test_devuelve_false_sin_romper_si_falta_configuracion(self):
        self.assertFalse(send_whatsapp_message('0991234567', 'hola'))


@override_settings(FACTURACION_ELECTRONICA_SERVICE_URL='http://localhost:8002')
class SendWhatsappMessageSinApiKeyTests(TestCase):
    # La URL puede estar en settings, pero si ninguna empresa está marcada
    # activa=True en Configuración > Facturación Electrónica, sigue
    # considerándose "no configurado".
    def test_devuelve_false_sin_romper_si_falta_la_api_key(self):
        self.assertFalse(send_whatsapp_message('0991234567', 'hola'))


@override_settings(FACTURACION_ELECTRONICA_SERVICE_URL='http://localhost:8002', FACTURACION_ELECTRONICA_SERVICE_TIMEOUT=15)
class SendWhatsappMessageConfiguradoTests(TestCase):
    def setUp(self):
        EmpresaFacturacionElectronica.objects.create(
            ruc='1790000000001', razon_social='TecnoStock S.A.', direccion_matriz='Av. Siempre Viva 123',
            codigo_establecimiento='001', codigo_punto_emision='001',
            empresa_id_microservicio='1', api_key='secretkey', activa=True,
        )

    @patch('shared.notifications.requests.post')
    def test_envia_y_devuelve_true_si_el_microservicio_responde_bien(self, mock_post):
        mock_post.return_value = Mock(status_code=200)

        resultado = send_whatsapp_message('0991234567', 'Confirmación de su pago.')

        self.assertTrue(resultado)
        mock_post.assert_called_once()
        url, kwargs = mock_post.call_args[0][0], mock_post.call_args[1]
        self.assertEqual(url, 'http://localhost:8002/enviar-mensaje-whatsapp')
        self.assertEqual(kwargs['json']['telefono'], '0991234567')
        self.assertEqual(kwargs['json']['texto'], 'Confirmación de su pago.')
        self.assertEqual(kwargs['headers']['Authorization'], 'Bearer secretkey')

    @patch('shared.notifications.requests.post')
    def test_devuelve_false_si_el_microservicio_devuelve_error(self, mock_post):
        mock_post.return_value = Mock(status_code=502, text='Error de Ultramsg')

        resultado = send_whatsapp_message('0991234567', 'hola')

        self.assertFalse(resultado)

    @patch('shared.notifications.requests.post', side_effect=Exception('sin conexión'))
    def test_devuelve_false_si_la_llamada_falla(self, mock_post):
        self.assertFalse(send_whatsapp_message('0991234567', 'hola'))

