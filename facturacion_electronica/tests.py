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
from configuracion.models import ConfiguracionSistema, EmpresaFacturacionElectronica

from .models import ComprobanteElectronico
from .services import (
    SRIError, consultar_autorizacion_publica, enviar_ride_whatsapp, generar_y_enviar_comprobante, reintentar,
)


def _mock_response(status_code, json_data=None, text=''):
    resp = Mock()
    resp.status_code = status_code
    resp.json.return_value = json_data or {}
    resp.text = text or json.dumps(json_data or {})
    return resp


def _factura_read(**overrides):
    """Forma real de la respuesta de POST /facturas/ (FacturaRead) — ver
    openapi.json del microservicio."""
    base = {
        'clave_acceso': '1' * 49,
        'secuencial': '000000001',
        'estado': 'generada',
        'fecha_emision': '2026-07-19',
        'ruta_xml_sin_firmar': 's3://facturas/1/sin_firmar.xml',
        'xml': '<factura>sin firmar</factura>',
    }
    base.update(overrides)
    return base


def _factura_estado_read(**overrides):
    """Forma real de la respuesta de POST /facturas/{clave}/firmar,
    POST /facturas/{clave}/enviar y GET /facturas/{clave} (todas devuelven
    FacturaEstadoRead) — ver openapi.json del microservicio."""
    base = {
        'clave_acceso': '1' * 49,
        'secuencial': '000000001',
        'estado': 'firmada',
        'ruta_xml_sin_firmar': 's3://facturas/1/sin_firmar.xml',
        'ruta_xml_firmado': None,
        'ruta_xml_autorizado': None,
        'numero_autorizacion': None,
        'fecha_autorizacion_sri': None,
        'intentos_envio': 0,
        'mensaje_error': None,
        'fecha_creacion': '2026-07-19T10:00:00+00:00',
        'fecha_actualizacion': '2026-07-19T10:00:00+00:00',
    }
    base.update(overrides)
    return base


class ServicesHttpClientTests(TestCase):
    """generar_y_enviar_comprobante()/reintentar() contra el contrato REAL
    del microservicio: POST /facturas/ (crear) -> POST /facturas/{clave}/
    firmar -> POST /facturas/{clave}/enviar (ver _procesar_factura en
    services.py). generar_y_enviar_comprobante() nunca debe dejar escapar
    una excepción (se llama automáticamente justo después de completar una
    venta); reintentar() SÍ la deja escapar (es manual). requests.post/get
    SIEMPRE se mockean: estos tests nunca tocan la red real."""

    def setUp(self):
        self.config = ConfiguracionSistema.get_solo()
        self.config.iva_porcentaje = 15
        self.config.save()
        self.empresa_activa = EmpresaFacturacionElectronica.objects.create(
            ruc='1234567890001', razon_social='Empresa Activa Services', direccion_matriz='Dirección Services',
            codigo_establecimiento='001', codigo_punto_emision='001',
            empresa_id_microservicio='1', api_key='clave-services', activa=True,
        )
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

    @patch('facturacion_electronica.services.requests.get')
    @patch('facturacion_electronica.services.requests.post')
    def test_flujo_exitoso_encadena_crear_firmar_enviar_y_guarda_el_comprobante_local(self, mock_post, mock_get):
        mock_post.side_effect = [
            _mock_response(201, _factura_read(estado='generada')),
            _mock_response(200, _factura_estado_read(estado='firmada', ruta_xml_firmado='s3://.../firmado.xml')),
            _mock_response(200, _factura_estado_read(
                estado='autorizada', ruta_xml_firmado='s3://.../firmado.xml',
                ruta_xml_autorizado='s3://.../autorizado.xml', numero_autorizacion='999',
                fecha_autorizacion_sri='2026-07-19T10:00:00+00:00',
            )),
        ]
        mock_get.return_value = _mock_response(200, text='<factura>firmada o autorizada</factura>')

        comprobante = generar_y_enviar_comprobante(self.invoice)

        self.assertIsNotNone(comprobante)
        self.assertEqual(comprobante.estado, ComprobanteElectronico.AUTORIZADO)
        self.assertEqual(comprobante.numero_autorizacion, '999')
        self.assertEqual(comprobante.xml_generado, '<factura>sin firmar</factura>')
        self.assertEqual(comprobante.xml_firmado, '<factura>firmada o autorizada</factura>')
        self.assertEqual(comprobante.xml_autorizado, '<factura>firmada o autorizada</factura>')
        # Las 3 llamadas: crear, firmar, enviar.
        self.assertEqual(mock_post.call_count, 3)
        crear_url = mock_post.call_args_list[0][0][0]
        firmar_url = mock_post.call_args_list[1][0][0]
        enviar_url = mock_post.call_args_list[2][0][0]
        self.assertTrue(crear_url.endswith('/facturas/'))
        self.assertTrue(firmar_url.endswith(f'/facturas/{comprobante.clave_acceso}/firmar'))
        self.assertTrue(enviar_url.endswith(f'/facturas/{comprobante.clave_acceso}/enviar'))
        # Se guardan también establecimiento/punto_emision/ambiente de la
        # empresa ACTIVA (el microservicio ya no los devuelve).
        self.assertEqual(comprobante.establecimiento, '001')
        self.assertEqual(comprobante.ambiente, '1')

    @patch('facturacion_electronica.services.requests.post')
    def test_el_payload_de_creacion_no_lleva_bloque_emisor(self, mock_post):
        # El microservicio real (FacturaCreate) no acepta un bloque emisor:
        # identifica la empresa por la Authorization (api_key).
        mock_post.return_value = _mock_response(201, _factura_read(estado='generada'))

        generar_y_enviar_comprobante(self.invoice)

        payload = mock_post.call_args_list[0].kwargs['json']
        self.assertNotIn('emisor', payload)
        self.assertEqual(set(payload.keys()), {'cliente', 'fecha_emision', 'productos', 'forma_pago'})
        self.assertEqual(len(payload['productos']), 1)
        self.assertEqual(payload['productos'][0]['porcentaje_iva'], 15)

    @patch('facturacion_electronica.services.requests.post')
    def test_forma_pago_tarjeta_se_manda_como_tarjeta_credito(self, mock_post):
        self.invoice.forma_pago = Invoice.TARJETA
        self.invoice.save()
        mock_post.return_value = _mock_response(201, _factura_read(estado='generada'))

        generar_y_enviar_comprobante(self.invoice)

        self.assertEqual(mock_post.call_args_list[0].kwargs['json']['forma_pago'], 'tarjeta_credito')

    @patch('facturacion_electronica.services.requests.post')
    def test_forma_pago_paypal_se_manda_como_dinero_electronico(self, mock_post):
        self.invoice.forma_pago = Invoice.PAYPAL
        self.invoice.save()
        mock_post.return_value = _mock_response(201, _factura_read(estado='generada'))

        generar_y_enviar_comprobante(self.invoice)

        self.assertEqual(mock_post.call_args_list[0].kwargs['json']['forma_pago'], 'dinero_electronico')

    @patch('facturacion_electronica.services.requests.post')
    def test_venta_a_credito_se_manda_como_sin_sistema_financiero(self, mock_post):
        self.invoice.tipo_pago = Invoice.CREDITO
        self.invoice.forma_pago = None
        self.invoice.estado = Invoice.PENDIENTE
        self.invoice.meses_credito = 3
        self.invoice.saldo = self.invoice.total
        self.invoice.save()
        mock_post.return_value = _mock_response(201, _factura_read(estado='generada'))

        generar_y_enviar_comprobante(self.invoice)

        self.assertEqual(mock_post.call_args_list[0].kwargs['json']['forma_pago'], 'sin_sistema_financiero')

    @patch('facturacion_electronica.services.requests.post')
    def test_consumidor_final_se_manda_con_la_identificacion_estandar_del_sri(self, mock_post):
        consumidor_final = Customer.get_or_create_consumidor_final()
        self.invoice.customer = consumidor_final
        self.invoice.save()
        mock_post.return_value = _mock_response(201, _factura_read(estado='generada'))

        generar_y_enviar_comprobante(self.invoice)

        cliente = mock_post.call_args_list[0].kwargs['json']['cliente']
        self.assertEqual(cliente, {
            'tipo_identificacion': 'consumidor_final', 'identificacion': '9999999999999',
            'razon_social': 'CONSUMIDOR FINAL',
        })

    @patch('facturacion_electronica.services.requests.post')
    def test_error_de_conexion_no_lanza_y_devuelve_none(self, mock_post):
        import requests
        mock_post.side_effect = requests.ConnectionError('No se pudo conectar')

        comprobante = generar_y_enviar_comprobante(self.invoice)  # no debe lanzar

        self.assertIsNone(comprobante)
        self.assertFalse(ComprobanteElectronico.objects.filter(invoice=self.invoice).exists())

    @patch('facturacion_electronica.services.requests.post')
    def test_microservicio_rechaza_la_creacion_no_crea_comprobante_ni_lanza(self, mock_post):
        mock_post.return_value = _mock_response(422, {'detail': 'Producto inválido'})

        comprobante = generar_y_enviar_comprobante(self.invoice)  # no debe lanzar

        self.assertIsNone(comprobante)
        self.assertFalse(ComprobanteElectronico.objects.filter(invoice=self.invoice).exists())

    @patch('facturacion_electronica.services.requests.post')
    def test_reintentar_con_factura_ya_creada_no_vuelve_a_crearla(self, mock_post):
        # La factura quedó en 'generada' (se cortó antes de firmar) —
        # reintentar debe consultar su estado real y retomar desde firmar,
        # NUNCA volver a llamar POST /facturas/ (duplicaría la factura).
        ComprobanteElectronico.objects.create(
            invoice=self.invoice, establecimiento='001', punto_emision='001', secuencial='000000001',
            clave_acceso='1' * 49, estado=ComprobanteElectronico.GENERADO,
        )
        # firmar -> enviar en la misma pasada (comportamiento correcto de
        # _procesar_factura: sigue avanzando todo lo que pueda).
        mock_post.side_effect = [
            _mock_response(200, _factura_estado_read(estado='firmada')),
            _mock_response(200, _factura_estado_read(estado='enviada')),
        ]
        with patch('facturacion_electronica.services.requests.get') as mock_get:
            mock_get.return_value = _mock_response(200, _factura_estado_read(estado='generada'))
            comprobante = reintentar(self.invoice)

        self.assertEqual(comprobante.estado, ComprobanteElectronico.ENVIADO)
        # firmar, luego enviar — nunca se volvió a llamar POST /facturas/
        # (eso duplicaría la factura del lado del microservicio).
        urls_post = [llamada[0][0] for llamada in mock_post.call_args_list]
        self.assertEqual(len(urls_post), 2)
        self.assertTrue(urls_post[0].endswith('/firmar'))
        self.assertTrue(urls_post[1].endswith('/enviar'))
        self.assertFalse(any(url.endswith('/facturas/') for url in urls_post))

    @patch('facturacion_electronica.services.requests.post')
    def test_reintentar_deja_escapar_srierror_con_el_mensaje_real(self, mock_post):
        mock_post.return_value = _mock_response(422, {'detail': 'Establecimiento inválido'})

        with self.assertRaises(SRIError) as ctx:
            reintentar(self.invoice)
        self.assertEqual(str(ctx.exception), 'Establecimiento inválido')
        self.assertFalse(ComprobanteElectronico.objects.filter(invoice=self.invoice).exists())

    @patch('facturacion_electronica.services.requests.get')
    def test_consultar_autorizacion_publica_sincroniza_comprobante_local(self, mock_get):
        ComprobanteElectronico.objects.create(
            invoice=self.invoice, establecimiento='001', punto_emision='001',
            secuencial='000000001', clave_acceso='1' * 49, estado=ComprobanteElectronico.ENVIADO,
        )
        mock_get.return_value = _mock_response(200, _factura_estado_read(
            estado='autorizada', numero_autorizacion='555',
        ))

        estado, numero, fecha, mensajes = consultar_autorizacion_publica('1' * 49)

        # Devuelve el estado TAL CUAL lo manda el microservicio (texto real,
        # no el choice interno) — es el contrato de esta función.
        self.assertEqual(estado, 'autorizada')
        self.assertEqual(numero, '555')
        comprobante = ComprobanteElectronico.objects.get(clave_acceso='1' * 49)
        self.assertEqual(comprobante.estado, ComprobanteElectronico.AUTORIZADO)

    @patch('facturacion_electronica.services.requests.get')
    def test_consultar_autorizacion_publica_propaga_sri_error(self, mock_get):
        import requests
        mock_get.side_effect = requests.Timeout('tardó demasiado')

        with self.assertRaises(SRIError):
            consultar_autorizacion_publica('1' * 49)

    @patch('facturacion_electronica.services.requests.post')
    def test_enviar_ride_whatsapp_exitoso(self, mock_post):
        comprobante = ComprobanteElectronico.objects.create(
            invoice=self.invoice, establecimiento='001', punto_emision='001',
            secuencial='000000001', clave_acceso='1' * 49, estado=ComprobanteElectronico.AUTORIZADO,
        )
        mock_post.return_value = _mock_response(200, {'ok': True, 'resultado': {'id': 'MSG1'}})

        resultado = enviar_ride_whatsapp(comprobante, '0991234567', 'Luis Torres', b'%PDF-contenido')

        self.assertEqual(resultado['ok'], True)
        mock_post.assert_called_once()
        payload_enviado = mock_post.call_args.kwargs['json']
        self.assertEqual(payload_enviado['telefono'], '0991234567')
        self.assertEqual(payload_enviado['nombre_cliente'], 'Luis Torres')
        self.assertIn(comprobante.clave_acceso, payload_enviado['nombre_archivo'])

    @patch('facturacion_electronica.services.requests.post')
    def test_enviar_ride_whatsapp_error_del_microservicio_lanza_sri_error(self, mock_post):
        comprobante = ComprobanteElectronico.objects.create(
            invoice=self.invoice, establecimiento='001', punto_emision='001',
            secuencial='000000001', clave_acceso='1' * 49, estado=ComprobanteElectronico.AUTORIZADO,
        )
        mock_post.return_value = _mock_response(502, {'detail': 'Ultramsg no responde'})

        with self.assertRaises(SRIError):
            enviar_ride_whatsapp(comprobante, '0991234567', 'Luis Torres', b'%PDF-contenido')

    @patch('facturacion_electronica.services.requests.post')
    def test_enviar_ride_whatsapp_error_de_conexion_lanza_sri_error(self, mock_post):
        import requests
        comprobante = ComprobanteElectronico.objects.create(
            invoice=self.invoice, establecimiento='001', punto_emision='001',
            secuencial='000000001', clave_acceso='1' * 49, estado=ComprobanteElectronico.AUTORIZADO,
        )
        mock_post.side_effect = requests.ConnectionError('no se pudo conectar')

        with self.assertRaises(SRIError):
            enviar_ride_whatsapp(comprobante, '0991234567', 'Luis Torres', b'%PDF-contenido')


class ComprobanteReintentarViewTests(TestCase):
    """Botón 'Reintentar generación' (facturacion_electronica/views.py ->
    comprobante_reintentar) — regresión del bug reportado: reintentar()
    deja escapar SRIError a propósito, y la vista tiene que atraparlo y
    mostrar un mensaje legible, NUNCA dejarlo escapar como un 500."""

    def setUp(self):
        self.brand = Brand.objects.create(name='Marca Reintentar')
        self.group = ProductGroup.objects.create(name='Grupo Reintentar')
        self.product = Product.objects.create(
            name='Producto Reintentar', brand=self.brand, group=self.group, unit_price=10, stock=50,
        )
        self.customer = Customer.objects.create(dni='1700000216', first_name='Diego', last_name='Salas')
        self.invoice = Invoice.objects.create(
            customer=self.customer, subtotal=20, tax=3, total=23,
            tipo_pago=Invoice.CONTADO, forma_pago=Invoice.EFECTIVO, saldo=0,
        )
        InvoiceDetail.objects.create(invoice=self.invoice, product=self.product, quantity=2, unit_price=10)
        self.user = User.objects.create_user('vendedor_reintentar', password='clave-test-123')
        self.user.user_permissions.set(Permission.objects.filter(
            codename__in=['add_comprobanteelectronico', 'view_invoice']
        ))
        self.client.force_login(self.user)

    def _url(self):
        return reverse('facturacion_electronica:comprobante_reintentar', args=[self.invoice.id])

    @patch('facturacion_electronica.views.reintentar')
    def test_error_del_microservicio_muestra_mensaje_en_vez_de_reventar_con_500(self, mock_reintentar):
        # Esto es EXACTAMENTE lo que reportó el bug: el microservicio
        # responde 404 (endpoint viejo/inexistente, o factura no
        # encontrada), reintentar() lo traduce a SRIError, y antes la vista
        # no lo atrapaba — terminaba en un 500 sin mensaje para el usuario.
        mock_reintentar.side_effect = SRIError(
            'sri_facturacion_service respondió 404 al reintentar la factura #105: {"detail":"Not Found"}'
        )

        response = self.client.get(self._url(), follow=True)

        self.assertEqual(response.status_code, 200)  # nunca 500
        self.assertContains(response, 'Not Found')

    @patch('facturacion_electronica.views.reintentar')
    def test_exito_muestra_mensaje_de_autorizado(self, mock_reintentar):
        comprobante = ComprobanteElectronico.objects.create(
            invoice=self.invoice, establecimiento='001', punto_emision='001', secuencial='000000001',
            clave_acceso='1' * 49, estado=ComprobanteElectronico.AUTORIZADO, numero_autorizacion='123456',
        )
        mock_reintentar.return_value = comprobante

        response = self.client.get(self._url(), follow=True)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '123456')

    @patch('facturacion_electronica.views.reintentar')
    def test_estado_no_autorizado_muestra_el_ultimo_mensaje(self, mock_reintentar):
        comprobante = ComprobanteElectronico.objects.create(
            invoice=self.invoice, establecimiento='001', punto_emision='001', secuencial='000000001',
            clave_acceso='1' * 49, estado=ComprobanteElectronico.NO_AUTORIZADO,
            mensajes=['Primer intento', 'RUC del comprador inválido'],
        )
        mock_reintentar.return_value = comprobante

        response = self.client.get(self._url(), follow=True)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'RUC del comprador inválido')

    def test_usuario_sin_permiso_es_redirigido(self):
        self.user.user_permissions.clear()
        response = self.client.get(self._url())
        self.assertEqual(response.status_code, 302)


class ComprobanteEnviarWhatsappViewTests(TestCase):
    def setUp(self):
        self.brand = Brand.objects.create(name='Marca WA')
        self.group = ProductGroup.objects.create(name='Grupo WA')
        self.product = Product.objects.create(
            name='Producto WA', brand=self.brand, group=self.group, unit_price=10, stock=50,
        )
        self.customer = Customer.objects.create(
            dni='1700000199', first_name='Sara', last_name='Vera', phone='0991234567',
        )
        self.invoice = Invoice.objects.create(
            customer=self.customer, subtotal=20, tax=3, total=23,
            tipo_pago=Invoice.CONTADO, forma_pago=Invoice.EFECTIVO, saldo=0,
        )
        InvoiceDetail.objects.create(invoice=self.invoice, product=self.product, quantity=2, unit_price=10)
        self.comprobante = ComprobanteElectronico.objects.create(
            invoice=self.invoice, establecimiento='001', punto_emision='001',
            secuencial='000000001', clave_acceso='1' * 49, estado=ComprobanteElectronico.AUTORIZADO,
        )
        self.user = User.objects.create_user('vendedor_wa', password='clave-test-123')
        self.user.user_permissions.set(Permission.objects.filter(
            codename__in=['view_comprobanteelectronico', 'view_invoice']
        ))
        self.client.force_login(self.user)

    @patch('facturacion_electronica.views.enviar_ride_whatsapp')
    @patch('facturacion_electronica.ride.build_ride_pdf')
    def test_envio_exitoso_redirige_con_mensaje(self, mock_build_ride, mock_enviar):
        mock_build_ride.return_value = b'%PDF-contenido'
        mock_enviar.return_value = {'ok': True}

        url = reverse('facturacion_electronica:comprobante_enviar_whatsapp', args=[self.comprobante.pk])
        response = self.client.get(url)

        self.assertRedirects(response, reverse('billing:invoice_detail', args=[self.invoice.pk]))
        mock_enviar.assert_called_once_with(self.comprobante, '0991234567', 'Sara Vera', b'%PDF-contenido')

    def test_sin_telefono_muestra_error_y_no_llama_a_nada(self):
        self.customer.phone = ''
        self.customer.save()
        url = reverse('facturacion_electronica:comprobante_enviar_whatsapp', args=[self.comprobante.pk])
        response = self.client.get(url)
        self.assertRedirects(response, reverse('billing:invoice_detail', args=[self.invoice.pk]))
        messages = [str(m) for m in response.wsgi_request._messages]
        self.assertTrue(any('teléfono' in m for m in messages))

    @patch('facturacion_electronica.views.enviar_ride_whatsapp')
    @patch('facturacion_electronica.ride.build_ride_pdf')
    def test_error_del_servicio_muestra_mensaje(self, mock_build_ride, mock_enviar):
        mock_build_ride.return_value = b'%PDF-contenido'
        mock_enviar.side_effect = SRIError('Ultramsg no responde')

        url = reverse('facturacion_electronica:comprobante_enviar_whatsapp', args=[self.comprobante.pk])
        response = self.client.get(url, follow=True)
        self.assertContains(response, 'Ultramsg no responde')


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
    para CUALQUIER clave de acceso (nuestra o no). Habla con
    GET /facturas/{clave} del microservicio — se mockea requests.get, nunca
    se toca la red real."""

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

    def _mock_estado_sri(self, mock_get, estado_sri='autorizada', numero='999', mensajes=None):
        mock_get.return_value = _mock_response(200, _factura_estado_read(
            clave_acceso=self.CLAVE_VALIDA, estado=estado_sri, numero_autorizacion=numero or None,
            mensaje_error=(mensajes or [None])[-1],
        ))

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
        self._mock_estado_sri(mock_get, estado_sri='enviada', numero='')
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
            secuencial='000000001', clave_acceso=self.CLAVE_VALIDA, estado=ComprobanteElectronico.ENVIADO,
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
        self._mock_estado_sri(mock_get, estado_sri='enviada', numero='')
        self.client.force_login(self.user)

        from .views import RATE_LIMIT_MAX
        for _ in range(RATE_LIMIT_MAX):
            response = self.client.get(self._url(clave_acceso=self.CLAVE_VALIDA))
            self.assertEqual(response.status_code, 200)

        response_extra = self.client.get(self._url(clave_acceso=self.CLAVE_VALIDA))
        self.assertEqual(response_extra.status_code, 429)


class CrearEmpresaYSubirCertificadoTests(TestCase):
    """crear_empresa()/subir_certificado() — llamadas al microservicio
    disparadas desde Configuración > Facturación Electrónica (ver
    configuracion/views.py -> conectar_facturacion_electronica). A
    diferencia de generar_y_enviar_comprobante(), estas SÍ dejan escapar
    SRIError: es un flujo manual, el usuario necesita ver el error real."""

    def _archivo(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        return SimpleUploadedFile('firma.p12', b'contenido-binario-falso')

    def _datos_empresa(self, **overrides):
        datos = {
            'ruc': '1790000000001', 'razon_social': 'TecnoStock S.A.',
            'direccion_matriz': 'Av. Siempre Viva 123', 'establecimiento': '001',
            'punto_emision': '001', 'ambiente': '1',
        }
        datos.update(overrides)
        return datos

    @patch('facturacion_electronica.services.requests.post')
    def test_crear_empresa_traduce_las_claves_y_el_ambiente_al_schema_del_microservicio(self, mock_post):
        from .services import crear_empresa

        mock_post.return_value = _mock_response(201, {'id': 42, 'api_key': 'clave-generada'})
        datos = {
            'ruc': '1790000000001', 'razon_social': 'TecnoStock S.A.',
            'direccion_matriz': 'Av. Siempre Viva 123', 'establecimiento': '001',
            'punto_emision': '001', 'ambiente': '1',
        }

        resultado = crear_empresa(datos)

        self.assertEqual(resultado, {'id': 42, 'api_key': 'clave-generada'})
        mock_post.assert_called_once()
        _url_llamada, kwargs = mock_post.call_args[0][0], mock_post.call_args[1]
        self.assertTrue(_url_llamada.endswith('/empresas/'))
        # El microservicio espera "codigo_establecimiento"/"codigo_punto_emision"
        # (no "establecimiento"/"punto_emision") y "ambiente" como texto.
        self.assertEqual(kwargs['json'], {
            'ruc': '1790000000001', 'razon_social': 'TecnoStock S.A.',
            'direccion_matriz': 'Av. Siempre Viva 123',
            'codigo_establecimiento': '001', 'codigo_punto_emision': '001',
            'ambiente': 'pruebas',
        })

    @patch('facturacion_electronica.services.requests.post')
    def test_crear_empresa_traduce_ambiente_produccion(self, mock_post):
        from .services import crear_empresa

        mock_post.return_value = _mock_response(201, {'id': 42, 'api_key': 'clave-generada'})

        crear_empresa({
            'ruc': '1790000000001', 'razon_social': 'TecnoStock S.A.',
            'direccion_matriz': 'Av. Siempre Viva 123', 'establecimiento': '001',
            'punto_emision': '001', 'ambiente': '2',
        })

        kwargs = mock_post.call_args[1]
        self.assertEqual(kwargs['json']['ambiente'], 'produccion')

    @patch('facturacion_electronica.services.requests.post')
    def test_crear_empresa_con_ruc_invalido_deja_escapar_srierror_con_el_mensaje_real(self, mock_post):
        from .services import crear_empresa

        mock_post.return_value = _mock_response(422, {'detail': 'El RUC no coincide con el certificado.'})

        with self.assertRaises(SRIError) as ctx:
            crear_empresa(self._datos_empresa(ruc='0000000000001'))
        self.assertEqual(str(ctx.exception), 'El RUC no coincide con el certificado.')

    @patch('facturacion_electronica.services.requests.post')
    def test_crear_empresa_sin_conexion_lanza_srierror(self, mock_post):
        import requests
        from .services import crear_empresa

        mock_post.side_effect = requests.ConnectionError('No se pudo conectar')

        with self.assertRaises(SRIError):
            crear_empresa(self._datos_empresa())

    @patch('facturacion_electronica.services.requests.post')
    def test_subir_certificado_manda_el_archivo_la_password_y_el_bearer(self, mock_post):
        from .services import subir_certificado

        mock_post.return_value = _mock_response(200, {'ok': True})
        archivo = self._archivo()

        resultado = subir_certificado('42', 'clave-generada', archivo, 'password-del-p12')

        self.assertEqual(resultado, {'ok': True})
        mock_post.assert_called_once()
        _url_llamada, kwargs = mock_post.call_args[0][0], mock_post.call_args[1]
        self.assertTrue(_url_llamada.endswith('/empresas/42/certificado'))
        self.assertEqual(kwargs['data'], {'password': 'password-del-p12'})
        self.assertEqual(kwargs['files']['certificado'][0], 'firma.p12')
        self.assertEqual(kwargs['headers']['Authorization'], 'Bearer clave-generada')

    @patch('facturacion_electronica.services.requests.post')
    def test_subir_certificado_con_password_incorrecta_deja_escapar_srierror_con_el_mensaje_real(self, mock_post):
        from .services import subir_certificado

        mock_post.return_value = _mock_response(400, {'detail': 'Contraseña de certificado incorrecta.'})

        with self.assertRaises(SRIError) as ctx:
            subir_certificado('42', 'clave-generada', self._archivo(), 'password-mala')
        self.assertEqual(str(ctx.exception), 'Contraseña de certificado incorrecta.')


class EditarEmpresaTests(TestCase):
    """editar_empresa() — PATCH /empresas/{id} (Configuración > Facturación
    Electrónica: 'Editar datos' y 'Cambiar de ambiente'). Usa la api_key de
    la empresa ACTIVA (_headers()), por eso hace falta una en setUp."""

    def setUp(self):
        EmpresaFacturacionElectronica.objects.create(
            ruc='1790000000001', razon_social='TecnoStock S.A.', direccion_matriz='Av. Siempre Viva 123',
            codigo_establecimiento='001', codigo_punto_emision='001',
            empresa_id_microservicio='42', api_key='clave-activa', activa=True,
        )

    @patch('facturacion_electronica.services.requests.patch')
    def test_editar_empresa_manda_los_campos_traducidos_y_el_bearer(self, mock_patch):
        from .services import editar_empresa

        mock_patch.return_value = _mock_response(200, {
            'id': 42, 'ruc': '1790000000001', 'razon_social': 'Nuevo Nombre',
            'direccion_matriz': 'Nueva dirección', 'codigo_establecimiento': '002',
            'codigo_punto_emision': '002', 'ambiente': 'produccion', 'secuencial_factura': 5,
        })

        resultado = editar_empresa('42', {
            'razon_social': 'Nuevo Nombre', 'direccion_matriz': 'Nueva dirección',
            'establecimiento': '002', 'punto_emision': '002', 'ambiente': '2',
        })

        self.assertEqual(resultado['razon_social'], 'Nuevo Nombre')
        mock_patch.assert_called_once()
        _url_llamada, kwargs = mock_patch.call_args[0][0], mock_patch.call_args[1]
        self.assertTrue(_url_llamada.endswith('/empresas/42'))
        self.assertEqual(kwargs['json'], {
            'razon_social': 'Nuevo Nombre', 'direccion_matriz': 'Nueva dirección',
            'codigo_establecimiento': '002', 'codigo_punto_emision': '002', 'ambiente': 'produccion',
        })
        self.assertEqual(kwargs['headers']['Authorization'], 'Bearer clave-activa')

    @patch('facturacion_electronica.services.requests.patch')
    def test_editar_empresa_manda_solo_el_ambiente_cuando_es_lo_unico_presente(self, mock_patch):
        # Caso 'Cambiar de ambiente': el payload NO debe traer razon_social/
        # direccion_matriz/etc, solo lo que realmente cambió.
        from .services import editar_empresa

        mock_patch.return_value = _mock_response(200, {'id': 42, 'ambiente': 'produccion'})

        editar_empresa('42', {'ambiente': '2'})

        self.assertEqual(mock_patch.call_args[1]['json'], {'ambiente': 'produccion'})

    @patch('facturacion_electronica.services.requests.patch')
    def test_editar_empresa_con_datos_invalidos_deja_escapar_srierror_con_el_mensaje_real(self, mock_patch):
        from .services import editar_empresa

        mock_patch.return_value = _mock_response(422, {'detail': 'Código de establecimiento inválido.'})

        with self.assertRaises(SRIError) as ctx:
            editar_empresa('42', {'establecimiento': 'xx'})
        self.assertEqual(str(ctx.exception), 'Código de establecimiento inválido.')

    @patch('facturacion_electronica.services.requests.patch')
    def test_editar_empresa_sin_conexion_deja_escapar_srierror(self, mock_patch):
        import requests
        from .services import editar_empresa

        mock_patch.side_effect = requests.ConnectionError('No se pudo conectar')

        with self.assertRaises(SRIError):
            editar_empresa('42', {'ambiente': '1'})


class ObtenerEmpresaActualTests(TestCase):
    """obtener_empresa_actual()/datos_empresa_desde_respuesta() — flujo "Ya
    tengo una empresa conectada" (configuracion/views.py ->
    vincular_empresa_existente), para empresas dadas de alta fuera de esta
    pantalla (ej. por script) que solo se enganchan con su api_key."""

    @patch('facturacion_electronica.services.requests.get')
    def test_obtener_empresa_actual_manda_el_bearer_y_devuelve_la_respuesta(self, mock_get):
        from .services import obtener_empresa_actual

        mock_get.return_value = _mock_response(200, {
            'id': 5, 'ruc': '1756927560001', 'razon_social': 'Mi Empresa Real',
            'direccion_matriz': 'Av. Real 123', 'codigo_establecimiento': '001',
            'codigo_punto_emision': '001', 'ambiente': 'produccion',
        })

        resultado = obtener_empresa_actual('clave-existente')

        self.assertEqual(resultado['ruc'], '1756927560001')
        mock_get.assert_called_once()
        _url_llamada, kwargs = mock_get.call_args[0][0], mock_get.call_args[1]
        self.assertTrue(_url_llamada.endswith('/empresas/me'))
        self.assertEqual(kwargs['headers']['Authorization'], 'Bearer clave-existente')

    @patch('facturacion_electronica.services.requests.get')
    def test_api_key_invalida_deja_escapar_srierror_con_el_mensaje_real(self, mock_get):
        from .services import obtener_empresa_actual

        mock_get.return_value = _mock_response(401, {'detail': 'Api key inválida.'})

        with self.assertRaises(SRIError) as ctx:
            obtener_empresa_actual('clave-mala')
        self.assertEqual(str(ctx.exception), 'Api key inválida.')

    def test_datos_empresa_desde_respuesta_traduce_ambiente_y_claves(self):
        from .services import datos_empresa_desde_respuesta

        campos = datos_empresa_desde_respuesta({
            'id': 5, 'ruc': '1756927560001', 'razon_social': 'Mi Empresa Real',
            'direccion_matriz': 'Av. Real 123', 'codigo_establecimiento': '001',
            'codigo_punto_emision': '001', 'ambiente': 'produccion',
        })

        self.assertEqual(campos, {
            'ruc': '1756927560001', 'razon_social': 'Mi Empresa Real',
            'direccion_matriz': 'Av. Real 123', 'codigo_establecimiento': '001',
            'codigo_punto_emision': '001', 'ambiente': '2',
        })
