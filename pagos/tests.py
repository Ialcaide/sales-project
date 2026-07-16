from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth.models import Permission, User
from django.core import mail
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from billing.models import Supplier
from caja.models import MovimientoCaja, SesionCaja
from purchasing.models import Purchase

from .forms import PagoCompraForm
from .models import PagoCompra

# Purchase.purchase_date es auto_now_add, así que cualquier compra creada en
# un test queda con fecha "hoy" (el día real en que corre el test). Los pagos
# que pasan por el FORMULARIO deben fecharse desde ese mismo día en adelante
# (ver PagoCompraForm.clean_fecha en pagos/forms.py) — por eso los tests que
# usan el form (no PagoCompra.objects.create() directo) usan HOY en vez de
# una fecha fija que podría quedar en el pasado.
HOY = timezone.now().date().isoformat()


def make_purchase(saldo='115.00', total='115.00', tipo_pago=Purchase.CREDITO, estado=Purchase.PENDIENTE):
    supplier = Supplier.objects.create(name='Proveedor Test')
    return Purchase.objects.create(
        supplier=supplier,
        document_number='FAC-TEST',
        subtotal=Decimal('100.00'),
        tax=Decimal('15.00'),
        total=Decimal(total),
        tipo_pago=tipo_pago,
        meses_credito=3 if tipo_pago == Purchase.CREDITO else None,
        saldo=Decimal(saldo),
        estado=estado,
    )


class PagoCompraModelTests(TestCase):
    def setUp(self):
        self.compra = make_purchase()

    def test_pago_parcial_actualiza_saldo_y_mantiene_pendiente(self):
        pago = PagoCompra.objects.create(compra=self.compra, fecha='2026-07-01', valor=Decimal('50.00'))
        self.compra.refresh_from_db()
        self.assertEqual(self.compra.saldo, Decimal('65.00'))
        self.assertEqual(self.compra.estado, Purchase.PENDIENTE)
        self.assertTrue(PagoCompra.objects.filter(pk=pago.pk).exists())

    def test_pago_que_salda_el_total_marca_pagada(self):
        PagoCompra.objects.create(compra=self.compra, fecha='2026-07-01', valor=Decimal('115.00'))
        self.compra.refresh_from_db()
        self.assertEqual(self.compra.saldo, Decimal('0.00'))
        self.assertEqual(self.compra.estado, Purchase.PAGADA)

    def test_pago_mayor_al_saldo_es_rechazado(self):
        with self.assertRaises(ValidationError):
            PagoCompra.objects.create(compra=self.compra, fecha='2026-07-01', valor=Decimal('200.00'))
        self.compra.refresh_from_db()
        self.assertEqual(self.compra.saldo, Decimal('115.00'))

    def test_pago_negativo_rechazado_por_full_clean(self):
        pago = PagoCompra(compra=self.compra, fecha='2026-07-01', valor=Decimal('-10.00'))
        with self.assertRaises(ValidationError):
            pago.full_clean()

    def test_pago_en_cero_rechazado_por_full_clean(self):
        pago = PagoCompra(compra=self.compra, fecha='2026-07-01', valor=Decimal('0.00'))
        with self.assertRaises(ValidationError):
            pago.full_clean()

    def test_editar_pago_recalcula_saldo_por_el_delta(self):
        pago = PagoCompra.objects.create(compra=self.compra, fecha='2026-07-01', valor=Decimal('50.00'))
        pago.valor = Decimal('80.00')
        pago.save()
        self.compra.refresh_from_db()
        self.assertEqual(self.compra.saldo, Decimal('35.00'))
        self.assertEqual(self.compra.estado, Purchase.PENDIENTE)

    def test_eliminar_pago_devuelve_el_saldo(self):
        pago = PagoCompra.objects.create(compra=self.compra, fecha='2026-07-01', valor=Decimal('50.00'))
        pago.delete()
        self.compra.refresh_from_db()
        self.assertEqual(self.compra.saldo, Decimal('115.00'))
        self.assertEqual(self.compra.estado, Purchase.PENDIENTE)

    def test_no_se_puede_eliminar_pago_de_compra_cancelada(self):
        pago = PagoCompra.objects.create(compra=self.compra, fecha='2026-07-01', valor=Decimal('115.00'))
        self.compra.refresh_from_db()
        self.assertEqual(self.compra.estado, Purchase.PAGADA)
        with self.assertRaises(ValidationError):
            pago.delete()
        self.assertTrue(PagoCompra.objects.filter(pk=pago.pk).exists())


class PagoCompraFormTests(TestCase):
    def setUp(self):
        self.compra = make_purchase(saldo='100.00', total='100.00')

    def test_form_valido_con_valor_dentro_del_saldo(self):
        form = PagoCompraForm(
            data={'fecha': HOY, 'valor': '50.00', 'observacion': ''},
            compra=self.compra,
        )
        self.assertTrue(form.is_valid())

    def test_form_invalido_con_valor_mayor_al_saldo(self):
        form = PagoCompraForm(
            data={'fecha': '2026-07-01', 'valor': '150.00', 'observacion': ''},
            compra=self.compra,
        )
        self.assertFalse(form.is_valid())
        self.assertIn('valor', form.errors)

    def test_form_invalido_con_valor_cero_o_negativo(self):
        for valor in ('0', '-5'):
            form = PagoCompraForm(
                data={'fecha': '2026-07-01', 'valor': valor, 'observacion': ''},
                compra=self.compra,
            )
            self.assertFalse(form.is_valid())
            self.assertIn('valor', form.errors)

    def test_editar_permite_mantener_el_mismo_valor(self):
        pago = PagoCompra.objects.create(compra=self.compra, fecha=HOY, valor=Decimal('40.00'))
        self.compra.refresh_from_db()
        form = PagoCompraForm(
            data={'fecha': HOY, 'valor': '40.00', 'observacion': ''},
            instance=pago,
            compra=self.compra,
        )
        self.assertTrue(form.is_valid())

    def test_pago_menor_a_la_cuota_minima_es_invalido(self):
        # total=100, meses_credito=3 (interes=0 por defecto en make_purchase)
        # -> cuota_minima = 100/3 = 33.33; un pago de 10 no alcanza ese ritmo.
        self.assertEqual(self.compra.cuota_minima, Decimal('33.33'))
        form = PagoCompraForm(
            data={'fecha': HOY, 'valor': '10.00', 'observacion': ''},
            compra=self.compra,
        )
        self.assertFalse(form.is_valid())
        self.assertIn('valor', form.errors)

    def test_pago_por_el_saldo_restante_exime_la_cuota_minima(self):
        # Si el saldo restante ya es menor que la cuota mínima, la última
        # cuota puede ser justo ese saldo (no hace falta "redondear para arriba").
        PagoCompra.objects.create(compra=self.compra, fecha=HOY, valor=Decimal('90.00'))
        self.compra.refresh_from_db()
        self.assertEqual(self.compra.saldo, Decimal('10.00'))
        form = PagoCompraForm(
            data={'fecha': HOY, 'valor': '10.00', 'observacion': ''},
            compra=self.compra,
        )
        self.assertTrue(form.is_valid())


class PagoCompraFechaTests(TestCase):
    """La fecha del pago debe estar entre la fecha de la compra y su plazo de crédito."""

    def setUp(self):
        self.compra = make_purchase(saldo='100.00', total='100.00')  # meses_credito=3

    def test_fecha_anterior_a_la_compra_es_invalida(self):
        from datetime import timedelta
        ayer = (self.compra.purchase_date.date() - timedelta(days=1)).isoformat()
        form = PagoCompraForm(
            data={'fecha': ayer, 'valor': '50.00', 'observacion': ''},
            compra=self.compra,
        )
        self.assertFalse(form.is_valid())
        self.assertIn('fecha', form.errors)

    def test_fecha_posterior_al_plazo_de_credito_es_invalida(self):
        from datetime import timedelta
        despues_del_plazo = (self.compra.fecha_limite_pago + timedelta(days=1)).isoformat()
        form = PagoCompraForm(
            data={'fecha': despues_del_plazo, 'valor': '50.00', 'observacion': ''},
            compra=self.compra,
        )
        self.assertFalse(form.is_valid())
        self.assertIn('fecha', form.errors)

    def test_fecha_dentro_del_plazo_es_valida(self):
        form = PagoCompraForm(
            data={'fecha': self.compra.fecha_limite_pago.isoformat(), 'valor': '50.00', 'observacion': ''},
            compra=self.compra,
        )
        self.assertTrue(form.is_valid())


class PagoCompraViewTests(TestCase):
    def setUp(self):
        self.compra = make_purchase(saldo='100.00', total='100.00')
        self.user = User.objects.create_user('analista', password='clave-test-123')
        perms = Permission.objects.filter(
            codename__in=['view_pagocompra', 'add_pagocompra', 'change_pagocompra', 'delete_pagocompra',
                           'access_pagocompra_module', 'view_purchase']
        )
        self.user.user_permissions.set(perms)
        self.client.force_login(self.user)
        # Un pago en EFECTIVO (el default de PagoCompraForm cuando no se
        # elige nada) ahora exige una caja abierta — ver
        # PagoCompraCajaIntegrationTests más abajo para el caso sin caja.
        SesionCaja.objects.create(usuario=self.user, monto_inicial=Decimal('100.00'))

    def test_lista_de_pendientes_muestra_la_compra(self):
        response = self.client.get(reverse('pagos:purchase_pending_list'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.compra.document_number)

    def test_registrar_pago_actualiza_saldo(self):
        url = reverse('pagos:pago_create', args=[self.compra.pk])
        response = self.client.post(url, {'fecha': HOY, 'valor': '100.00', 'observacion': 'Abono total'})
        self.assertEqual(response.status_code, 302)
        self.compra.refresh_from_db()
        self.assertEqual(self.compra.saldo, Decimal('0.00'))
        self.assertEqual(self.compra.estado, Purchase.PAGADA)

    def test_registrar_pago_mayor_al_saldo_no_se_guarda(self):
        url = reverse('pagos:pago_create', args=[self.compra.pk])
        response = self.client.post(url, {'fecha': HOY, 'valor': '999.00', 'observacion': ''})
        self.assertEqual(response.status_code, 200)  # vuelve a mostrar el formulario con error
        self.compra.refresh_from_db()
        self.assertEqual(self.compra.saldo, Decimal('100.00'))
        self.assertFalse(PagoCompra.objects.filter(compra=self.compra).exists())

    def test_registrar_pago_guarda_la_forma_de_pago_elegida(self):
        url = reverse('pagos:pago_create', args=[self.compra.pk])
        response = self.client.post(url, {'fecha': HOY, 'valor': '100.00', 'forma_pago': 'paypal', 'observacion': ''})
        self.assertEqual(response.status_code, 302)
        pago = PagoCompra.objects.get(compra=self.compra)
        self.assertEqual(pago.forma_pago, PagoCompra.PAYPAL)

    def test_registrar_pago_sin_forma_de_pago_usa_efectivo_por_defecto(self):
        url = reverse('pagos:pago_create', args=[self.compra.pk])
        response = self.client.post(url, {'fecha': HOY, 'valor': '100.00', 'observacion': ''})
        self.assertEqual(response.status_code, 302)
        pago = PagoCompra.objects.get(compra=self.compra)
        self.assertEqual(pago.forma_pago, PagoCompra.EFECTIVO)

    def test_eliminar_pago_de_compra_cancelada_muestra_error(self):
        pago = PagoCompra.objects.create(compra=self.compra, fecha=HOY, valor=Decimal('100.00'))
        url = reverse('pagos:pago_delete', args=[pago.pk])
        response = self.client.post(url)
        self.assertEqual(response.status_code, 302)
        self.assertTrue(PagoCompra.objects.filter(pk=pago.pk).exists())

    def test_usuario_sin_permiso_es_redirigido(self):
        self.client.logout()
        other = User.objects.create_user('sinpermiso', password='clave-test-123')
        self.client.force_login(other)
        response = self.client.get(reverse('pagos:pago_list'))
        self.assertEqual(response.status_code, 302)

    def test_pago_pdf_devuelve_un_pdf(self):
        pago = PagoCompra.objects.create(compra=self.compra, fecha=HOY, valor=Decimal('50.00'))
        response = self.client.get(reverse('pagos:pago_pdf', args=[pago.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/pdf')

    def test_registrar_pago_envia_comprobante_al_proveedor(self):
        self.compra.supplier.email = 'proveedor@example.com'
        self.compra.supplier.save()
        url = reverse('pagos:pago_create', args=[self.compra.pk])
        self.client.post(url, {'fecha': HOY, 'valor': '40.00', 'observacion': ''})
        self.assertEqual(len(mail.outbox), 1)
        sent = mail.outbox[0]
        self.assertIn('comprobante de pago', sent.subject.lower())
        self.assertEqual(sent.to, ['proveedor@example.com'])
        self.assertEqual(len(sent.attachments), 1)
        filename, content, mimetype = sent.attachments[0]
        self.assertTrue(filename.endswith('.pdf'))
        self.assertEqual(mimetype, 'application/pdf')

    def test_registrar_pago_no_envia_correo_si_proveedor_sin_email(self):
        url = reverse('pagos:pago_create', args=[self.compra.pk])
        self.client.post(url, {'fecha': HOY, 'valor': '40.00', 'observacion': ''})
        self.assertEqual(len(mail.outbox), 0)

    @patch('pagos.views.send_whatsapp_message')
    def test_registrar_pago_envia_whatsapp_si_proveedor_tiene_telefono(self, mock_whatsapp):
        self.compra.supplier.phone = '+593987654321'
        self.compra.supplier.save()
        url = reverse('pagos:pago_create', args=[self.compra.pk])
        self.client.post(url, {'fecha': HOY, 'valor': '40.00', 'observacion': ''})
        mock_whatsapp.assert_called_once()
        phone_arg, body_arg = mock_whatsapp.call_args[0]
        self.assertEqual(phone_arg, '+593987654321')
        self.assertIn('40.00', body_arg)
        self.assertIn(f'#{self.compra.id:04d}', body_arg)

    @patch('pagos.views.send_whatsapp_message')
    def test_registrar_pago_no_llama_whatsapp_si_proveedor_sin_telefono(self, mock_whatsapp):
        url = reverse('pagos:pago_create', args=[self.compra.pk])
        self.client.post(url, {'fecha': HOY, 'valor': '40.00', 'observacion': ''})
        mock_whatsapp.assert_not_called()


class PagoCompraCajaIntegrationTests(TestCase):
    """Un pago en EFECTIVO sale físicamente de la caja del usuario — mismo
    criterio espejo que una venta en efectivo (billing/tests.py -> CajaIntegracionInvoiceTests)."""

    def setUp(self):
        self.compra = make_purchase(saldo='100.00', total='100.00')
        self.user = User.objects.create_user('analista_caja', password='clave-test-123')
        self.user.user_permissions.set(Permission.objects.filter(
            codename__in=['view_pagocompra', 'add_pagocompra', 'view_purchase']
        ))
        self.client.force_login(self.user)

    def _post(self, valor='40.00', forma_pago=None):
        data = {'fecha': HOY, 'valor': valor, 'observacion': ''}
        if forma_pago is not None:
            data['forma_pago'] = forma_pago
        return self.client.post(reverse('pagos:pago_create', args=[self.compra.pk]), data)

    def test_pago_en_efectivo_sin_caja_abierta_es_bloqueado(self):
        response = self._post()
        self.assertEqual(response.status_code, 200)  # vuelve a mostrar el form con error
        self.assertFalse(PagoCompra.objects.filter(compra=self.compra).exists())

    def test_pago_en_efectivo_con_caja_abierta_crea_egreso(self):
        sesion = SesionCaja.objects.create(usuario=self.user, monto_inicial=Decimal('100.00'))
        response = self._post(valor='40.00')
        self.assertEqual(response.status_code, 302)
        pago = PagoCompra.objects.get(compra=self.compra)
        self.assertEqual(sesion.movimientos.count(), 1)
        movimiento = sesion.movimientos.first()
        self.assertEqual(movimiento.tipo, MovimientoCaja.EGRESO)
        self.assertEqual(movimiento.monto, Decimal('40.00'))
        self.assertEqual(movimiento.pago_compra, pago)
        self.assertIn(self.compra.supplier.name, movimiento.concepto)

    def test_pago_con_paypal_no_requiere_caja_ni_crea_movimiento(self):
        response = self._post(valor='40.00', forma_pago='paypal')
        self.assertEqual(response.status_code, 302)
        self.assertTrue(PagoCompra.objects.filter(compra=self.compra).exists())
        self.assertEqual(MovimientoCaja.objects.count(), 0)
