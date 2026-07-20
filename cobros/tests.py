from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth.models import Permission, User
from django.core import mail
from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from billing.models import Customer, Invoice
from caja.models import MovimientoCaja, SesionCaja

from .forms import CobroFacturaForm
from .models import CobroFactura

# Invoice.invoice_date es auto_now_add, así que cada factura creada en un
# test queda fechada "hoy" (el día real en que corre el test). Los cobros
# que pasan por el FORMULARIO deben fecharse desde ese día en adelante (ver
# CobroFacturaForm.clean_fecha en cobros/forms.py) — por eso los tests que
# usan el form (no CobroFactura.objects.create() directo) usan HOY en vez de
# una fecha fija que podría quedar en el pasado.
HOY = timezone.now().date().isoformat()


def make_invoice(saldo='115.00', total='115.00', tipo_pago=Invoice.CREDITO,
                  estado=Invoice.PENDIENTE, is_active=True, meses_credito=None):
    # dni es único en Customer, así que cada llamada necesita uno distinto
    # (varios tests crean más de una factura/cliente en el mismo caso).
    dni = f'{Customer.objects.count():010d}'
    customer = Customer.objects.create(dni=dni, first_name='Juan', last_name='Pérez')
    return Invoice.objects.create(
        customer=customer,
        subtotal=Decimal('100.00'),
        tax=Decimal('15.00'),
        total=Decimal(total),
        tipo_pago=tipo_pago,
        saldo=Decimal(saldo),
        estado=estado,
        is_active=is_active,
        meses_credito=meses_credito,
    )


class CobroFacturaModelTests(TestCase):
    def setUp(self):
        self.factura = make_invoice()

    def test_cobro_parcial_actualiza_saldo_y_mantiene_pendiente(self):
        cobro = CobroFactura.objects.create(factura=self.factura, fecha='2026-07-01', valor=Decimal('50.00'))
        self.factura.refresh_from_db()
        self.assertEqual(self.factura.saldo, Decimal('65.00'))
        self.assertEqual(self.factura.estado, Invoice.PENDIENTE)
        self.assertTrue(CobroFactura.objects.filter(pk=cobro.pk).exists())

    def test_cobro_que_salda_el_total_marca_pagada(self):
        CobroFactura.objects.create(factura=self.factura, fecha='2026-07-01', valor=Decimal('115.00'))
        self.factura.refresh_from_db()
        self.assertEqual(self.factura.saldo, Decimal('0.00'))
        self.assertEqual(self.factura.estado, Invoice.PAGADA)

    def test_cobro_mayor_al_saldo_es_rechazado(self):
        with self.assertRaises(ValidationError):
            CobroFactura.objects.create(factura=self.factura, fecha='2026-07-01', valor=Decimal('200.00'))
        self.factura.refresh_from_db()
        self.assertEqual(self.factura.saldo, Decimal('115.00'))

    def test_cobro_negativo_rechazado_por_full_clean(self):
        cobro = CobroFactura(factura=self.factura, fecha='2026-07-01', valor=Decimal('-10.00'))
        with self.assertRaises(ValidationError):
            cobro.full_clean()

    def test_cobro_en_cero_rechazado_por_full_clean(self):
        cobro = CobroFactura(factura=self.factura, fecha='2026-07-01', valor=Decimal('0.00'))
        with self.assertRaises(ValidationError):
            cobro.full_clean()

    def test_editar_cobro_recalcula_saldo_por_el_delta(self):
        cobro = CobroFactura.objects.create(factura=self.factura, fecha='2026-07-01', valor=Decimal('50.00'))
        cobro.valor = Decimal('80.00')
        cobro.save()
        self.factura.refresh_from_db()
        self.assertEqual(self.factura.saldo, Decimal('35.00'))
        self.assertEqual(self.factura.estado, Invoice.PENDIENTE)

    def test_eliminar_cobro_devuelve_el_saldo(self):
        cobro = CobroFactura.objects.create(factura=self.factura, fecha='2026-07-01', valor=Decimal('50.00'))
        cobro.delete()
        self.factura.refresh_from_db()
        self.assertEqual(self.factura.saldo, Decimal('115.00'))
        self.assertEqual(self.factura.estado, Invoice.PENDIENTE)

    def test_no_se_puede_eliminar_cobro_de_factura_cancelada(self):
        cobro = CobroFactura.objects.create(factura=self.factura, fecha='2026-07-01', valor=Decimal('115.00'))
        self.factura.refresh_from_db()
        self.assertEqual(self.factura.estado, Invoice.PAGADA)
        with self.assertRaises(ValidationError):
            cobro.delete()
        self.assertTrue(CobroFactura.objects.filter(pk=cobro.pk).exists())

    def test_no_se_puede_cobrar_una_factura_anulada(self):
        factura_anulada = make_invoice(is_active=False)
        with self.assertRaises(ValidationError):
            CobroFactura.objects.create(factura=factura_anulada, fecha='2026-07-01', valor=Decimal('10.00'))


class CobroFacturaFormTests(TestCase):
    def setUp(self):
        self.factura = make_invoice(saldo='100.00', total='100.00')

    def test_form_valido_con_valor_dentro_del_saldo(self):
        form = CobroFacturaForm(
            data={'fecha': HOY, 'valor': '50.00', 'monto_recibido': '50.00', 'observacion': ''},
            factura=self.factura,
        )
        self.assertTrue(form.is_valid())

    def test_form_invalido_con_valor_mayor_al_saldo(self):
        form = CobroFacturaForm(
            data={'fecha': '2026-07-01', 'valor': '150.00', 'observacion': ''},
            factura=self.factura,
        )
        self.assertFalse(form.is_valid())
        self.assertIn('valor', form.errors)

    def test_form_invalido_con_valor_cero_o_negativo(self):
        for valor in ('0', '-5'):
            form = CobroFacturaForm(
                data={'fecha': '2026-07-01', 'valor': valor, 'observacion': ''},
                factura=self.factura,
            )
            self.assertFalse(form.is_valid())
            self.assertIn('valor', form.errors)

    def test_editar_permite_mantener_el_mismo_valor(self):
        cobro = CobroFactura.objects.create(factura=self.factura, fecha=HOY, valor=Decimal('40.00'))
        self.factura.refresh_from_db()
        form = CobroFacturaForm(
            data={'fecha': HOY, 'valor': '40.00', 'monto_recibido': '40.00', 'observacion': ''},
            instance=cobro,
            factura=self.factura,
        )
        self.assertTrue(form.is_valid())

    def test_form_invalido_si_la_factura_esta_anulada(self):
        factura_anulada = make_invoice(is_active=False)
        form = CobroFacturaForm(
            data={'fecha': '2026-07-01', 'valor': '10.00', 'observacion': ''},
            factura=factura_anulada,
        )
        self.assertFalse(form.is_valid())

    def test_tarjeta_sin_titular_es_invalido(self):
        # clean() valida titular/cvv/expiración en orden y corta en la
        # primera que falle (mismo criterio que InvoiceForm.clean()).
        form = CobroFacturaForm(
            data={'fecha': HOY, 'valor': '50.00', 'forma_pago': 'tarjeta', 'observacion': ''},
            factura=self.factura,
        )
        self.assertFalse(form.is_valid())
        self.assertIn('tarjeta_titular', form.errors)

    def test_tarjeta_sin_cvv_es_invalido(self):
        form = CobroFacturaForm(
            data={
                'fecha': HOY, 'valor': '50.00', 'forma_pago': 'tarjeta', 'observacion': '',
                'tarjeta_titular': 'Ana Gómez',
            },
            factura=self.factura,
        )
        self.assertFalse(form.is_valid())
        self.assertIn('tarjeta_cvv', form.errors)

    def test_tarjeta_sin_expiracion_es_invalido(self):
        form = CobroFacturaForm(
            data={
                'fecha': HOY, 'valor': '50.00', 'forma_pago': 'tarjeta', 'observacion': '',
                'tarjeta_titular': 'Ana Gómez', 'tarjeta_cvv': '456',
            },
            factura=self.factura,
        )
        self.assertFalse(form.is_valid())
        self.assertIn('tarjeta_expiracion', form.errors)

    def test_tarjeta_con_todos_los_datos_es_valido(self):
        form = CobroFacturaForm(
            data={
                'fecha': HOY, 'valor': '50.00', 'forma_pago': 'tarjeta', 'observacion': '',
                'tarjeta_titular': 'Ana Gómez', 'tarjeta_cvv': '456', 'tarjeta_expiracion': '2030-01-01',
            },
            factura=self.factura,
        )
        self.assertTrue(form.is_valid())

    def test_tarjeta_no_exige_monto_recibido(self):
        form = CobroFacturaForm(
            data={
                'fecha': HOY, 'valor': '50.00', 'forma_pago': 'tarjeta', 'observacion': '',
                'tarjeta_titular': 'Ana Gómez', 'tarjeta_cvv': '456', 'tarjeta_expiracion': '2030-01-01',
            },
            factura=self.factura,
        )
        self.assertTrue(form.is_valid())
        self.assertIsNone(form.cleaned_data.get('monto_recibido'))


class CobroFacturaFechaTests(TestCase):
    """El cobro no puede fecharse antes de que la factura existiera."""

    def setUp(self):
        self.factura = make_invoice(saldo='100.00', total='100.00')

    def test_fecha_anterior_a_la_factura_es_invalida(self):
        from datetime import timedelta
        ayer = (self.factura.invoice_date.date() - timedelta(days=1)).isoformat()
        form = CobroFacturaForm(
            data={'fecha': ayer, 'valor': '50.00', 'observacion': ''},
            factura=self.factura,
        )
        self.assertFalse(form.is_valid())
        self.assertIn('fecha', form.errors)

    def test_fecha_igual_a_la_de_la_factura_es_valida(self):
        form = CobroFacturaForm(
            data={'fecha': self.factura.invoice_date.date().isoformat(), 'valor': '50.00', 'monto_recibido': '50.00', 'observacion': ''},
            factura=self.factura,
        )
        self.assertTrue(form.is_valid())

    def test_fecha_posterior_a_la_factura_es_valida(self):
        from datetime import timedelta
        despues = (self.factura.invoice_date.date() + timedelta(days=5)).isoformat()
        form = CobroFacturaForm(
            data={'fecha': despues, 'valor': '50.00', 'monto_recibido': '50.00', 'observacion': ''},
            factura=self.factura,
        )
        self.assertTrue(form.is_valid())

    def test_editar_ignora_la_fecha_enviada_y_mantiene_la_original(self):
        from datetime import timedelta
        original_fecha = self.factura.invoice_date.date()
        cobro = CobroFactura.objects.create(factura=self.factura, fecha=original_fecha, valor=Decimal('40.00'))
        otra_fecha = (original_fecha + timedelta(days=2)).isoformat()
        form = CobroFacturaForm(
            data={'fecha': otra_fecha, 'valor': '40.00', 'monto_recibido': '40.00', 'observacion': 'corregido'},
            instance=cobro,
            factura=self.factura,
        )
        self.assertTrue(form.is_valid())
        guardado = form.save()
        self.assertEqual(guardado.fecha, original_fecha)


class CobroFacturaViewTests(TestCase):
    def setUp(self):
        self.factura = make_invoice(saldo='100.00', total='100.00')
        self.user = User.objects.create_user('vendedor', password='clave-test-123')
        perms = Permission.objects.filter(
            codename__in=['view_cobrofactura', 'add_cobrofactura', 'change_cobrofactura', 'delete_cobrofactura',
                           'access_cobrofactura_module', 'view_invoice']
        )
        self.user.user_permissions.set(perms)
        self.client.force_login(self.user)
        # Un cobro en EFECTIVO (el default de CobroFacturaForm cuando no se
        # elige nada) ahora exige una caja abierta — ver
        # CobroFacturaCajaIntegrationTests más abajo para el caso sin caja.
        SesionCaja.objects.create(usuario=self.user, monto_inicial=Decimal('100.00'))

    def test_lista_de_pendientes_muestra_la_factura(self):
        response = self.client.get(reverse('cobros:invoice_pending_list'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f'#{self.factura.id:04d}')

    def test_registrar_cobro_actualiza_saldo(self):
        url = reverse('cobros:cobro_create', args=[self.factura.pk])
        response = self.client.post(url, {'fecha': HOY, 'valor': '100.00', 'monto_recibido': '100.00', 'observacion': 'Abono total'})
        self.assertEqual(response.status_code, 302)
        self.factura.refresh_from_db()
        self.assertEqual(self.factura.saldo, Decimal('0.00'))
        self.assertEqual(self.factura.estado, Invoice.PAGADA)

    def test_registrar_cobro_mayor_al_saldo_no_se_guarda(self):
        url = reverse('cobros:cobro_create', args=[self.factura.pk])
        response = self.client.post(url, {'fecha': '2026-07-01', 'valor': '999.00', 'observacion': ''})
        self.assertEqual(response.status_code, 200)
        self.factura.refresh_from_db()
        self.assertEqual(self.factura.saldo, Decimal('100.00'))
        self.assertFalse(CobroFactura.objects.filter(factura=self.factura).exists())

    def test_registrar_cobro_no_permite_elegir_paypal_en_este_formulario(self):
        # El formulario manual ahora tiene 'forma_pago' (Efectivo/Tarjeta),
        # pero PayPal queda excluido de sus choices (ver CobroFacturaForm):
        # pagar con PayPal de verdad exige el flujo real de
        # cobro_paypal_iniciar (CobroPaypalIntegrationTests). Postear
        # 'paypal' acá ya no se ignora silenciosamente, se rechaza.
        url = reverse('cobros:cobro_create', args=[self.factura.pk])
        response = self.client.post(url, {
            'fecha': HOY, 'valor': '100.00', 'forma_pago': 'paypal', 'monto_recibido': '100.00', 'observacion': '',
        })
        self.assertEqual(response.status_code, 200)
        self.assertFalse(CobroFactura.objects.filter(factura=self.factura).exists())
        self.assertIn('forma_pago', response.context['form'].errors)

    def test_registrar_cobro_sin_forma_de_pago_usa_efectivo_por_defecto(self):
        url = reverse('cobros:cobro_create', args=[self.factura.pk])
        response = self.client.post(url, {'fecha': HOY, 'valor': '100.00', 'monto_recibido': '100.00', 'observacion': ''})
        self.assertEqual(response.status_code, 302)
        cobro = CobroFactura.objects.get(factura=self.factura)
        self.assertEqual(cobro.forma_pago, CobroFactura.EFECTIVO)

    def test_no_se_puede_registrar_cobro_en_factura_anulada(self):
        factura_anulada = make_invoice(is_active=False)
        url = reverse('cobros:cobro_create', args=[factura_anulada.pk])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 302)  # redirige antes de mostrar el form

    def test_eliminar_cobro_de_factura_cancelada_muestra_error(self):
        cobro = CobroFactura.objects.create(factura=self.factura, fecha='2026-07-01', valor=Decimal('100.00'))
        url = reverse('cobros:cobro_delete', args=[cobro.pk])
        response = self.client.post(url)
        self.assertEqual(response.status_code, 302)
        self.assertTrue(CobroFactura.objects.filter(pk=cobro.pk).exists())

    def test_usuario_sin_permiso_es_redirigido(self):
        self.client.logout()
        other = User.objects.create_user('sinpermiso', password='clave-test-123')
        self.client.force_login(other)
        response = self.client.get(reverse('cobros:cobro_list'))
        self.assertEqual(response.status_code, 302)

    def test_registrar_cobro_envia_comprobante_pdf_al_cliente(self):
        self.factura.customer.email = 'cliente@example.com'
        self.factura.customer.save()
        url = reverse('cobros:cobro_create', args=[self.factura.pk])
        self.client.post(url, {'fecha': HOY, 'valor': '30.00', 'monto_recibido': '30.00', 'observacion': ''})
        self.assertEqual(len(mail.outbox), 1)
        sent = mail.outbox[0]
        self.assertIn('comprobante de cobro', sent.subject.lower())
        self.assertEqual(sent.to, ['cliente@example.com'])
        self.assertEqual(len(sent.attachments), 1)
        filename, content, mimetype = sent.attachments[0]
        self.assertTrue(filename.endswith('.pdf'))
        self.assertEqual(mimetype, 'application/pdf')

    def test_registrar_cobro_envia_comprobante_aunque_factura_quede_pagada(self):
        self.factura.customer.email = 'cliente@example.com'
        self.factura.customer.save()
        url = reverse('cobros:cobro_create', args=[self.factura.pk])
        self.client.post(url, {'fecha': HOY, 'valor': '100.00', 'monto_recibido': '100.00', 'observacion': ''})  # salda el total
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('cancelada', mail.outbox[0].body.lower())

    def test_registrar_cobro_no_envia_correo_si_cliente_sin_email(self):
        url = reverse('cobros:cobro_create', args=[self.factura.pk])
        self.client.post(url, {'fecha': HOY, 'valor': '30.00', 'monto_recibido': '30.00', 'observacion': ''})
        self.assertEqual(len(mail.outbox), 0)

    @patch('cobros.views.send_whatsapp_message')
    def test_registrar_cobro_envia_whatsapp_si_cliente_tiene_telefono(self, mock_whatsapp):
        self.factura.customer.phone = '+593987654321'
        self.factura.customer.save()
        url = reverse('cobros:cobro_create', args=[self.factura.pk])
        self.client.post(url, {'fecha': HOY, 'valor': '30.00', 'monto_recibido': '30.00', 'observacion': ''})
        mock_whatsapp.assert_called_once()
        phone_arg, body_arg = mock_whatsapp.call_args[0]
        self.assertEqual(phone_arg, '+593987654321')
        self.assertIn('30.00', body_arg)
        self.assertIn(f'#{self.factura.id:04d}', body_arg)

    @patch('cobros.views.send_whatsapp_message')
    def test_registrar_cobro_no_llama_whatsapp_si_cliente_sin_telefono(self, mock_whatsapp):
        url = reverse('cobros:cobro_create', args=[self.factura.pk])
        self.client.post(url, {'fecha': HOY, 'valor': '30.00', 'monto_recibido': '30.00', 'observacion': ''})
        mock_whatsapp.assert_not_called()

    def test_cobro_pdf_devuelve_un_pdf(self):
        cobro = CobroFactura.objects.create(factura=self.factura, fecha=HOY, valor=Decimal('30.00'))
        response = self.client.get(reverse('cobros:cobro_pdf', args=[cobro.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/pdf')

    def test_historial_no_muestra_boton_editar(self):
        cobro = CobroFactura.objects.create(factura=self.factura, fecha=HOY, valor=Decimal('20.00'))
        response = self.client.get(reverse('cobros:cobro_list'))
        self.assertNotContains(response, reverse('cobros:cobro_update', args=[cobro.pk]))

    def test_historial_muestra_boton_ver_comprobante_funcional(self):
        cobro = CobroFactura.objects.create(factura=self.factura, fecha=HOY, valor=Decimal('20.00'))
        pdf_url = reverse('cobros:cobro_pdf', args=[cobro.pk])
        response = self.client.get(reverse('cobros:cobro_list'))
        self.assertContains(response, pdf_url)
        # el enlace no solo aparece: de verdad descarga el comprobante en PDF
        pdf_response = self.client.get(pdf_url)
        self.assertEqual(pdf_response.status_code, 200)
        self.assertEqual(pdf_response['Content-Type'], 'application/pdf')

    def test_facturas_pendientes_muestra_boton_editar_del_ultimo_cobro(self):
        cobro = CobroFactura.objects.create(factura=self.factura, fecha=HOY, valor=Decimal('20.00'))
        response = self.client.get(reverse('cobros:invoice_pending_list'))
        self.assertContains(response, reverse('cobros:cobro_update', args=[cobro.pk]))

    def test_facturas_pendientes_sin_cobros_no_muestra_boton_editar(self):
        # 'btn-warning' es la clase exclusiva del botón Editar en esta
        # pantalla — buscar la palabra "Editar" a secas da falso positivo
        # porque el navbar ya trae un enlace "Editar mis datos".
        response = self.client.get(reverse('cobros:invoice_pending_list'))
        self.assertNotContains(response, 'btn-warning')


@override_settings(PAYPAL_CLIENT_ID='fake-id', PAYPAL_CLIENT_SECRET='fake-secret')
class CobroPaypalIntegrationTests(TestCase):
    """Iniciar un pago con PayPal NO debe crear el CobroFactura de inmediato
    — solo arma la orden en PayPal y redirige al checkout (ver
    paypal_pagos/services.py -> finalizar_orden, que crea el CobroFactura
    real una vez que el pago se confirma)."""

    def setUp(self):
        self.factura = make_invoice(saldo='100.00', total='100.00')
        self.user = User.objects.create_user('vendedor_pp_cobro', password='clave-test-123')
        self.user.user_permissions.set(Permission.objects.filter(
            codename__in=['view_cobrofactura', 'add_cobrofactura', 'view_invoice']
        ))
        self.client.force_login(self.user)

    @patch('paypal_pagos.services.crear_orden')
    def test_iniciar_pago_no_crea_cobro_y_redirige_al_checkout(self, mock_crear_orden):
        mock_crear_orden.return_value = ('ORDER9', 'https://paypal.test/approve9')
        url = reverse('cobros:cobro_paypal_iniciar', args=[self.factura.pk])
        response = self.client.post(url, {'monto': '40.00'})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, 'https://paypal.test/approve9')
        self.assertFalse(CobroFactura.objects.filter(factura=self.factura).exists())

        from paypal_pagos.models import OrdenPaypal
        orden = OrdenPaypal.objects.get(paypal_order_id='ORDER9')
        self.assertEqual(orden.tipo, OrdenPaypal.COBRO)
        self.assertEqual(orden.monto, Decimal('40.00'))
        self.factura.refresh_from_db()
        self.assertEqual(self.factura.saldo, Decimal('100.00'))  # sin tocar hasta confirmar

    def test_monto_mayor_al_saldo_es_rechazado(self):
        url = reverse('cobros:cobro_paypal_iniciar', args=[self.factura.pk])
        response = self.client.post(url, {'monto': '999.00'})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse('cobros:cobro_create', args=[self.factura.pk]))
        self.assertFalse(CobroFactura.objects.filter(factura=self.factura).exists())

    def test_boton_paypal_no_aparece_si_no_esta_configurado(self):
        with override_settings(PAYPAL_CLIENT_ID='', PAYPAL_CLIENT_SECRET=''):
            url = reverse('cobros:cobro_create', args=[self.factura.pk])
            response = self.client.get(url)
            self.assertNotContains(response, 'cobro_paypal_iniciar')

    def test_boton_paypal_aparece_si_esta_configurado(self):
        url = reverse('cobros:cobro_create', args=[self.factura.pk])
        response = self.client.get(url)
        self.assertContains(response, 'Pagar con PayPal')


class CobroFacturaCajaIntegrationTests(TestCase):
    """Un cobro en EFECTIVO entra físicamente a la caja del usuario — mismo
    criterio espejo que una venta en efectivo (billing) y un pago a
    proveedor en efectivo (pagos)."""

    def setUp(self):
        self.factura = make_invoice(saldo='100.00', total='100.00')
        self.user = User.objects.create_user('vendedor_caja_cobro', password='clave-test-123')
        self.user.user_permissions.set(Permission.objects.filter(
            codename__in=['view_cobrofactura', 'add_cobrofactura', 'view_invoice']
        ))
        self.client.force_login(self.user)

    def _post(self, valor='40.00', forma_pago=None, monto_recibido='1000.00'):
        data = {'fecha': HOY, 'valor': valor, 'observacion': ''}
        if forma_pago is not None:
            data['forma_pago'] = forma_pago
        if forma_pago is None or forma_pago == CobroFactura.EFECTIVO:
            data['monto_recibido'] = monto_recibido
        return self.client.post(reverse('cobros:cobro_create', args=[self.factura.pk]), data)

    def test_cobro_en_efectivo_sin_caja_abierta_es_bloqueado(self):
        response = self._post()
        self.assertEqual(response.status_code, 200)  # vuelve a mostrar el form con error
        self.assertFalse(CobroFactura.objects.filter(factura=self.factura).exists())

    def test_cobro_en_efectivo_con_caja_abierta_crea_ingreso(self):
        sesion = SesionCaja.objects.create(usuario=self.user, monto_inicial=Decimal('100.00'))
        response = self._post(valor='40.00')
        self.assertEqual(response.status_code, 302)
        cobro = CobroFactura.objects.get(factura=self.factura)
        self.assertEqual(sesion.movimientos.count(), 1)
        movimiento = sesion.movimientos.first()
        self.assertEqual(movimiento.tipo, MovimientoCaja.INGRESO)
        self.assertEqual(movimiento.monto, Decimal('40.00'))
        self.assertEqual(movimiento.cobro_factura, cobro)

    def test_forma_pago_paypal_enviada_al_form_manual_se_rechaza(self):
        # 'paypal' no está entre las choices de este formulario (ver
        # CobroFacturaForm) — el form queda inválido y no llega ni a
        # revisar la caja. Pagar con PayPal de verdad es un flujo aparte
        # (cobro_paypal_iniciar).
        response = self._post(valor='40.00', forma_pago='paypal')
        self.assertEqual(response.status_code, 200)
        self.assertFalse(CobroFactura.objects.filter(factura=self.factura).exists())

    def _post_tarjeta(self, valor='40.00'):
        return self.client.post(reverse('cobros:cobro_create', args=[self.factura.pk]), {
            'fecha': HOY, 'valor': valor, 'forma_pago': 'tarjeta', 'observacion': '',
            'tarjeta_titular': 'Ana Gómez', 'tarjeta_cvv': '456', 'tarjeta_expiracion': '2030-01-01',
        })

    def test_cobro_con_tarjeta_sin_caja_abierta_es_bloqueado(self):
        response = self._post_tarjeta()
        self.assertEqual(response.status_code, 200)
        self.assertFalse(CobroFactura.objects.filter(factura=self.factura).exists())

    def test_cobro_con_tarjeta_con_caja_abierta_no_crea_movimiento(self):
        SesionCaja.objects.create(usuario=self.user, monto_inicial=Decimal('100.00'))
        response = self._post_tarjeta(valor='40.00')
        self.assertEqual(response.status_code, 302)
        cobro = CobroFactura.objects.get(factura=self.factura)
        self.assertEqual(cobro.forma_pago, CobroFactura.TARJETA)
        self.assertEqual(cobro.tarjeta_titular, 'Ana Gómez')
        self.assertEqual(MovimientoCaja.objects.count(), 0)

    def test_cobro_en_efectivo_no_guarda_datos_de_tarjeta_aunque_se_envien(self):
        SesionCaja.objects.create(usuario=self.user, monto_inicial=Decimal('100.00'))
        response = self.client.post(reverse('cobros:cobro_create', args=[self.factura.pk]), {
            'fecha': HOY, 'valor': '40.00', 'forma_pago': 'efectivo', 'monto_recibido': '40.00', 'observacion': '',
            'tarjeta_titular': 'Ana Gómez', 'tarjeta_cvv': '456', 'tarjeta_expiracion': '2030-01-01',
        })
        self.assertEqual(response.status_code, 302)
        cobro = CobroFactura.objects.get(factura=self.factura)
        self.assertIsNone(cobro.tarjeta_titular)
        self.assertIsNone(cobro.tarjeta_cvv)
        self.assertIsNone(cobro.tarjeta_expiracion)


class CobroFacturaCuotaMinimaTests(TestCase):
    """Cuota mínima: mismo criterio espejo que PagoCompraForm (pagos/tests.py)."""

    def setUp(self):
        self.factura = make_invoice(saldo='100.00', total='100.00', meses_credito=3)

    def test_cobro_menor_a_la_cuota_minima_es_invalido(self):
        # total=100, meses_credito=3 (interes=0 por defecto en make_invoice)
        # -> cuota_minima = 100/3 = 33.33; un cobro de 10 no alcanza ese ritmo.
        self.assertEqual(self.factura.cuota_minima, Decimal('33.33'))
        form = CobroFacturaForm(
            data={'fecha': HOY, 'valor': '10.00', 'observacion': ''},
            factura=self.factura,
        )
        self.assertFalse(form.is_valid())
        self.assertIn('valor', form.errors)

    def test_cobro_por_el_saldo_restante_exime_la_cuota_minima(self):
        # Si el saldo restante ya es menor que la cuota mínima, la última
        # cuota puede ser justo ese saldo (no hace falta "redondear para arriba").
        CobroFactura.objects.create(factura=self.factura, fecha=HOY, valor=Decimal('90.00'))
        self.factura.refresh_from_db()
        self.assertEqual(self.factura.saldo, Decimal('10.00'))
        form = CobroFacturaForm(
            data={'fecha': HOY, 'valor': '10.00', 'monto_recibido': '10.00', 'observacion': ''},
            factura=self.factura,
        )
        self.assertTrue(form.is_valid())

    def test_factura_sin_meses_credito_no_exige_cuota_minima(self):
        factura_sin_plazo = make_invoice(saldo='100.00', total='100.00')
        self.assertIsNone(factura_sin_plazo.cuota_minima)
        form = CobroFacturaForm(
            data={'fecha': HOY, 'valor': '5.00', 'monto_recibido': '5.00', 'observacion': ''},
            factura=factura_sin_plazo,
        )
        self.assertTrue(form.is_valid())


class CobroFacturaFechaLimiteTests(TestCase):
    """La fecha del cobro no puede pasar el plazo de crédito (Invoice.fecha_limite_pago,
    solo cuando la factura tiene meses_credito) — mismo criterio espejo que PagoCompraForm."""

    def setUp(self):
        self.factura = make_invoice(saldo='100.00', total='100.00', meses_credito=3)

    def test_fecha_posterior_al_plazo_de_credito_es_invalida(self):
        from datetime import timedelta
        despues_del_plazo = (self.factura.fecha_limite_pago + timedelta(days=1)).isoformat()
        form = CobroFacturaForm(
            data={'fecha': despues_del_plazo, 'valor': '50.00', 'observacion': ''},
            factura=self.factura,
        )
        self.assertFalse(form.is_valid())
        self.assertIn('fecha', form.errors)

    def test_fecha_dentro_del_plazo_es_valida(self):
        form = CobroFacturaForm(
            data={'fecha': self.factura.fecha_limite_pago.isoformat(), 'valor': '50.00', 'monto_recibido': '50.00', 'observacion': ''},
            factura=self.factura,
        )
        self.assertTrue(form.is_valid())

    def test_factura_sin_meses_credito_no_tiene_limite_de_fecha(self):
        from datetime import timedelta
        factura_sin_plazo = make_invoice(saldo='100.00', total='100.00')
        muy_lejos = (factura_sin_plazo.invoice_date.date() + timedelta(days=3650)).isoformat()
        form = CobroFacturaForm(
            data={'fecha': muy_lejos, 'valor': '50.00', 'monto_recibido': '50.00', 'observacion': ''},
            factura=factura_sin_plazo,
        )
        self.assertTrue(form.is_valid())


class CobroFacturaMontoRecibidoTests(TestCase):
    """En efectivo hay que declarar cuánto entregó el cliente y se calcula el cambio."""

    def setUp(self):
        self.factura = make_invoice(saldo='100.00', total='100.00')

    def test_efectivo_sin_monto_recibido_es_invalido(self):
        form = CobroFacturaForm(
            data={'fecha': HOY, 'valor': '50.00', 'observacion': ''},
            factura=self.factura,
        )
        self.assertFalse(form.is_valid())
        self.assertIn('monto_recibido', form.errors)

    def test_efectivo_con_monto_recibido_menor_al_valor_es_invalido(self):
        form = CobroFacturaForm(
            data={'fecha': HOY, 'valor': '50.00', 'monto_recibido': '30.00', 'observacion': ''},
            factura=self.factura,
        )
        self.assertFalse(form.is_valid())
        self.assertIn('monto_recibido', form.errors)

    def test_efectivo_calcula_el_cambio(self):
        form = CobroFacturaForm(
            data={'fecha': HOY, 'valor': '50.00', 'monto_recibido': '60.00', 'observacion': ''},
            factura=self.factura,
        )
        self.assertTrue(form.is_valid())
        cobro = form.save(commit=False)
        cobro.factura = self.factura
        cobro.save()
        self.assertEqual(cobro.monto_recibido, Decimal('60.00'))
        self.assertEqual(cobro.cambio, Decimal('10.00'))

    def test_forma_pago_excluye_paypal_de_las_choices(self):
        # Este form sí tiene 'forma_pago' (Efectivo/Tarjeta), pero nunca deja
        # elegir 'paypal' a mano: pagar con PayPal de verdad es un flujo
        # aparte (cobro_paypal_iniciar, que sí cobra).
        form = CobroFacturaForm(
            data={'fecha': HOY, 'valor': '50.00', 'forma_pago': 'paypal', 'observacion': ''},
            factura=self.factura,
        )
        self.assertIn('forma_pago', form.fields)
        self.assertNotIn(CobroFactura.PAYPAL, dict(form.fields['forma_pago'].choices))
        self.assertFalse(form.is_valid())
        self.assertIn('forma_pago', form.errors)

    def test_editar_cobro_pagado_por_paypal_no_exige_monto_recibido(self):
        # Un cobro que YA se pagó de verdad por PayPal (creado por
        # paypal_pagos/services.py, no por este form) conserva su
        # forma_pago='paypal' al editarlo, y no se le pide monto recibido.
        cobro_paypal = CobroFactura.objects.create(
            factura=self.factura, fecha=HOY, valor=Decimal('50.00'), forma_pago=CobroFactura.PAYPAL,
        )
        form = CobroFacturaForm(
            data={'fecha': HOY, 'valor': '50.00', 'observacion': 'nota'},
            instance=cobro_paypal, factura=self.factura,
        )
        self.assertTrue(form.is_valid(), form.errors)
