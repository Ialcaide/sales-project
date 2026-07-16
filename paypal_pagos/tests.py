from decimal import Decimal
from unittest.mock import MagicMock, patch

from django.contrib.auth.models import Permission, User
from django.test import TestCase, override_settings
from django.urls import reverse

from billing.models import Brand, Customer, Invoice, Product, ProductGroup
from cobros.models import CobroFactura

from .client import PayPalError, PayPalNoConfiguradoError, capturar_orden, crear_orden, obtener_access_token
from .models import OrdenPaypal
from .services import crear_orden_cobro, crear_orden_venta, finalizar_orden

PAYPAL_SETTINGS = dict(PAYPAL_CLIENT_ID='fake-id', PAYPAL_CLIENT_SECRET='fake-secret', PAYPAL_WEBHOOK_ID='fake-webhook-id')


def mock_response(json_data, status_ok=True):
    resp = MagicMock()
    resp.json.return_value = json_data
    if status_ok:
        resp.raise_for_status.return_value = None
    else:
        import requests
        resp.raise_for_status.side_effect = requests.HTTPError('error')
    return resp


@override_settings(**PAYPAL_SETTINGS)
class ClientTests(TestCase):
    @patch('paypal_pagos.client.requests.post')
    def test_obtener_access_token(self, mock_post):
        mock_post.return_value = mock_response({'access_token': 'tok123'})
        self.assertEqual(obtener_access_token(), 'tok123')

    @override_settings(PAYPAL_CLIENT_ID='', PAYPAL_CLIENT_SECRET='')
    def test_obtener_access_token_sin_configurar(self):
        with self.assertRaises(PayPalNoConfiguradoError):
            obtener_access_token()

    @patch('paypal_pagos.client.requests.post')
    def test_crear_orden_devuelve_id_y_approval_url(self, mock_post):
        mock_post.side_effect = [
            mock_response({'access_token': 'tok123'}),
            mock_response({'id': 'ORDER1', 'links': [{'rel': 'approve', 'href': 'https://paypal.test/approve'}]}),
        ]
        order_id, approval_url = crear_orden(Decimal('10.00'), 'ref1', 'https://x/return', 'https://x/cancel')
        self.assertEqual(order_id, 'ORDER1')
        self.assertEqual(approval_url, 'https://paypal.test/approve')

    @patch('paypal_pagos.client.requests.post')
    def test_crear_orden_sin_link_de_aprobacion_lanza_error(self, mock_post):
        mock_post.side_effect = [
            mock_response({'access_token': 'tok123'}),
            mock_response({'id': 'ORDER1', 'links': []}),
        ]
        with self.assertRaises(PayPalError):
            crear_orden(Decimal('10.00'), 'ref1', 'https://x/return', 'https://x/cancel')

    @patch('paypal_pagos.client.requests.post')
    def test_capturar_orden_devuelve_status(self, mock_post):
        mock_post.side_effect = [
            mock_response({'access_token': 'tok123'}),
            mock_response({'status': 'COMPLETED'}),
        ]
        self.assertEqual(capturar_orden('ORDER1'), 'COMPLETED')

    @patch('paypal_pagos.client.requests.post')
    def test_verificar_firma_webhook_exitosa(self, mock_post):
        from .client import verificar_firma_webhook
        mock_post.side_effect = [
            mock_response({'access_token': 'tok123'}),
            mock_response({'verification_status': 'SUCCESS'}),
        ]
        self.assertTrue(verificar_firma_webhook({}, {'event_type': 'x'}))

    @override_settings(PAYPAL_WEBHOOK_ID='')
    def test_verificar_firma_sin_webhook_id_configurado(self):
        from .client import verificar_firma_webhook
        self.assertFalse(verificar_firma_webhook({}, {}))


@override_settings(**PAYPAL_SETTINGS)
class ServicesTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('paypal_user', password='clave-test-123')
        self.brand = Brand.objects.create(name='Marca PayPal')
        self.group = ProductGroup.objects.create(name='Grupo PayPal')
        self.product = Product.objects.create(
            name='Producto PayPal', brand=self.brand, group=self.group,
            unit_price=Decimal('10.00'), stock=20,
        )
        self.customer = Customer.objects.create(dni='1700000088', first_name='Ana', last_name='Gómez')

    @patch('paypal_pagos.services.crear_orden')
    def test_crear_orden_venta_calcula_monto_con_iva_y_guarda_orden(self, mock_crear):
        mock_crear.return_value = ('ORDER1', 'https://paypal.test/approve')
        datos_venta = {
            'customer_id': self.customer.id, 'tipo_pago': Invoice.CONTADO,
            'lineas': [{'product_id': self.product.id, 'quantity': 2, 'unit_price': '10.00'}],
        }
        orden = crear_orden_venta(datos_venta, self.user)
        self.assertEqual(orden.tipo, OrdenPaypal.VENTA)
        self.assertEqual(orden.monto, Decimal('23.00'))  # 20 subtotal + 15% IVA
        self.assertEqual(orden.paypal_order_id, 'ORDER1')
        self.assertEqual(orden.approval_url, 'https://paypal.test/approve')
        mock_crear.assert_called_once()
        self.assertEqual(mock_crear.call_args.kwargs['monto'], Decimal('23.00'))

    @patch('paypal_pagos.services.crear_orden')
    def test_crear_orden_cobro_guarda_orden(self, mock_crear):
        mock_crear.return_value = ('ORDER2', 'https://paypal.test/approve2')
        invoice = Invoice.objects.create(
            customer=self.customer, total=Decimal('50.00'), saldo=Decimal('50.00'),
            tipo_pago=Invoice.CREDITO, estado=Invoice.PENDIENTE,
        )
        orden = crear_orden_cobro(invoice, Decimal('20.00'), self.user)
        self.assertEqual(orden.tipo, OrdenPaypal.COBRO)
        self.assertEqual(orden.monto, Decimal('20.00'))
        self.assertEqual(orden.payload, {'factura_id': invoice.id})

    @patch('paypal_pagos.services.capturar_orden')
    def test_finalizar_orden_venta_crea_invoice_y_baja_stock(self, mock_capturar):
        mock_capturar.return_value = 'COMPLETED'
        orden = OrdenPaypal.objects.create(
            paypal_order_id='ORDER3', tipo=OrdenPaypal.VENTA, monto=Decimal('23.00'),
            payload={
                'customer_id': self.customer.id, 'tipo_pago': Invoice.CONTADO,
                'lineas': [{'product_id': self.product.id, 'quantity': 2, 'unit_price': '10.00'}],
            },
            creado_por=self.user,
        )
        resultado = finalizar_orden(orden)
        self.assertEqual(resultado.estado, OrdenPaypal.CAPTURADA)
        self.assertIsNotNone(resultado.invoice)
        self.assertEqual(resultado.invoice.total, Decimal('23.00'))
        self.assertEqual(resultado.invoice.forma_pago, Invoice.PAYPAL)
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock, 18)

    @patch('paypal_pagos.services.capturar_orden')
    def test_finalizar_orden_es_idempotente(self, mock_capturar):
        mock_capturar.return_value = 'COMPLETED'
        orden = OrdenPaypal.objects.create(
            paypal_order_id='ORDER4', tipo=OrdenPaypal.VENTA, monto=Decimal('23.00'),
            payload={
                'customer_id': self.customer.id, 'tipo_pago': Invoice.CONTADO,
                'lineas': [{'product_id': self.product.id, 'quantity': 2, 'unit_price': '10.00'}],
            },
            creado_por=self.user,
        )
        finalizar_orden(orden)
        finalizar_orden(orden)  # segunda vez (ej. webhook + return casi simultáneos)
        self.assertEqual(Invoice.objects.filter(customer=self.customer).count(), 1)
        self.assertEqual(mock_capturar.call_count, 1)

    @patch('paypal_pagos.services.capturar_orden')
    def test_finalizar_orden_cobro_crea_cobrofactura(self, mock_capturar):
        mock_capturar.return_value = 'COMPLETED'
        invoice = Invoice.objects.create(
            customer=self.customer, total=Decimal('50.00'), saldo=Decimal('50.00'),
            tipo_pago=Invoice.CREDITO, estado=Invoice.PENDIENTE,
        )
        orden = OrdenPaypal.objects.create(
            paypal_order_id='ORDER5', tipo=OrdenPaypal.COBRO, monto=Decimal('20.00'),
            payload={'factura_id': invoice.id}, creado_por=self.user,
        )
        resultado = finalizar_orden(orden)
        self.assertEqual(resultado.estado, OrdenPaypal.CAPTURADA)
        self.assertIsNotNone(resultado.cobro)
        invoice.refresh_from_db()
        self.assertEqual(invoice.saldo, Decimal('30.00'))
        self.assertEqual(CobroFactura.objects.filter(factura=invoice).count(), 1)
        self.assertEqual(resultado.cobro.forma_pago, CobroFactura.PAYPAL)

    @patch('paypal_pagos.services.capturar_orden')
    def test_finalizar_orden_marca_fallida_si_no_completa(self, mock_capturar):
        mock_capturar.return_value = 'DECLINED'
        orden = OrdenPaypal.objects.create(
            paypal_order_id='ORDER6', tipo=OrdenPaypal.COBRO, monto=Decimal('10.00'),
            payload={'factura_id': 1}, creado_por=self.user,
        )
        resultado = finalizar_orden(orden)
        self.assertEqual(resultado.estado, OrdenPaypal.FALLIDA)

    @patch('paypal_pagos.services.capturar_orden')
    def test_finalizar_orden_marca_fallida_si_paypalerror(self, mock_capturar):
        mock_capturar.side_effect = PayPalError('boom')
        orden = OrdenPaypal.objects.create(
            paypal_order_id='ORDER7', tipo=OrdenPaypal.COBRO, monto=Decimal('10.00'),
            payload={'factura_id': 1}, creado_por=self.user,
        )
        resultado = finalizar_orden(orden)
        self.assertEqual(resultado.estado, OrdenPaypal.FALLIDA)


@override_settings(**PAYPAL_SETTINGS)
class PaypalViewsTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('paypal_view_user', password='clave-test-123')
        self.user.user_permissions.set(Permission.objects.filter(
            codename__in=['view_invoice', 'view_cobrofactura', 'access_cobrofactura_module']
        ))
        self.client.force_login(self.user)
        self.brand = Brand.objects.create(name='Marca PV')
        self.group = ProductGroup.objects.create(name='Grupo PV')
        self.customer = Customer.objects.create(dni='1700000091', first_name='Ana', last_name='Gómez')

    @patch('paypal_pagos.views.finalizar_orden')
    def test_paypal_return_venta_capturada_redirige_a_invoice_detail(self, mock_finalizar):
        invoice = Invoice.objects.create(
            customer=self.customer, total=Decimal('23.00'), saldo=Decimal('0.00'),
            tipo_pago=Invoice.CONTADO, estado=Invoice.PAGADA, forma_pago=Invoice.PAYPAL,
        )
        orden = OrdenPaypal.objects.create(
            paypal_order_id='ORDERX', tipo=OrdenPaypal.VENTA, estado=OrdenPaypal.CAPTURADA,
            monto=Decimal('23.00'), payload={}, creado_por=self.user, invoice=invoice,
        )
        mock_finalizar.return_value = orden
        response = self.client.get(reverse('paypal_pagos:paypal_return'), {'token': 'ORDERX'})
        self.assertRedirects(response, reverse('billing:invoice_detail', args=[invoice.id]))

    @patch('paypal_pagos.views.finalizar_orden')
    def test_paypal_return_fallida_redirige_con_error(self, mock_finalizar):
        orden = OrdenPaypal.objects.create(
            paypal_order_id='ORDERY', tipo=OrdenPaypal.VENTA, estado=OrdenPaypal.FALLIDA,
            monto=Decimal('10.00'), payload={}, creado_por=self.user,
        )
        mock_finalizar.return_value = orden
        response = self.client.get(reverse('paypal_pagos:paypal_return'), {'token': 'ORDERY'})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse('billing:invoice_create'))

    def test_paypal_cancel_marca_cancelada(self):
        orden = OrdenPaypal.objects.create(
            paypal_order_id='ORDERZ', tipo=OrdenPaypal.COBRO, estado=OrdenPaypal.CREADA,
            monto=Decimal('10.00'), payload={'factura_id': 1}, creado_por=self.user,
        )
        response = self.client.get(reverse('paypal_pagos:paypal_cancel'), {'token': 'ORDERZ'})
        orden.refresh_from_db()
        self.assertEqual(orden.estado, OrdenPaypal.CANCELADA)
        self.assertRedirects(response, reverse('cobros:invoice_pending_list'))

    @patch('paypal_pagos.views.finalizar_orden')
    @patch('paypal_pagos.views.verificar_firma_webhook')
    def test_webhook_firma_invalida_devuelve_400(self, mock_verificar, mock_finalizar):
        mock_verificar.return_value = False
        response = self.client.post(
            reverse('paypal_pagos:paypal_webhook'), data='{"event_type": "PAYMENT.CAPTURE.COMPLETED", "resource": {}}',
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 400)
        mock_finalizar.assert_not_called()

    @patch('paypal_pagos.views.finalizar_orden')
    @patch('paypal_pagos.views.verificar_firma_webhook')
    def test_webhook_firma_valida_finaliza_la_orden(self, mock_verificar, mock_finalizar):
        mock_verificar.return_value = True
        OrdenPaypal.objects.create(
            paypal_order_id='ORDERW', tipo=OrdenPaypal.COBRO, estado=OrdenPaypal.CREADA,
            monto=Decimal('10.00'), payload={'factura_id': 1}, creado_por=self.user,
        )
        body = '{"event_type": "PAYMENT.CAPTURE.COMPLETED", "resource": {"id": "CAPTUREID", "supplementary_data": {"related_ids": {"order_id": "ORDERW"}}}}'
        response = self.client.post(reverse('paypal_pagos:paypal_webhook'), data=body, content_type='application/json')
        self.assertEqual(response.status_code, 200)
        mock_finalizar.assert_called_once()

    @patch('paypal_pagos.views.finalizar_orden')
    @patch('paypal_pagos.views.verificar_firma_webhook')
    def test_webhook_evento_irrelevante_no_finaliza(self, mock_verificar, mock_finalizar):
        mock_verificar.return_value = True
        response = self.client.post(
            reverse('paypal_pagos:paypal_webhook'), data='{"event_type": "PAYMENT.CAPTURE.DENIED", "resource": {}}',
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 200)
        mock_finalizar.assert_not_called()
