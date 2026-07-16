"""
facturacion_electronica ya NO firma ni arma XML acá (esa lógica se movió a
sri_facturacion_service, un proyecto Django aparte — ver su propio
comprobantes/tests.py para ClaveAccesoTests/FirmaTests/XmlBuilderTests, que
antes vivían acá). Este archivo prueba lo que SÍ se queda en este proyecto:
- que services.py arme bien el payload y llame al microservicio por HTTP
- que el criterio "best effort" se mantenga (nunca lanza, nunca bloquea la venta)
- que el enganche automático en billing/views.py -> _finalizar_venta siga funcionando
- que la API pública de verificación (views.py -> verificar_autorizacion_api)
  siga funcionando igual, ahora hablándole al microservicio en vez de al SRI directo
"""
import datetime
import json
from unittest.mock import Mock, patch

from django.contrib.auth.models import Permission, User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from billing.models import Brand, Customer, Invoice, InvoiceDetail, Product, ProductGroup
from configuracion.models import ConfiguracionSistema

from .models import ComprobanteElectronico
from .services import SRIError, consultar_autorizacion_publica, generar_y_enviar_comprobante, reintentar


def _mock_response(status_code, json_data=None, text=''):
    resp = Mock()
    resp.status_code = status_code
    resp.json.return_value = json_data or {}
    resp.text = text
    return resp


def _comprobante_json(**overrides):
    """Forma de respuesta que devuelve sri_facturacion_service para un
    comprobante — ver sri_facturacion_service/comprobantes/models.py -> to_dict()."""
    base = {
        'referencia_externa': 'billing.invoice:1',
        'clave_acceso': '1' * 49,
        'tipo_comprobante': '01',
        'establecimiento': '001',
        'punto_emision': '001',
        'secuencial': '000000001',
        'estado': 'generado',
        'ambiente': '1',
        'numero_autorizacion': '',
        'fecha_autorizacion': None,
        'mensajes': [],
        'xml_generado': '<factura/>',
        'xml_firmado': '',
        'xml_autorizado': '',
    }
    base.update(overrides)
    return base


class ServicesHttpClientTests(TestCase):
    """generar_y_enviar_comprobante()/reintentar() nunca deben dejar escapar
    una excepción — se llaman automáticamente justo después de completar una
    venta. requests.post/get SIEMPRE se mockean: estos tests nunca tocan la
    red real ni necesitan sri_facturacion_service levantado."""

    def setUp(self):
        self.config = ConfiguracionSistema.get_solo()
        self.config.empresa_ruc = '1234567890001'
        self.config.save()
        self.brand = Brand.objects.create(name='Marca Services')
        self.group = ProductGroup.objects.create(name='Grupo Services')
        self.product = Product.objects.create(
            name='Producto Services', brand=self.brand, group=self.group, unit_price=10, stock=50,
        )
        self.customer = Customer.objects.create(dni='1700000175', first_name='Luis', last_name='Torres')
        self.invoice = Invoice.objects.create(
            customer=self.customer, subtotal=20, tax=3, total=23,
            tipo_pago=Invoice.CONTADO, forma_pago=Invoice.EFECTIVO, saldo=0,
        )
        InvoiceDetail.objects.create(invoice=self.invoice, product=self.product, quantity=2, unit_price=10)

    @patch('facturacion_electronica.services.requests.post')
    def test_flujo_exitoso_guarda_el_comprobante_local(self, mock_post):
        mock_post.return_value = _mock_response(201, {'comprobante': _comprobante_json(
            referencia_externa=f'billing.invoice:{self.invoice.id}', estado='autorizado', numero_autorizacion='999',
            fecha_autorizacion='2026-07-13T10:00:00+00:00',
        )})

        comprobante = generar_y_enviar_comprobante(self.invoice)

        self.assertIsNotNone(comprobante)
        self.assertEqual(comprobante.estado, ComprobanteElectronico.AUTORIZADO)
        self.assertEqual(comprobante.numero_autorizacion, '999')
        mock_post.assert_called_once()
        # El payload mandado debe traer el emisor/comprador/líneas armados
        # desde ESTE invoice — es la parte que sigue viviendo acá.
        payload_enviado = mock_post.call_args.kwargs['json']
        self.assertEqual(payload_enviado['referencia_externa'], f'billing.invoice:{self.invoice.id}')
        self.assertEqual(payload_enviado['emisor']['ruc'], '1234567890001')
        self.assertEqual(len(payload_enviado['lineas']), 1)

    @patch('facturacion_electronica.services.requests.post')
    def test_error_de_conexion_no_lanza_y_devuelve_none(self, mock_post):
        import requests
        mock_post.side_effect = requests.ConnectionError('No se pudo conectar')

        comprobante = generar_y_enviar_comprobante(self.invoice)  # no debe lanzar

        self.assertIsNone(comprobante)
        self.assertFalse(ComprobanteElectronico.objects.filter(invoice=self.invoice).exists())

    @patch('facturacion_electronica.services.requests.post')
    def test_microservicio_rechaza_el_payload_no_crea_comprobante_ni_lanza(self, mock_post):
        mock_post.return_value = _mock_response(422, text='Establecimiento inválido')

        comprobante = generar_y_enviar_comprobante(self.invoice)  # no debe lanzar

        self.assertIsNone(comprobante)
        self.assertFalse(ComprobanteElectronico.objects.filter(invoice=self.invoice).exists())

    @patch('facturacion_electronica.services.requests.post')
    def test_reintentar_vuelve_a_pedir_el_mismo_invoice(self, mock_post):
        mock_post.return_value = _mock_response(201, {'comprobante': _comprobante_json(
            referencia_externa=f'billing.invoice:{self.invoice.id}', estado='error', mensajes=['SRI caído'],
        )})
        comprobante = generar_y_enviar_comprobante(self.invoice)
        self.assertEqual(comprobante.estado, ComprobanteElectronico.ERROR)

        mock_post.return_value = _mock_response(201, {'comprobante': _comprobante_json(
            referencia_externa=f'billing.invoice:{self.invoice.id}', estado='autorizado', numero_autorizacion='777',
        )})
        self.invoice.refresh_from_db()
        comprobante_reintentado = reintentar(self.invoice)

        self.assertEqual(comprobante_reintentado.estado, ComprobanteElectronico.AUTORIZADO)
        self.assertEqual(comprobante_reintentado.numero_autorizacion, '777')
        self.assertEqual(ComprobanteElectronico.objects.filter(invoice=self.invoice).count(), 1)

    @patch('facturacion_electronica.services.requests.get')
    def test_consultar_autorizacion_publica_sincroniza_comprobante_local(self, mock_get):
        ComprobanteElectronico.objects.create(
            invoice=self.invoice, establecimiento='001', punto_emision='001',
            secuencial='000000001', clave_acceso='1' * 49, estado=ComprobanteElectronico.EN_PROCESO,
        )
        mock_get.return_value = _mock_response(200, {
            'ok': True, 'clave_acceso': '1' * 49, 'estado_sri': 'AUTORIZADO', 'autorizado': True,
            'numero_autorizacion': '555', 'fecha_autorizacion': None, 'mensajes': [],
        })

        estado, numero, fecha, mensajes = consultar_autorizacion_publica('1' * 49)

        self.assertEqual(estado, 'AUTORIZADO')
        self.assertEqual(numero, '555')
        comprobante = ComprobanteElectronico.objects.get(clave_acceso='1' * 49)
        self.assertEqual(comprobante.estado, ComprobanteElectronico.AUTORIZADO)

    @patch('facturacion_electronica.services.requests.get')
    def test_consultar_autorizacion_publica_propaga_sri_error(self, mock_get):
        import requests
        mock_get.side_effect = requests.Timeout('tardó demasiado')

        with self.assertRaises(SRIError):
            consultar_autorizacion_publica('1' * 49)


class InvoiceCreateIntegrationTests(TestCase):
    """Confirma el enganche automático en billing/views.py -> _finalizar_venta:
    la generación del comprobante es 'best effort' — si falla, la venta debe
    completarse igual (nunca debe revertirse ni bloquearse). Acá NO se
    mockea requests: al no haber ningún sri_facturacion_service realmente
    corriendo durante los tests, la llamada HTTP falla por conexión — el
    mismo caso real que "el microservicio está caído", y se comporta igual
    (best effort, no bloquea la venta)."""

    def setUp(self):
        self.brand = Brand.objects.create(name='Marca SRI Hook')
        self.group = ProductGroup.objects.create(name='Grupo SRI Hook')
        self.customer = Customer.objects.create(dni='1700000183', first_name='Ana', last_name='Gómez')
        self.product = Product.objects.create(
            name='Producto SRI Hook', brand=self.brand, group=self.group, unit_price=10, stock=50,
        )
        self.user = User.objects.create_user('vendedor_sri', password='clave-test-123')
        perms = Permission.objects.filter(
            codename__in=['view_invoice', 'add_invoice', 'view_invoicedetail', 'add_invoicedetail']
        )
        self.user.user_permissions.set(perms)
        self.client.force_login(self.user)
        from caja.models import SesionCaja
        SesionCaja.objects.create(usuario=self.user, monto_inicial=100)

    def _post(self):
        data = {
            'customer': self.customer.id, 'tipo_pago': Invoice.CONTADO, 'forma_pago': Invoice.EFECTIVO,
            'monto_recibido': '1000.00',
            'details-TOTAL_FORMS': '1', 'details-INITIAL_FORMS': '0', 'details-MIN_NUM_FORMS': '0', 'details-MAX_NUM_FORMS': '1000',
            'details-0-id': '', 'details-0-product': self.product.id, 'details-0-quantity': '2', 'details-0-unit_price': '10.00',
        }
        return self.client.post(reverse('billing:invoice_create'), data)

    def test_microservicio_no_disponible_no_impide_que_la_venta_se_guarde(self):
        response = self._post()
        self.assertEqual(response.status_code, 302)
        invoice = Invoice.objects.get(customer=self.customer)
        self.assertFalse(hasattr(invoice, 'comprobante_electronico'))

    @patch('facturacion_electronica.services.generar_y_enviar_comprobante')
    def test_venta_normal_dispara_la_generacion_del_comprobante(self, mock_generar):
        response = self._post()
        self.assertEqual(response.status_code, 302)
        mock_generar.assert_called_once()
        invoice_pasada = mock_generar.call_args[0][0]
        self.assertEqual(invoice_pasada.customer_id, self.customer.id)


class VerificarAutorizacionApiTests(TestCase):
    """API de verificación (facturacion_electronica/views.py ->
    verificar_autorizacion_api) — reusable con sesión+permiso o con API key,
    para CUALQUIER clave de acceso (nuestra o no). Ahora habla con
    sri_facturacion_service en vez del SRI directo — se mockea
    requests.get, nunca se toca la red real."""

    CLAVE_VALIDA = '1' * 49
    API_KEY = 'clave-de-prueba-123'

    def setUp(self):
        from django.core.cache import cache
        cache.clear()  # el rate-limit usa el cache — no debe arrastrar estado entre tests

        self.brand = Brand.objects.create(name='Marca API SRI')
        self.group = ProductGroup.objects.create(name='Grupo API SRI')
        self.product = Product.objects.create(
            name='Producto API SRI', brand=self.brand, group=self.group, unit_price=10, stock=50,
        )
        self.customer = Customer.objects.create(dni='1700000182', first_name='Marta', last_name='Ruiz')
        self.invoice = Invoice.objects.create(
            customer=self.customer, subtotal=20, tax=3, total=23,
            tipo_pago=Invoice.CONTADO, forma_pago=Invoice.EFECTIVO, saldo=0,
        )
        InvoiceDetail.objects.create(invoice=self.invoice, product=self.product, quantity=2, unit_price=10)

        self.user = User.objects.create_user('con_permiso_sri', password='clave-test-123')
        self.user.user_permissions.set(
            Permission.objects.filter(codename='view_comprobanteelectronico')
        )

    def _url(self, **params):
        return reverse('facturacion_electronica:verificar_autorizacion_api') + (
            '?' + '&'.join(f'{k}={v}' for k, v in params.items()) if params else ''
        )

    def _mock_estado_sri(self, mock_get, estado_sri='AUTORIZADO', numero='999', mensajes=None):
        mock_get.return_value = _mock_response(200, {
            'ok': True, 'clave_acceso': self.CLAVE_VALIDA, 'estado_sri': estado_sri,
            'autorizado': estado_sri == 'AUTORIZADO', 'numero_autorizacion': numero,
            'fecha_autorizacion': None, 'mensajes': mensajes or [],
        })

    @patch('facturacion_electronica.services.requests.get')
    def test_con_sesion_y_permiso_funciona_sin_api_key(self, mock_get):
        self._mock_estado_sri(mock_get, numero='999')
        self.client.force_login(self.user)

        response = self.client.get(self._url(clave_acceso=self.CLAVE_VALIDA))

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload['ok'])
        self.assertTrue(payload['autorizado'])
        self.assertEqual(payload['numero_autorizacion'], '999')
        mock_get.assert_called_once()

    @patch('facturacion_electronica.services.requests.get')
    def test_con_api_key_correcta_funciona_sin_sesion(self, mock_get):
        self._mock_estado_sri(mock_get, estado_sri='EN PROCESO', numero='')
        with self.settings(SRI_VERIFICACION_API_KEY=self.API_KEY):
            response = self.client.get(
                self._url(clave_acceso=self.CLAVE_VALIDA), headers={'X-API-Key': self.API_KEY}
            )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()['autorizado'])

    def test_sin_sesion_y_sin_api_key_responde_401(self):
        response = self.client.get(self._url(clave_acceso=self.CLAVE_VALIDA))
        self.assertEqual(response.status_code, 401)
        self.assertFalse(response.json()['ok'])

    def test_con_api_key_incorrecta_responde_401(self):
        with self.settings(SRI_VERIFICACION_API_KEY=self.API_KEY):
            response = self.client.get(
                self._url(clave_acceso=self.CLAVE_VALIDA), headers={'X-API-Key': 'clave-equivocada'}
            )
        self.assertEqual(response.status_code, 401)

    def test_clave_acceso_de_largo_incorrecto_responde_400(self):
        self.client.force_login(self.user)
        response = self.client.get(self._url(clave_acceso='123'))
        self.assertEqual(response.status_code, 400)

    def test_clave_acceso_con_letras_responde_400(self):
        self.client.force_login(self.user)
        response = self.client.get(self._url(clave_acceso='a' * 49))
        self.assertEqual(response.status_code, 400)

    @patch('facturacion_electronica.services.requests.get')
    def test_error_de_red_responde_502(self, mock_get):
        import requests
        mock_get.side_effect = requests.Timeout('Timeout al conectar con el SRI')
        self.client.force_login(self.user)

        response = self.client.get(self._url(clave_acceso=self.CLAVE_VALIDA))

        self.assertEqual(response.status_code, 502)
        self.assertFalse(response.json()['ok'])

    @patch('facturacion_electronica.services.requests.get')
    def test_comprobante_local_existente_se_sincroniza(self, mock_get):
        comprobante = ComprobanteElectronico.objects.create(
            invoice=self.invoice, establecimiento='001', punto_emision='001',
            secuencial='000000001', clave_acceso=self.CLAVE_VALIDA, estado=ComprobanteElectronico.EN_PROCESO,
        )
        self._mock_estado_sri(mock_get, numero='555')

        self.client.force_login(self.user)
        response = self.client.get(self._url(clave_acceso=self.CLAVE_VALIDA))

        self.assertEqual(response.status_code, 200)
        comprobante.refresh_from_db()
        self.assertEqual(comprobante.estado, ComprobanteElectronico.AUTORIZADO)
        self.assertEqual(comprobante.numero_autorizacion, '555')
        mock_get.assert_called_once()  # UNA sola llamada HTTP

    @patch('facturacion_electronica.services.requests.get')
    def test_clave_ajena_no_crea_comprobante_local(self, mock_get):
        self._mock_estado_sri(mock_get, numero='777')
        self.client.force_login(self.user)

        response = self.client.get(self._url(clave_acceso=self.CLAVE_VALIDA))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(ComprobanteElectronico.objects.count(), 0)

    @patch('facturacion_electronica.services.requests.get')
    def test_por_invoice_id_resuelve_la_clave(self, mock_get):
        ComprobanteElectronico.objects.create(
            invoice=self.invoice, establecimiento='001', punto_emision='001',
            secuencial='000000001', clave_acceso=self.CLAVE_VALIDA,
        )
        self._mock_estado_sri(mock_get, numero='111')
        self.client.force_login(self.user)

        response = self.client.get(self._url(invoice_id=self.invoice.id))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['clave_acceso'], self.CLAVE_VALIDA)

    def test_invoice_sin_comprobante_responde_400(self):
        self.client.force_login(self.user)
        response = self.client.get(self._url(invoice_id=self.invoice.id))
        self.assertEqual(response.status_code, 400)

    @patch('facturacion_electronica.services.requests.get')
    def test_rate_limit_bloquea_despues_del_maximo(self, mock_get):
        self._mock_estado_sri(mock_get, estado_sri='EN PROCESO', numero='')
        self.client.force_login(self.user)

        from .views import RATE_LIMIT_MAX
        for _ in range(RATE_LIMIT_MAX):
            response = self.client.get(self._url(clave_acceso=self.CLAVE_VALIDA))
            self.assertEqual(response.status_code, 200)

        response_extra = self.client.get(self._url(clave_acceso=self.CLAVE_VALIDA))
        self.assertEqual(response_extra.status_code, 429)
