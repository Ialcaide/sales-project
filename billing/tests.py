from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth.models import Permission, User
from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings
from django.urls import reverse

from caja.models import MovimientoCaja, SesionCaja
from cobros.models import CobroFactura
from configuracion.models import ConfiguracionSistema
from facturacion_electronica.models import ComprobanteElectronico
from notificaciones.models import Notificacion

from .forms import InvoiceForm
from .models import Brand, Customer, CustomerProfile, Invoice, Product, ProductGroup, Supplier


class InvoiceAplicarTipoPagoTests(TestCase):
    def setUp(self):
        self.customer = Customer.objects.create(dni='1234567890', first_name='Ana', last_name='Gómez')

    def test_contado_queda_pagada_con_saldo_cero(self):
        invoice = Invoice(customer=self.customer, total=Decimal('100'), tipo_pago=Invoice.CONTADO)
        invoice.aplicar_tipo_pago()
        self.assertEqual(invoice.saldo, Decimal('0'))
        self.assertEqual(invoice.estado, Invoice.PAGADA)

    def test_credito_queda_pendiente_con_saldo_igual_al_total(self):
        invoice = Invoice(customer=self.customer, total=Decimal('100'), tipo_pago=Invoice.CREDITO)
        invoice.aplicar_tipo_pago()
        self.assertEqual(invoice.saldo, Decimal('100'))
        self.assertEqual(invoice.estado, Invoice.PENDIENTE)


class InvoiceCreateViewTests(TestCase):
    def setUp(self):
        self.brand = Brand.objects.create(name='Marca Test')
        self.group = ProductGroup.objects.create(name='Grupo Test')
        self.customer = Customer.objects.create(dni='1234567890', first_name='Ana', last_name='Gómez')
        CustomerProfile.objects.create(customer=self.customer, credit_limit=Decimal('1000.00'))
        self.product = Product.objects.create(
            name='Producto Test', brand=self.brand, group=self.group,
            unit_price=Decimal('10'), stock=50,
        )
        self.user = User.objects.create_user('vendedor', password='clave-test-123')
        perms = Permission.objects.filter(
            codename__in=['view_invoice', 'add_invoice', 'view_invoicedetail', 'add_invoicedetail']
        )
        self.user.user_permissions.set(perms)
        self.client.force_login(self.user)
        # EFECTIVO es la única forma de pago síncrona no-PayPal desde que se
        # quitaron tarjeta/transferencia — exige una caja abierta (ver
        # CajaIntegracionInvoiceTests más abajo para el caso sin caja).
        SesionCaja.objects.create(usuario=self.user, monto_inicial=Decimal('100.00'))

    def _post(self, tipo_pago, forma_pago=None, meses_credito=None, monto_recibido='1000.00'):
        if forma_pago is None:
            forma_pago = Invoice.EFECTIVO if tipo_pago == Invoice.CONTADO else ''
        data = {
            'customer': self.customer.id,
            'tipo_pago': tipo_pago,
            'forma_pago': forma_pago,
            'details-TOTAL_FORMS': '1',
            'details-INITIAL_FORMS': '0',
            'details-MIN_NUM_FORMS': '0',
            'details-MAX_NUM_FORMS': '1000',
            'details-0-id': '',
            'details-0-product': self.product.id,
            'details-0-quantity': '2',
            'details-0-unit_price': '10.00',
        }
        if meses_credito is not None:
            data['meses_credito'] = meses_credito
        if forma_pago == Invoice.EFECTIVO:
            data['monto_recibido'] = monto_recibido
        return self.client.post(reverse('billing:invoice_create'), data)

    def test_guardar_factura_contado_queda_pagada(self):
        response = self._post(Invoice.CONTADO)
        self.assertEqual(response.status_code, 302)
        invoice = Invoice.objects.get(customer=self.customer)
        self.assertEqual(invoice.estado, Invoice.PAGADA)
        self.assertEqual(invoice.saldo, Decimal('0.00'))

    def test_guardar_factura_credito_queda_pendiente(self):
        response = self._post(Invoice.CREDITO, meses_credito=6)
        self.assertEqual(response.status_code, 302)
        invoice = Invoice.objects.get(customer=self.customer)
        self.assertEqual(invoice.estado, Invoice.PENDIENTE)
        self.assertEqual(invoice.meses_credito, 6)
        # 6 meses cae en el tramo (4-6] -> 10% de interés (ver INTERES_TIERS)
        self.assertEqual(invoice.interes, (invoice.total * Decimal('0.10')).quantize(Decimal('0.01')))
        self.assertEqual(invoice.saldo, invoice.total + invoice.interes)

    def test_guardar_factura_credito_sin_meses_no_se_guarda(self):
        response = self._post(Invoice.CREDITO)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Invoice.objects.filter(customer=self.customer).exists())

    def test_factura_credito_bloqueada_si_excede_credito_disponible(self):
        self.customer.profile.credit_limit = Decimal('10.00')  # la factura sale en $23
        self.customer.profile.save()
        response = self._post(Invoice.CREDITO, meses_credito=6)
        self.assertEqual(response.status_code, 200)  # vuelve a mostrar el form con error
        self.assertFalse(Invoice.objects.filter(customer=self.customer).exists())

    def test_credito_disponible_baja_con_facturas_pendientes(self):
        self._post(Invoice.CREDITO, meses_credito=6)  # factura de $23 a crédito
        invoice = Invoice.objects.get(customer=self.customer)
        self.customer.refresh_from_db()
        # El límite ya no es fijo: crece 30% del total histórico comprado
        # (esta misma factura de $23, el interés no cuenta para el histórico)
        # sobre la base de $1000 del perfil.
        limite_esperado = Decimal('1000.00') + invoice.total * Decimal('0.30')
        self.assertEqual(self.customer.limite_credito, limite_esperado)
        self.assertEqual(self.customer.credito_disponible(), limite_esperado - invoice.saldo)

    def test_consumidor_final_no_admite_credito(self):
        data = {
            'customer': '',
            'consumidor_final': 'on',
            'tipo_pago': Invoice.CREDITO,
            'details-TOTAL_FORMS': '1',
            'details-INITIAL_FORMS': '0',
            'details-MIN_NUM_FORMS': '0',
            'details-MAX_NUM_FORMS': '1000',
            'details-0-id': '',
            'details-0-product': self.product.id,
            'details-0-quantity': '2',
            'details-0-unit_price': '10.00',
        }
        response = self.client.post(reverse('billing:invoice_create'), data)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Invoice.objects.filter(tipo_pago=Invoice.CREDITO, customer__dni=Customer.CONSUMIDOR_FINAL_DNI).exists())

    def test_consumidor_final_crea_factura_con_cliente_generico_y_sin_correo(self):
        data = {
            'customer': '',
            'consumidor_final': 'on',
            'tipo_pago': Invoice.CONTADO,
            'forma_pago': Invoice.EFECTIVO,
            'monto_recibido': '1000.00',
            'details-TOTAL_FORMS': '1',
            'details-INITIAL_FORMS': '0',
            'details-MIN_NUM_FORMS': '0',
            'details-MAX_NUM_FORMS': '1000',
            'details-0-id': '',
            'details-0-product': self.product.id,
            'details-0-quantity': '2',
            'details-0-unit_price': '10.00',
        }
        response = self.client.post(reverse('billing:invoice_create'), data)
        self.assertEqual(response.status_code, 302)
        invoice = Invoice.objects.latest('id')
        self.assertEqual(invoice.customer.dni, Customer.CONSUMIDOR_FINAL_DNI)
        self.assertFalse(invoice.customer.email)
        self.assertEqual(invoice.tipo_pago, Invoice.CONTADO)

    def test_venta_efectivo_calcula_cambio(self):
        # 2 x $10 + 15% IVA = $23.00
        response = self._post(Invoice.CONTADO, monto_recibido='25.00')
        self.assertEqual(response.status_code, 302)
        invoice = Invoice.objects.get(customer=self.customer)
        self.assertEqual(invoice.monto_recibido, Decimal('25.00'))
        self.assertEqual(invoice.cambio, Decimal('2.00'))

    def test_venta_efectivo_sin_monto_recibido_no_se_guarda(self):
        data = {
            'customer': self.customer.id, 'tipo_pago': Invoice.CONTADO, 'forma_pago': Invoice.EFECTIVO,
            'details-TOTAL_FORMS': '1', 'details-INITIAL_FORMS': '0', 'details-MIN_NUM_FORMS': '0', 'details-MAX_NUM_FORMS': '1000',
            'details-0-id': '', 'details-0-product': self.product.id, 'details-0-quantity': '2', 'details-0-unit_price': '10.00',
        }
        response = self.client.post(reverse('billing:invoice_create'), data)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Invoice.objects.filter(customer=self.customer).exists())

    def test_venta_efectivo_monto_insuficiente_no_se_guarda(self):
        response = self._post(Invoice.CONTADO, monto_recibido='5.00')  # la factura sale en $23
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Invoice.objects.filter(customer=self.customer).exists())


class CustomerDeleteButtonPermissionTests(TestCase):
    """Mismo criterio que InvoiceDeleteButtonPermissionTests: 'Editar'/'Borrar'
    en el detalle y listado de clientes deben reflejar los permisos reales
    (billing.change_customer / billing.delete_customer), no la pertenencia
    al grupo 'Administrador'."""

    def setUp(self):
        self.customer = Customer.objects.create(dni='1700000134', first_name='Luis', last_name='Torres')

    def _login_con_permisos(self, username, codenames):
        user = User.objects.create_user(username, password='clave-test-123')
        user.user_permissions.set(Permission.objects.filter(codename__in=codenames))
        self.client.force_login(user)
        return user

    def test_sin_permisos_no_muestra_editar_ni_borrar(self):
        self._login_con_permisos('vendedor_sin_editar', ['view_customer'])
        response = self.client.get(reverse('billing:customer_detail', args=[self.customer.pk]))
        self.assertNotContains(response, reverse('billing:customer_update', args=[self.customer.pk]))
        self.assertNotContains(response, reverse('billing:customer_delete', args=[self.customer.pk]))

    def test_con_permisos_otorgados_directamente_muestra_ambos_botones(self):
        self._login_con_permisos('vendedor_con_editar', ['view_customer', 'change_customer', 'delete_customer'])
        response = self.client.get(reverse('billing:customer_detail', args=[self.customer.pk]))
        self.assertContains(response, reverse('billing:customer_update', args=[self.customer.pk]))
        self.assertContains(response, reverse('billing:customer_delete', args=[self.customer.pk]))


class CustomerConsumidorFinalYCreditoTests(TestCase):
    def setUp(self):
        self.customer = Customer.objects.create(dni='1234567890', first_name='Ana', last_name='Gómez')

    def test_get_or_create_consumidor_final_es_idempotente(self):
        c1 = Customer.get_or_create_consumidor_final()
        c2 = Customer.get_or_create_consumidor_final()
        self.assertEqual(c1.pk, c2.pk)
        self.assertTrue(c1.es_consumidor_final)
        self.assertFalse(self.customer.es_consumidor_final)

    def test_credito_disponible_es_cero_sin_perfil(self):
        self.assertEqual(self.customer.limite_credito, Decimal('0'))
        self.assertEqual(self.customer.deuda_actual_credito(), Decimal('0'))
        self.assertEqual(self.customer.credito_disponible(), Decimal('0'))

    def test_credito_disponible_usa_el_limite_del_perfil(self):
        CustomerProfile.objects.create(customer=self.customer, credit_limit=Decimal('500.00'))
        self.assertEqual(self.customer.limite_credito, Decimal('500.00'))
        self.assertEqual(self.customer.credito_disponible(), Decimal('500.00'))

    def test_credito_disponible_descuenta_facturas_pendientes(self):
        CustomerProfile.objects.create(customer=self.customer, credit_limit=Decimal('500.00'))
        Invoice.objects.create(
            customer=self.customer, total=Decimal('200.00'), saldo=Decimal('150.00'),
            tipo_pago=Invoice.CREDITO, estado=Invoice.PENDIENTE,
        )
        # una factura ya PAGADA no debe descontar del crédito disponible
        Invoice.objects.create(
            customer=self.customer, total=Decimal('80.00'), saldo=Decimal('0.00'),
            tipo_pago=Invoice.CREDITO, estado=Invoice.PAGADA,
        )
        self.assertEqual(self.customer.deuda_actual_credito(), Decimal('150.00'))
        # límite = base ($500) + 30% del total histórico comprado ($200+$80=$280 -> +$84) = $584
        self.assertEqual(self.customer.limite_credito, Decimal('584.00'))
        self.assertEqual(self.customer.credito_disponible(), Decimal('584.00') - Decimal('150.00'))

    def test_limite_credito_crece_con_el_total_historico_comprado(self):
        CustomerProfile.objects.create(customer=self.customer, credit_limit=Decimal('100.00'))
        self.assertEqual(self.customer.total_comprado_historico(), Decimal('0'))
        self.assertEqual(self.customer.limite_credito, Decimal('100.00'))

        Invoice.objects.create(
            customer=self.customer, total=Decimal('1000.00'), saldo=Decimal('0.00'),
            tipo_pago=Invoice.CONTADO, estado=Invoice.PAGADA,
        )
        self.assertEqual(self.customer.total_comprado_historico(), Decimal('1000.00'))
        self.assertEqual(self.customer.limite_credito, Decimal('100.00') + Decimal('300.00'))

    def test_facturas_anuladas_no_cuentan_para_el_total_historico(self):
        CustomerProfile.objects.create(customer=self.customer, credit_limit=Decimal('100.00'))
        Invoice.objects.create(
            customer=self.customer, total=Decimal('1000.00'), saldo=Decimal('0.00'),
            tipo_pago=Invoice.CONTADO, estado=Invoice.PAGADA, is_active=False,
        )
        self.assertEqual(self.customer.total_comprado_historico(), Decimal('0'))
        self.assertEqual(self.customer.limite_credito, Decimal('100.00'))

    def test_sumas_de_centavos_no_dejan_ruido_de_punto_flotante(self):
        # SQLite calcula Sum() sobre DecimalField internamente en float y
        # puede devolver algo como Decimal('53.3200000000000') en vez de
        # Decimal('53.32') — estos montos "feos" (.99, .33, .01) son los que
        # de verdad disparan ese ruido; 200.00/80.00 no lo mostraban siempre.
        CustomerProfile.objects.create(customer=self.customer, credit_limit=Decimal('100.00'))
        Invoice.objects.create(
            customer=self.customer, total=Decimal('19.99'), saldo=Decimal('19.99'),
            tipo_pago=Invoice.CREDITO, estado=Invoice.PENDIENTE,
        )
        Invoice.objects.create(
            customer=self.customer, total=Decimal('33.33'), saldo=Decimal('33.33'),
            tipo_pago=Invoice.CREDITO, estado=Invoice.PENDIENTE,
        )
        for valor in (
            self.customer.deuda_actual_credito(),
            self.customer.total_comprado_historico(),
            self.customer.limite_credito,
            self.customer.credito_disponible(),
        ):
            self.assertEqual(valor.as_tuple().exponent, -2, f'{valor!r} tiene más de 2 decimales')
        self.assertEqual(self.customer.deuda_actual_credito(), Decimal('53.32'))


class CustomerTipoIdentificacionModelTests(TestCase):
    """Customer.clean() ahora valida dni según tipo_identificacion en vez de
    un único validador fijo por campo — ver shared/validators.py
    (validate_cedula_ec vs validate_pasaporte)."""

    def test_cedula_valida_con_tipo_cedula_pasa(self):
        c = Customer(dni='1700000076', tipo_identificacion=Customer.CEDULA, first_name='Ana', last_name='Gómez')
        c.full_clean()  # no debe lanzar

    def test_ruc_valido_con_tipo_ruc_pasa(self):
        c = Customer(dni='1700000076001', tipo_identificacion=Customer.RUC, first_name='Empresa', last_name='S.A.')
        c.full_clean()  # no debe lanzar

    def test_cedula_invalida_con_tipo_cedula_falla(self):
        c = Customer(dni='9999999999', tipo_identificacion=Customer.CEDULA, first_name='Ana', last_name='Gómez')
        with self.assertRaises(ValidationError):
            c.full_clean()

    def test_pasaporte_alfanumerico_con_tipo_pasaporte_pasa(self):
        # Un pasaporte NUNCA pasaría validate_cedula_ec (no es solo dígitos)
        # — la prueba real es justamente que con tipo_identificacion=PASAPORTE
        # no se le aplica ese validador.
        c = Customer(dni='AB123456', tipo_identificacion=Customer.PASAPORTE, first_name='John', last_name='Doe')
        c.full_clean()  # no debe lanzar

    def test_pasaporte_muy_corto_falla(self):
        c = Customer(dni='ab', tipo_identificacion=Customer.PASAPORTE, first_name='John', last_name='Doe')
        with self.assertRaises(ValidationError):
            c.full_clean()

    def test_pasaporte_con_simbolos_falla(self):
        c = Customer(dni='AB-123456', tipo_identificacion=Customer.PASAPORTE, first_name='John', last_name='Doe')
        with self.assertRaises(ValidationError):
            c.full_clean()

    def test_dni_alfanumerico_con_tipo_cedula_falla(self):
        # El mismo dni de pasaporte NO debe pasar si tipo_identificacion
        # dice que es cédula/RUC — confirma que es tipo_identificacion, no
        # el formato del valor, quien decide qué validador corre.
        c = Customer(dni='AB123456', tipo_identificacion=Customer.CEDULA, first_name='John', last_name='Doe')
        with self.assertRaises(ValidationError):
            c.full_clean()


class TelefonoNormalizacionTests(TestCase):
    """Customer/Supplier.clean() debe dejar el teléfono listo para WhatsApp."""

    def test_customer_antepone_593_si_falta_codigo_de_pais(self):
        customer = Customer(dni='1700000001', first_name='Ana', last_name='Gómez', phone='0987654321')
        customer.full_clean()
        self.assertEqual(customer.phone, '+593987654321')

    def test_customer_respeta_telefono_que_ya_trae_mas(self):
        customer = Customer(dni='1700000019', first_name='Ana', last_name='Gómez', phone='+14155551234')
        customer.full_clean()
        self.assertEqual(customer.phone, '+14155551234')

    def test_customer_sin_telefono_no_falla(self):
        customer = Customer(dni='1700000027', first_name='Ana', last_name='Gómez', phone='')
        customer.full_clean()  # no debe lanzar

    def test_customer_telefono_invalido_es_rechazado(self):
        customer = Customer(dni='1700000035', first_name='Ana', last_name='Gómez', phone='abc')
        with self.assertRaises(ValidationError):
            customer.full_clean()

    def test_supplier_antepone_593_si_falta_codigo_de_pais(self):
        supplier = Supplier(name='Proveedor Test', phone='0987654321')
        supplier.full_clean()
        self.assertEqual(supplier.phone, '+593987654321')


class InvoiceFormConsumidorFinalTests(TestCase):
    def setUp(self):
        self.customer = Customer.objects.create(dni='1234567890', first_name='Ana', last_name='Gómez')

    def test_sin_cliente_ni_consumidor_final_es_invalido(self):
        form = InvoiceForm(data={'tipo_pago': Invoice.CONTADO})
        self.assertFalse(form.is_valid())
        self.assertIn('customer', form.errors)

    def test_consumidor_final_con_credito_es_invalido(self):
        form = InvoiceForm(data={'consumidor_final': 'on', 'tipo_pago': Invoice.CREDITO})
        self.assertFalse(form.is_valid())
        self.assertIn('tipo_pago', form.errors)

    def test_consumidor_final_asigna_cliente_generico(self):
        form = InvoiceForm(data={'consumidor_final': 'on', 'tipo_pago': Invoice.CONTADO, 'forma_pago': Invoice.EFECTIVO})
        self.assertTrue(form.is_valid())
        self.assertEqual(form.cleaned_data['customer'].dni, Customer.CONSUMIDOR_FINAL_DNI)


class InvoiceFormaPagoModelTests(TestCase):
    def setUp(self):
        self.customer = Customer.objects.create(dni='1700000001', first_name='Ana', last_name='Gómez')

    def test_contado_sin_forma_pago_es_invalido(self):
        invoice = Invoice(customer=self.customer, total=Decimal('100'), tipo_pago=Invoice.CONTADO)
        with self.assertRaises(ValidationError):
            invoice.full_clean()

    def test_contado_con_forma_pago_es_valido(self):
        invoice = Invoice(customer=self.customer, total=Decimal('100'), tipo_pago=Invoice.CONTADO, forma_pago=Invoice.EFECTIVO)
        invoice.full_clean()  # no debe lanzar

    def test_credito_con_forma_pago_es_invalido(self):
        invoice = Invoice(
            customer=self.customer, total=Decimal('100'), tipo_pago=Invoice.CREDITO,
            forma_pago=Invoice.EFECTIVO, meses_credito=6,
        )
        with self.assertRaises(ValidationError):
            invoice.full_clean()

    def test_credito_sin_forma_pago_es_valido(self):
        invoice = Invoice(customer=self.customer, total=Decimal('100'), tipo_pago=Invoice.CREDITO, meses_credito=6)
        invoice.full_clean()  # no debe lanzar


class InvoiceMesesCreditoModelTests(TestCase):
    """Espejo de PurchaseMesesCreditoModelTests (purchasing/tests.py)."""

    def setUp(self):
        self.customer = Customer.objects.create(dni='1700000043', first_name='Ana', last_name='Gómez')

    def make(self, **kwargs):
        defaults = dict(customer=self.customer, total=Decimal('100'))
        defaults.update(kwargs)
        return Invoice(**defaults)

    def test_credito_sin_meses_es_invalido(self):
        invoice = self.make(tipo_pago=Invoice.CREDITO, meses_credito=None)
        with self.assertRaises(ValidationError):
            invoice.full_clean()

    def test_credito_con_meses_en_cero_es_invalido(self):
        invoice = self.make(tipo_pago=Invoice.CREDITO, meses_credito=0)
        with self.assertRaises(ValidationError):
            invoice.full_clean()

    def test_credito_con_meses_fuera_de_rango_es_invalido(self):
        invoice = self.make(tipo_pago=Invoice.CREDITO, meses_credito=Invoice.MESES_CREDITO_MAX + 1)
        with self.assertRaises(ValidationError):
            invoice.full_clean()

    def test_credito_con_meses_valido_pasa(self):
        invoice = self.make(tipo_pago=Invoice.CREDITO, meses_credito=6)
        invoice.full_clean()  # no debe lanzar

    def test_contado_con_meses_es_invalido(self):
        invoice = self.make(tipo_pago=Invoice.CONTADO, forma_pago=Invoice.EFECTIVO, meses_credito=3)
        with self.assertRaises(ValidationError):
            invoice.full_clean()

    def test_contado_sin_meses_pasa(self):
        invoice = self.make(tipo_pago=Invoice.CONTADO, forma_pago=Invoice.EFECTIVO, meses_credito=None)
        invoice.full_clean()  # no debe lanzar


class InvoiceFormMesesCreditoTests(TestCase):
    """Espejo de PurchaseFormMesesCreditoTests (purchasing/tests.py)."""

    def setUp(self):
        self.customer = Customer.objects.create(dni='1700000050', first_name='Ana', last_name='Gómez')

    def test_form_credito_sin_meses_muestra_error(self):
        form = InvoiceForm(data={'customer': self.customer.id, 'tipo_pago': Invoice.CREDITO})
        self.assertFalse(form.is_valid())
        self.assertIn('meses_credito', form.errors)

    def test_form_credito_con_meses_es_valido(self):
        form = InvoiceForm(data={
            'customer': self.customer.id, 'tipo_pago': Invoice.CREDITO, 'meses_credito': 6,
        })
        self.assertTrue(form.is_valid())

    def test_form_contado_con_meses_muestra_error(self):
        form = InvoiceForm(data={
            'customer': self.customer.id, 'tipo_pago': Invoice.CONTADO, 'forma_pago': Invoice.EFECTIVO,
            'meses_credito': 3,
        })
        self.assertFalse(form.is_valid())
        self.assertIn('meses_credito', form.errors)

    def test_form_contado_sin_meses_es_valido(self):
        form = InvoiceForm(data={
            'customer': self.customer.id, 'tipo_pago': Invoice.CONTADO, 'forma_pago': Invoice.EFECTIVO,
        })
        self.assertTrue(form.is_valid())


class InvoiceFinanciamientoTests(TestCase):
    """Tasa de interés según meses, y cuota mínima resultante — espejo de
    PurchaseFinanciamientoTests (purchasing/tests.py)."""

    def setUp(self):
        self.customer = Customer.objects.create(dni='1700000068', first_name='Ana', last_name='Gómez')

    def make(self, meses_credito, total='100.00', tipo_pago=Invoice.CREDITO):
        return Invoice(
            customer=self.customer, total=Decimal(total), tipo_pago=tipo_pago, meses_credito=meses_credito,
        )

    def test_tasa_interes_por_tramo(self):
        self.assertEqual(Invoice.tasa_interes(1), Decimal('0.05'))
        self.assertEqual(Invoice.tasa_interes(3), Decimal('0.05'))
        self.assertEqual(Invoice.tasa_interes(4), Decimal('0.10'))
        self.assertEqual(Invoice.tasa_interes(6), Decimal('0.10'))
        self.assertEqual(Invoice.tasa_interes(7), Decimal('0.15'))
        self.assertEqual(Invoice.tasa_interes(12), Decimal('0.15'))
        self.assertEqual(Invoice.tasa_interes(13), Decimal('0.20'))
        self.assertEqual(Invoice.tasa_interes(24), Decimal('0.20'))
        self.assertEqual(Invoice.tasa_interes(25), Decimal('0.25'))
        self.assertEqual(Invoice.tasa_interes(36), Decimal('0.25'))

    def test_aplicar_tipo_pago_credito_calcula_interes_y_saldo(self):
        invoice = self.make(meses_credito=12, total='100.00')
        invoice.aplicar_tipo_pago()
        self.assertEqual(invoice.interes, Decimal('15.00'))
        self.assertEqual(invoice.saldo, Decimal('115.00'))
        self.assertEqual(invoice.estado, Invoice.PENDIENTE)

    def test_aplicar_tipo_pago_contado_sin_interes(self):
        invoice = self.make(meses_credito=None, total='100.00', tipo_pago=Invoice.CONTADO)
        invoice.aplicar_tipo_pago()
        self.assertEqual(invoice.interes, Decimal('0'))
        self.assertEqual(invoice.saldo, 0)
        self.assertEqual(invoice.estado, Invoice.PAGADA)

    def test_credito_sin_meses_credito_compatibilidad_sin_interes(self):
        # Facturas creadas fuera del form (ej. .objects.create() directo, o
        # históricas) sin meses_credito: mismo comportamiento que antes de
        # este cambio, interes=0 y saldo=total.
        invoice = self.make(meses_credito=None, total='100.00', tipo_pago=Invoice.CREDITO)
        invoice.aplicar_tipo_pago()
        self.assertEqual(invoice.interes, Decimal('0'))
        self.assertEqual(invoice.saldo, Decimal('100'))
        self.assertEqual(invoice.estado, Invoice.PENDIENTE)

    def test_cuota_minima_es_total_a_pagar_entre_meses(self):
        invoice = self.make(meses_credito=4, total='100.00')  # tramo 10%
        invoice.aplicar_tipo_pago()
        # total_a_pagar = 110.00 / 4 meses = 27.50
        self.assertEqual(invoice.cuota_minima, Decimal('27.50'))

    def test_cuota_minima_none_para_contado(self):
        invoice = self.make(meses_credito=None, total='100.00', tipo_pago=Invoice.CONTADO)
        invoice.aplicar_tipo_pago()
        self.assertIsNone(invoice.cuota_minima)

    def test_fecha_limite_pago_suma_meses_a_la_fecha_de_la_factura(self):
        # invoice_date es auto_now_add, por eso acá sí se guarda (.create())
        # en vez de solo instanciar el objeto en memoria.
        invoice = Invoice.objects.create(
            customer=self.customer, total=Decimal('100'), tipo_pago=Invoice.CREDITO, meses_credito=5,
        )
        fecha_factura = invoice.invoice_date.date()
        limite = invoice.fecha_limite_pago
        self.assertEqual(limite.year, fecha_factura.year + (1 if fecha_factura.month + 5 > 12 else 0))
        self.assertEqual(limite.day, fecha_factura.day)

    def test_fecha_limite_pago_none_para_contado(self):
        invoice = Invoice.objects.create(
            customer=self.customer, total=Decimal('100'), tipo_pago=Invoice.CONTADO, forma_pago=Invoice.EFECTIVO,
        )
        self.assertIsNone(invoice.fecha_limite_pago)


class ProductBarcodeTests(TestCase):
    def setUp(self):
        self.brand = Brand.objects.create(name='Marca Barcode')
        self.group = ProductGroup.objects.create(name='Grupo Barcode')

    def test_barcode_vacio_se_normaliza_a_none(self):
        product = Product(name='Producto 1', brand=self.brand, group=self.group, unit_price=Decimal('10'), barcode='')
        product.full_clean()
        self.assertIsNone(product.barcode)

    def test_dos_productos_sin_barcode_no_chocan(self):
        Product.objects.create(name='Producto 1', brand=self.brand, group=self.group, unit_price=Decimal('10'), stock=0, barcode=None)
        p2 = Product(name='Producto 2', brand=self.brand, group=self.group, unit_price=Decimal('10'), barcode='')
        p2.full_clean()  # no debe lanzar por unique=True (None/'' -> None)

    def test_barcode_duplicado_es_rechazado(self):
        Product.objects.create(name='Producto 1', brand=self.brand, group=self.group, unit_price=Decimal('10'), stock=0, barcode='7501234567890')
        p2 = Product(name='Producto 2', brand=self.brand, group=self.group, unit_price=Decimal('10'), barcode='7501234567890')
        with self.assertRaises(ValidationError):
            p2.full_clean()


class ProductBarcodeAutoGenerationTests(TestCase):
    def setUp(self):
        self.brand = Brand.objects.create(name='Marca AutoBarcode')
        self.group = ProductGroup.objects.create(name='Grupo AutoBarcode')

    def _digito_verificador_esperado(self, codigo_12):
        pesos = sum(int(d) * (3 if i % 2 else 1) for i, d in enumerate(codigo_12))
        return (10 - (pesos % 10)) % 10

    def test_producto_sin_barcode_recibe_uno_automatico_de_13_digitos(self):
        product = Product.objects.create(
            name='Producto Sin Codigo', brand=self.brand, group=self.group, unit_price=Decimal('10'),
        )
        self.assertIsNotNone(product.barcode)
        self.assertEqual(len(product.barcode), 13)
        self.assertTrue(product.barcode.isdigit())
        self.assertTrue(product.barcode.startswith('200'))

    def test_digito_verificador_es_correcto(self):
        product = Product.objects.create(
            name='Producto Verificador', brand=self.brand, group=self.group, unit_price=Decimal('10'),
        )
        codigo_12, digito = product.barcode[:12], product.barcode[12]
        self.assertEqual(int(digito), self._digito_verificador_esperado(codigo_12))

    def test_barcode_incluye_el_pk_del_producto(self):
        product = Product.objects.create(
            name='Producto PK', brand=self.brand, group=self.group, unit_price=Decimal('10'),
        )
        self.assertEqual(product.barcode[3:12], f'{product.pk:09d}')

    def test_dos_productos_sin_barcode_reciben_codigos_distintos(self):
        p1 = Product.objects.create(name='Producto A', brand=self.brand, group=self.group, unit_price=Decimal('10'))
        p2 = Product.objects.create(name='Producto B', brand=self.brand, group=self.group, unit_price=Decimal('10'))
        self.assertNotEqual(p1.barcode, p2.barcode)

    def test_barcode_manual_no_se_sobrescribe(self):
        product = Product.objects.create(
            name='Producto Manual', brand=self.brand, group=self.group, unit_price=Decimal('10'),
            barcode='7501234567890',
        )
        self.assertEqual(product.barcode, '7501234567890')

    def test_actualizar_producto_existente_no_le_cambia_el_barcode(self):
        product = Product.objects.create(name='Producto Editar', brand=self.brand, group=self.group, unit_price=Decimal('10'))
        barcode_original = product.barcode
        product.unit_price = Decimal('15')
        product.save()
        product.refresh_from_db()
        self.assertEqual(product.barcode, barcode_original)


class ProductBarcodeViewTests(TestCase):
    def setUp(self):
        self.brand = Brand.objects.create(name='Marca Barcode View')
        self.group = ProductGroup.objects.create(name='Grupo Barcode View')
        self.product = Product.objects.create(
            name='Producto Vista Barcode', brand=self.brand, group=self.group, unit_price=Decimal('10'),
        )
        self.user = User.objects.create_user('viewer_barcode', password='clave-test-123')
        self.user.user_permissions.set(Permission.objects.filter(codename__in=['view_product', 'access_product_module']))
        self.client.force_login(self.user)

    def test_imagen_de_barcode_devuelve_png(self):
        response = self.client.get(reverse('billing:product_barcode_image', args=[self.product.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'image/png')

    def test_vista_de_impresion_muestra_el_producto(self):
        response = self.client.get(reverse('billing:product_barcode_print', args=[self.product.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.product.name)
        self.assertContains(response, str(self.product.unit_price))

    def test_usuario_sin_permiso_es_redirigido(self):
        self.client.logout()
        other = User.objects.create_user('sinpermiso_barcode', password='clave-test-123')
        self.client.force_login(other)
        response = self.client.get(reverse('billing:product_barcode_image', args=[self.product.pk]))
        self.assertEqual(response.status_code, 302)

    def test_buscar_por_codigo_de_barras_encuentra_el_producto(self):
        response = self.client.get(reverse('billing:product_list'), {'q': self.product.barcode})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.product.name)


class InvoiceCancelViewTests(TestCase):
    def setUp(self):
        self.brand = Brand.objects.create(name='Marca Cancel')
        self.group = ProductGroup.objects.create(name='Grupo Cancel')
        self.customer = Customer.objects.create(dni='1700000019', first_name='Ana', last_name='Gómez')
        self.product = Product.objects.create(name='Producto Cancel', brand=self.brand, group=self.group, unit_price=Decimal('10'), stock=48)
        self.invoice = Invoice.objects.create(
            customer=self.customer, subtotal=Decimal('20'), tax=Decimal('3'), total=Decimal('23'),
            tipo_pago=Invoice.CONTADO, forma_pago=Invoice.EFECTIVO, saldo=Decimal('0'), estado=Invoice.PAGADA,
        )
        from .models import InvoiceDetail
        InvoiceDetail.objects.create(invoice=self.invoice, product=self.product, quantity=2, unit_price=Decimal('10'))

        self.user = User.objects.create_user('vendedor_cancel', password='clave-test-123')
        perms = Permission.objects.filter(codename__in=['view_invoice', 'change_invoice'])
        self.user.user_permissions.set(perms)
        self.client.force_login(self.user)

    def test_anular_restaura_stock_y_marca_inactiva(self):
        url = reverse('billing:invoice_cancel', args=[self.invoice.pk])
        response = self.client.post(url)
        self.assertEqual(response.status_code, 302)
        self.invoice.refresh_from_db()
        self.product.refresh_from_db()
        self.assertFalse(self.invoice.is_active)
        self.assertEqual(self.product.stock, 50)  # 48 + 2 restaurados

    def test_no_se_puede_anular_dos_veces(self):
        self.invoice.is_active = False
        self.invoice.save(update_fields=['is_active'])
        url = reverse('billing:invoice_cancel', args=[self.invoice.pk])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 302)

    def test_no_se_puede_anular_con_cobros_registrados(self):
        credito_invoice = Invoice.objects.create(
            customer=self.customer, subtotal=Decimal('20'), tax=Decimal('3'), total=Decimal('23'),
            tipo_pago=Invoice.CREDITO, saldo=Decimal('23'), estado=Invoice.PENDIENTE,
        )
        CobroFactura.objects.create(factura=credito_invoice, fecha='2026-07-11', valor=Decimal('10.00'))
        url = reverse('billing:invoice_cancel', args=[credito_invoice.pk])
        response = self.client.post(url)
        self.assertEqual(response.status_code, 302)
        credito_invoice.refresh_from_db()
        self.assertTrue(credito_invoice.is_active)  # sigue activa, no se anuló


class CajaIntegracionInvoiceTests(TestCase):
    def setUp(self):
        self.brand = Brand.objects.create(name='Marca Caja')
        self.group = ProductGroup.objects.create(name='Grupo Caja')
        self.customer = Customer.objects.create(dni='1700000027', first_name='Ana', last_name='Gómez')
        self.product = Product.objects.create(name='Producto Caja', brand=self.brand, group=self.group, unit_price=Decimal('10'), stock=50)
        self.user = User.objects.create_user('cajero_pos', password='clave-test-123')
        perms = Permission.objects.filter(
            codename__in=['view_invoice', 'add_invoice', 'view_invoicedetail', 'add_invoicedetail']
        )
        self.user.user_permissions.set(perms)
        self.client.force_login(self.user)

    def _post_efectivo(self):
        data = {
            'customer': self.customer.id, 'tipo_pago': Invoice.CONTADO, 'forma_pago': Invoice.EFECTIVO,
            'monto_recibido': '1000.00',
            'details-TOTAL_FORMS': '1', 'details-INITIAL_FORMS': '0', 'details-MIN_NUM_FORMS': '0', 'details-MAX_NUM_FORMS': '1000',
            'details-0-id': '', 'details-0-product': self.product.id, 'details-0-quantity': '2', 'details-0-unit_price': '10.00',
        }
        return self.client.post(reverse('billing:invoice_create'), data)

    def test_venta_en_efectivo_sin_caja_abierta_es_bloqueada(self):
        response = self._post_efectivo()
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Invoice.objects.filter(customer=self.customer).exists())

    def test_venta_en_efectivo_con_caja_abierta_crea_movimiento(self):
        sesion = SesionCaja.objects.create(usuario=self.user, monto_inicial=Decimal('100.00'))
        response = self._post_efectivo()
        self.assertEqual(response.status_code, 302)
        invoice = Invoice.objects.get(customer=self.customer)
        self.assertEqual(sesion.movimientos.count(), 1)
        movimiento = sesion.movimientos.first()
        self.assertEqual(movimiento.tipo, MovimientoCaja.INGRESO)
        self.assertEqual(movimiento.monto, invoice.total)
        self.assertEqual(movimiento.invoice, invoice)


class InvoiceDeleteButtonPermissionTests(TestCase):
    """El botón 'Eliminar' debe reflejar el permiso real (billing.delete_invoice)
    otorgado desde Seguridad > Permisos, sin importar a qué rol/grupo pertenezca
    el usuario — antes quedaba fijo a 'pertenece al grupo Administrador',
    así que otorgarle el permiso de eliminar a otro rol (ej. Vendedor) no
    hacía aparecer el botón."""

    def setUp(self):
        self.brand = Brand.objects.create(name='Marca DelBtn')
        self.group = ProductGroup.objects.create(name='Grupo DelBtn')
        self.customer = Customer.objects.create(dni='1700000126', first_name='Ana', last_name='Gómez')
        self.product = Product.objects.create(name='Producto DelBtn', brand=self.brand, group=self.group, unit_price=Decimal('10'), stock=10)
        self.invoice = Invoice.objects.create(
            customer=self.customer, subtotal=Decimal('20'), tax=Decimal('3'), total=Decimal('23'),
            tipo_pago=Invoice.CONTADO, forma_pago=Invoice.EFECTIVO, saldo=Decimal('0'), estado=Invoice.PAGADA,
        )
        from .models import InvoiceDetail
        InvoiceDetail.objects.create(invoice=self.invoice, product=self.product, quantity=2, unit_price=Decimal('10'))

    def _login_con_permisos(self, username, codenames):
        user = User.objects.create_user(username, password='clave-test-123')
        user.user_permissions.set(Permission.objects.filter(codename__in=codenames))
        self.client.force_login(user)
        return user

    def test_sin_permiso_de_eliminar_no_muestra_el_boton(self):
        self._login_con_permisos('vendedor_sin_borrar', ['view_invoice'])
        response = self.client.get(reverse('billing:invoice_detail', args=[self.invoice.pk]))
        self.assertNotContains(response, reverse('billing:invoice_delete', args=[self.invoice.pk]))

    def test_con_permiso_de_eliminar_otorgado_directamente_muestra_el_boton(self):
        # Un usuario SIN el grupo "Administrador" pero con el permiso
        # delete_invoice otorgado (ej. vía el rol Vendedor) debe ver el botón.
        self._login_con_permisos('vendedor_con_borrar', ['view_invoice', 'delete_invoice'])
        response = self.client.get(reverse('billing:invoice_detail', args=[self.invoice.pk]))
        self.assertContains(response, reverse('billing:invoice_delete', args=[self.invoice.pk]))

    def test_lista_de_facturas_respeta_el_mismo_permiso(self):
        self._login_con_permisos('vendedor_lista', ['view_invoice', 'delete_invoice', 'access_invoice_module'])
        response = self.client.get(reverse('billing:invoice_list'))
        self.assertContains(response, reverse('billing:invoice_delete', args=[self.invoice.pk]))


class InvoiceWhatsAppTests(TestCase):
    def setUp(self):
        self.brand = Brand.objects.create(name='Marca WA')
        self.group = ProductGroup.objects.create(name='Grupo WA')
        self.customer = Customer.objects.create(dni='1700000035', first_name='Ana', last_name='Gómez', phone='+593987654321')
        self.product = Product.objects.create(name='Producto WA', brand=self.brand, group=self.group, unit_price=Decimal('10'), stock=50)
        self.user = User.objects.create_user('vendedor_wa', password='clave-test-123')
        perms = Permission.objects.filter(
            codename__in=['view_invoice', 'add_invoice', 'view_invoicedetail', 'add_invoicedetail']
        )
        self.user.user_permissions.set(perms)
        self.client.force_login(self.user)
        SesionCaja.objects.create(usuario=self.user, monto_inicial=Decimal('100.00'))

    def _post(self):
        data = {
            'customer': self.customer.id, 'tipo_pago': Invoice.CONTADO, 'forma_pago': Invoice.EFECTIVO,
            'monto_recibido': '1000.00',
            'details-TOTAL_FORMS': '1', 'details-INITIAL_FORMS': '0', 'details-MIN_NUM_FORMS': '0', 'details-MAX_NUM_FORMS': '1000',
            'details-0-id': '', 'details-0-product': self.product.id, 'details-0-quantity': '1', 'details-0-unit_price': '10.00',
        }
        return self.client.post(reverse('billing:invoice_create'), data)

    @patch('billing.views.send_whatsapp_message')
    def test_envia_whatsapp_al_cliente_con_telefono(self, mock_whatsapp):
        self._post()
        mock_whatsapp.assert_called_once()
        phone_arg, body_arg = mock_whatsapp.call_args[0]
        self.assertEqual(phone_arg, '+593987654321')
        self.assertIn('Factura', body_arg)

    @patch('billing.views.send_whatsapp_message')
    def test_no_envia_whatsapp_a_consumidor_final(self, mock_whatsapp):
        data = {
            'customer': '', 'consumidor_final': 'on', 'tipo_pago': Invoice.CONTADO, 'forma_pago': Invoice.EFECTIVO,
            'monto_recibido': '1000.00',
            'details-TOTAL_FORMS': '1', 'details-INITIAL_FORMS': '0', 'details-MIN_NUM_FORMS': '0', 'details-MAX_NUM_FORMS': '1000',
            'details-0-id': '', 'details-0-product': self.product.id, 'details-0-quantity': '1', 'details-0-unit_price': '10.00',
        }
        self.client.post(reverse('billing:invoice_create'), data)
        mock_whatsapp.assert_not_called()


class InvoiceEmailAdjuntosSRITests(TestCase):
    """El correo automático de la factura adjunta el RIDE y el XML del
    comprobante electrónico cuando el SRI llegó a generarlo — ver
    billing/views.py -> _finalizar_venta. generar_y_enviar_comprobante se
    mockea (la firma/envío real al SRI ya está cubierta en
    facturacion_electronica/tests.py) para poder verificar, aislado, que
    _finalizar_venta arma los adjuntos correctos según lo que ese mock
    devuelva."""

    def setUp(self):
        self.brand = Brand.objects.create(name='Marca Email SRI')
        self.group = ProductGroup.objects.create(name='Grupo Email SRI')
        self.customer = Customer.objects.create(
            dni='1700000308', first_name='Ana', last_name='Gómez', email='ana@example.com',
        )
        self.product = Product.objects.create(
            name='Producto Email SRI', brand=self.brand, group=self.group, unit_price=Decimal('10'), stock=50,
        )
        self.user = User.objects.create_user('vendedor_email_sri', password='clave-test-123')
        perms = Permission.objects.filter(
            codename__in=['view_invoice', 'add_invoice', 'view_invoicedetail', 'add_invoicedetail']
        )
        self.user.user_permissions.set(perms)
        self.client.force_login(self.user)
        SesionCaja.objects.create(usuario=self.user, monto_inicial=Decimal('100.00'))

    def _post(self):
        data = {
            'customer': self.customer.id, 'tipo_pago': Invoice.CONTADO, 'forma_pago': Invoice.EFECTIVO,
            'monto_recibido': '1000.00',
            'details-TOTAL_FORMS': '1', 'details-INITIAL_FORMS': '0', 'details-MIN_NUM_FORMS': '0', 'details-MAX_NUM_FORMS': '1000',
            'details-0-id': '', 'details-0-product': self.product.id, 'details-0-quantity': '1', 'details-0-unit_price': '10.00',
        }
        return self.client.post(reverse('billing:invoice_create'), data)

    @patch('billing.views.send_email_with_attachments')
    @patch('facturacion_electronica.ride.build_ride_pdf')
    @patch('facturacion_electronica.services.generar_y_enviar_comprobante')
    def test_correo_adjunta_ride_y_xml_cuando_hay_comprobante(self, mock_generar, mock_ride, mock_send):
        # build_ride_pdf ahora le pide el PDF a sri_facturacion_service por
        # HTTP (antes lo armaba local con reportlab) — se mockea acá para
        # no depender de tener ese servicio realmente levantado en los tests.
        mock_ride.return_value = b'%PDF-fake-ride%'

        def _fake_generar(invoice):
            return ComprobanteElectronico.objects.create(
                invoice=invoice, establecimiento='001', punto_emision='001', secuencial='000000001',
                clave_acceso='1' * 49, xml_generado='<factura>contenido</factura>',
            )
        mock_generar.side_effect = _fake_generar

        self._post()

        mock_send.assert_called_once()
        to_email, subject, body, adjuntos = mock_send.call_args[0]
        self.assertEqual(to_email, 'ana@example.com')
        nombres = [nombre for nombre, _, _ in adjuntos]
        self.assertEqual(len(adjuntos), 3)
        self.assertTrue(any(n.startswith('factura_') and n.endswith('.pdf') for n in nombres))
        self.assertTrue(any(n.startswith('ride_') and n.endswith('.pdf') for n in nombres))
        self.assertTrue(any(n.startswith('factura_sri_') and n.endswith('.xml') for n in nombres))
        self.assertIn('RIDE', body)

    @patch('billing.views.send_email_with_attachments')
    @patch('facturacion_electronica.services.generar_y_enviar_comprobante')
    def test_correo_solo_lleva_pdf_si_el_sri_no_genero_comprobante(self, mock_generar, mock_send):
        # "best effort": si el SRI está caído o mal configurado,
        # generar_y_enviar_comprobante devuelve None — la venta y el correo
        # deben seguir su curso igual, solo sin RIDE/XML.
        mock_generar.return_value = None

        self._post()

        mock_send.assert_called_once()
        to_email, subject, body, adjuntos = mock_send.call_args[0]
        self.assertEqual(len(adjuntos), 1)
        self.assertTrue(adjuntos[0][0].startswith('factura_'))
        self.assertNotIn('RIDE', body)

    @patch('billing.views.send_email_with_attachments')
    @patch('facturacion_electronica.ride.build_ride_pdf')
    @patch('facturacion_electronica.services.generar_y_enviar_comprobante')
    def test_correo_omite_el_ride_si_el_microservicio_de_facturacion_falla(self, mock_generar, mock_ride, mock_send):
        # "best effort" nuevo (desde que el RIDE se pide por HTTP a
        # sri_facturacion_service): si ESE servicio está caído justo al
        # armar el correo, la venta y el correo deben salir igual, con el
        # XML (ya lo teníamos guardado localmente) pero sin el RIDE.
        from facturacion_electronica.services import SRIError
        mock_ride.side_effect = SRIError('sri_facturacion_service no responde')

        def _fake_generar(invoice):
            return ComprobanteElectronico.objects.create(
                invoice=invoice, establecimiento='001', punto_emision='001', secuencial='000000001',
                clave_acceso='1' * 49, xml_generado='<factura>contenido</factura>',
            )
        mock_generar.side_effect = _fake_generar

        self._post()

        mock_send.assert_called_once()
        to_email, subject, body, adjuntos = mock_send.call_args[0]
        nombres = [nombre for nombre, _, _ in adjuntos]
        self.assertEqual(len(adjuntos), 2)
        self.assertTrue(any(n.startswith('factura_') and n.endswith('.pdf') for n in nombres))
        self.assertTrue(any(n.startswith('factura_sri_') and n.endswith('.xml') for n in nombres))
        self.assertFalse(any(n.startswith('ride_') for n in nombres))
        self.assertNotIn('RIDE', body)


class InvoiceWhatsappRecordatorioUrlTests(TestCase):
    """Link 'wa.me' manual (no automatizado) para recordar un pago pendiente."""

    def setUp(self):
        self.customer = Customer.objects.create(
            dni='1700000109', first_name='Ana', last_name='Gómez', phone='+593987654321',
        )

    def test_none_si_cliente_sin_telefono(self):
        customer_sin_telefono = Customer.objects.create(dni='1700000117', first_name='Luis', last_name='Pérez')
        invoice = Invoice.objects.create(
            customer=customer_sin_telefono, total=Decimal('23.00'), saldo=Decimal('23.00'),
            tipo_pago=Invoice.CREDITO, estado=Invoice.PENDIENTE, meses_credito=3,
        )
        self.assertIsNone(invoice.whatsapp_recordatorio_url)

    def test_url_apunta_a_wa_me_con_el_telefono_sin_el_signo_mas(self):
        invoice = Invoice.objects.create(
            customer=self.customer, total=Decimal('23.00'), saldo=Decimal('23.00'),
            tipo_pago=Invoice.CREDITO, estado=Invoice.PENDIENTE, meses_credito=3,
        )
        url = invoice.whatsapp_recordatorio_url
        self.assertTrue(url.startswith('https://wa.me/593987654321?text='))

    def test_mensaje_incluye_datos_de_la_factura(self):
        invoice = Invoice.objects.create(
            customer=self.customer, total=Decimal('23.00'), saldo=Decimal('23.00'),
            tipo_pago=Invoice.CREDITO, estado=Invoice.PENDIENTE, meses_credito=3,
        )
        from urllib.parse import unquote
        mensaje = unquote(invoice.whatsapp_recordatorio_url.split('?text=', 1)[1])
        self.assertIn(self.customer.full_name, mensaje)
        self.assertIn(f'#{invoice.id:04d}', mensaje)
        self.assertIn('23.00', mensaje)


class NotificacionStockBajoIntegracionTests(TestCase):
    """Verifica que invoice_create dispare notificar_stock_bajo (notificaciones/services.py)."""

    def setUp(self):
        self.brand = Brand.objects.create(name='Marca Notif')
        self.group = ProductGroup.objects.create(name='Grupo Notif')
        self.customer = Customer.objects.create(dni='1700000043', first_name='Ana', last_name='Gómez')
        self.product = Product.objects.create(
            name='Producto Notif', brand=self.brand, group=self.group,
            unit_price=Decimal('10'), stock=6, stock_minimo=5,
        )
        self.user = User.objects.create_user('vendedor_notif', password='clave-test-123')
        perms = Permission.objects.filter(
            codename__in=['view_invoice', 'add_invoice', 'view_invoicedetail', 'add_invoicedetail']
        )
        self.user.user_permissions.set(perms)
        self.client.force_login(self.user)
        SesionCaja.objects.create(usuario=self.user, monto_inicial=Decimal('100.00'))

    def _post(self, product, quantity):
        data = {
            'customer': self.customer.id, 'tipo_pago': Invoice.CONTADO, 'forma_pago': Invoice.EFECTIVO,
            'monto_recibido': '1000.00',
            'details-TOTAL_FORMS': '1', 'details-INITIAL_FORMS': '0', 'details-MIN_NUM_FORMS': '0', 'details-MAX_NUM_FORMS': '1000',
            'details-0-id': '', 'details-0-product': product.id, 'details-0-quantity': str(quantity), 'details-0-unit_price': '10.00',
        }
        return self.client.post(reverse('billing:invoice_create'), data)

    def test_vender_por_debajo_del_minimo_crea_notificacion(self):
        self._post(self.product, 2)  # stock queda en 4, por debajo del mínimo de 5
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock, 4)
        self.assertTrue(Notificacion.objects.filter(tipo=Notificacion.STOCK_BAJO, clave=f'stock_bajo:producto:{self.product.id}').exists())

    def test_vender_sin_bajar_del_minimo_no_crea_notificacion(self):
        producto_con_holgura = Product.objects.create(
            name='Producto Notif 2', brand=self.brand, group=self.group,
            unit_price=Decimal('10'), stock=10, stock_minimo=5,
        )
        self._post(producto_con_holgura, 2)  # stock queda en 8, por encima del mínimo
        producto_con_holgura.refresh_from_db()
        self.assertEqual(producto_con_holgura.stock, 8)
        self.assertFalse(Notificacion.objects.filter(tipo=Notificacion.STOCK_BAJO).exists())


class ConfiguracionSistemaIntegracionTests(TestCase):
    """Confirma que cambiar ConfiguracionSistema (configuracion/models.py) cambia
    resultados reales, no solo que la vista de configuración se guarda."""

    def setUp(self):
        self.brand = Brand.objects.create(name='Marca Config')
        self.group = ProductGroup.objects.create(name='Grupo Config')
        self.customer = Customer.objects.create(dni='1700000060', first_name='Ana', last_name='Gómez')
        self.product = Product.objects.create(
            name='Producto Config', brand=self.brand, group=self.group,
            unit_price=Decimal('10'), stock=50,
        )
        self.user = User.objects.create_user('vendedor_config', password='clave-test-123')
        self.user.user_permissions.set(Permission.objects.filter(
            codename__in=['view_invoice', 'add_invoice', 'view_invoicedetail', 'add_invoicedetail']
        ))
        self.client.force_login(self.user)
        SesionCaja.objects.create(usuario=self.user, monto_inicial=Decimal('100.00'))

    def _post(self):
        data = {
            'customer': self.customer.id, 'tipo_pago': Invoice.CONTADO, 'forma_pago': Invoice.EFECTIVO,
            'monto_recibido': '1000.00',
            'details-TOTAL_FORMS': '1', 'details-INITIAL_FORMS': '0', 'details-MIN_NUM_FORMS': '0', 'details-MAX_NUM_FORMS': '1000',
            'details-0-id': '', 'details-0-product': self.product.id, 'details-0-quantity': '1', 'details-0-unit_price': '10.00',
        }
        return self.client.post(reverse('billing:invoice_create'), data)

    def test_cambiar_iva_cambia_el_impuesto_calculado(self):
        config = ConfiguracionSistema.get_solo()
        config.iva_porcentaje = Decimal('10.00')
        config.save()

        self._post()
        invoice = Invoice.objects.get(customer=self.customer)
        # subtotal $10 al 10% = $1.00 (con IVA por defecto de 15% habría sido $1.50)
        self.assertEqual(invoice.tax, Decimal('1.00'))
        self.assertEqual(invoice.total, Decimal('11.00'))

    def test_cambiar_porcentaje_credito_cambia_limite_de_credito(self):
        CustomerProfile.objects.create(customer=self.customer, credit_limit=Decimal('0.00'))
        config = ConfiguracionSistema.get_solo()
        config.credito_porcentaje_por_compras = Decimal('50.00')
        config.save()

        Invoice.objects.create(
            customer=self.customer, total=Decimal('100.00'), saldo=Decimal('0.00'),
            tipo_pago=Invoice.CONTADO, estado=Invoice.PAGADA, forma_pago=Invoice.EFECTIVO,
        )
        # 50% de $100 histórico = $50 (con el 30% por defecto habría sido $30)
        self.assertEqual(self.customer.limite_credito, Decimal('50.00'))


@override_settings(PAYPAL_CLIENT_ID='fake-id', PAYPAL_CLIENT_SECRET='fake-secret')
class InvoicePaypalIntegrationTests(TestCase):
    """Elegir PayPal como forma de pago NO debe crear la Invoice de inmediato
    — solo debe armar la orden en PayPal y redirigir al checkout (ver
    paypal_pagos/services.py -> finalizar_orden, que es quien crea la
    Invoice real una vez que el pago se confirma)."""

    def setUp(self):
        self.brand = Brand.objects.create(name='Marca PP')
        self.group = ProductGroup.objects.create(name='Grupo PP')
        self.customer = Customer.objects.create(dni='1700000102', first_name='Ana', last_name='Gómez')
        self.product = Product.objects.create(
            name='Producto PP', brand=self.brand, group=self.group,
            unit_price=Decimal('10'), stock=50,
        )
        self.user = User.objects.create_user('vendedor_pp', password='clave-test-123')
        self.user.user_permissions.set(Permission.objects.filter(
            codename__in=['view_invoice', 'add_invoice', 'view_invoicedetail', 'add_invoicedetail']
        ))
        self.client.force_login(self.user)

    def _post_paypal(self):
        data = {
            'customer': self.customer.id, 'tipo_pago': Invoice.CONTADO, 'forma_pago': Invoice.PAYPAL,
            'details-TOTAL_FORMS': '1', 'details-INITIAL_FORMS': '0', 'details-MIN_NUM_FORMS': '0', 'details-MAX_NUM_FORMS': '1000',
            'details-0-id': '', 'details-0-product': self.product.id, 'details-0-quantity': '2', 'details-0-unit_price': '10.00',
        }
        return self.client.post(reverse('billing:invoice_create'), data)

    @patch('paypal_pagos.services.crear_orden')
    def test_elegir_paypal_no_crea_invoice_y_redirige_al_checkout(self, mock_crear_orden):
        mock_crear_orden.return_value = ('ORDER1', 'https://paypal.test/approve')
        response = self._post_paypal()
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, 'https://paypal.test/approve')
        self.assertFalse(Invoice.objects.filter(customer=self.customer).exists())

        from paypal_pagos.models import OrdenPaypal
        orden = OrdenPaypal.objects.get(paypal_order_id='ORDER1')
        self.assertEqual(orden.tipo, OrdenPaypal.VENTA)
        self.assertEqual(orden.monto, Decimal('23.00'))
        # el stock tampoco se toca hasta que el pago se confirme
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock, 50)

    @patch('paypal_pagos.services.crear_orden')
    def test_error_de_paypal_muestra_mensaje_y_no_crea_nada(self, mock_crear_orden):
        from paypal_pagos.client import PayPalError
        mock_crear_orden.side_effect = PayPalError('PayPal no responde')
        response = self._post_paypal()
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'PayPal no responde')
        self.assertFalse(Invoice.objects.filter(customer=self.customer).exists())

    def test_paypal_no_configurado_no_aparece_en_las_opciones_del_form(self):
        with override_settings(PAYPAL_CLIENT_ID='', PAYPAL_CLIENT_SECRET=''):
            form = InvoiceForm()
            valores = [c[0] for c in form.fields['forma_pago'].choices]
            self.assertNotIn(Invoice.PAYPAL, valores)


class InvoiceModuleAccessVsViewButtonTests(TestCase):
    """El permiso 'Ver' (view_invoice) ahora controla solo el botón/acceso a
    UNA factura puntual (detalle, PDF) — el acceso al listado completo del
    módulo lo controla un permiso aparte, access_invoice_module. Antes,
    view_invoice controlaba las dos cosas a la vez."""

    def setUp(self):
        self.brand = Brand.objects.create(name='Marca ModAccess')
        self.group = ProductGroup.objects.create(name='Grupo ModAccess')
        self.customer = Customer.objects.create(dni='1700000142', first_name='Ana', last_name='Gómez')
        self.product = Product.objects.create(name='Producto ModAccess', brand=self.brand, group=self.group, unit_price=Decimal('10'), stock=10)
        self.invoice = Invoice.objects.create(
            customer=self.customer, subtotal=Decimal('20'), tax=Decimal('3'), total=Decimal('23'),
            tipo_pago=Invoice.CONTADO, forma_pago=Invoice.EFECTIVO, saldo=Decimal('0'), estado=Invoice.PAGADA,
        )
        from .models import InvoiceDetail
        InvoiceDetail.objects.create(invoice=self.invoice, product=self.product, quantity=2, unit_price=Decimal('10'))

    def _login_con_permisos(self, username, codenames):
        user = User.objects.create_user(username, password='clave-test-123')
        user.user_permissions.set(Permission.objects.filter(codename__in=codenames))
        self.client.force_login(user)
        return user

    def test_sin_access_invoice_module_no_puede_entrar_al_listado(self):
        # Tiene view_invoice (podría ver una factura puntual) pero no
        # access_invoice_module: el listado completo debe quedar bloqueado.
        self._login_con_permisos('solo_ver_una_factura', ['view_invoice'])
        response = self.client.get(reverse('billing:invoice_list'))
        self.assertEqual(response.status_code, 302)  # redirige, no se le deja entrar

    def test_con_access_invoice_module_puede_entrar_al_listado(self):
        self._login_con_permisos('con_acceso_modulo', ['access_invoice_module'])
        response = self.client.get(reverse('billing:invoice_list'))
        self.assertEqual(response.status_code, 200)

    def test_sin_view_invoice_el_boton_ver_no_aparece_aunque_tenga_acceso_al_modulo(self):
        # Puede entrar al listado (access_invoice_module) pero no tiene
        # view_invoice: el botón "Ver" de cada fila no debe aparecer.
        self._login_con_permisos('acceso_modulo_sin_ver', ['access_invoice_module'])
        response = self.client.get(reverse('billing:invoice_list'))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, reverse('billing:invoice_detail', args=[self.invoice.pk]))

    def test_sin_view_invoice_no_puede_abrir_el_detalle_directamente(self):
        self._login_con_permisos('acceso_modulo_sin_ver_2', ['access_invoice_module'])
        response = self.client.get(reverse('billing:invoice_detail', args=[self.invoice.pk]))
        self.assertEqual(response.status_code, 302)

    def test_con_ambos_permisos_ve_el_listado_y_el_boton_ver(self):
        self._login_con_permisos('ambos_permisos', ['access_invoice_module', 'view_invoice'])
        response = self.client.get(reverse('billing:invoice_list'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, reverse('billing:invoice_detail', args=[self.invoice.pk]))
        detail_response = self.client.get(reverse('billing:invoice_detail', args=[self.invoice.pk]))
        self.assertEqual(detail_response.status_code, 200)


class InvoiceExportAndWhatsappPermissionTests(TestCase):
    """Los botones de exportar PDF/Excel y el 'Recordar' por WhatsApp ahora
    exigen su propio permiso (export_pdf_invoice/export_excel_invoice/
    send_whatsapp_invoice), separado del que da acceso al listado."""

    def setUp(self):
        self.customer = Customer.objects.create(dni='1700000159', first_name='Ana', last_name='Gómez', phone='+593987654321')
        self.invoice = Invoice.objects.create(
            customer=self.customer, subtotal=Decimal('20'), tax=Decimal('3'), total=Decimal('23'),
            tipo_pago=Invoice.CONTADO, forma_pago=Invoice.EFECTIVO, saldo=Decimal('0'), estado=Invoice.PAGADA,
        )

    def _login_con_permisos(self, username, codenames):
        user = User.objects.create_user(username, password='clave-test-123')
        user.user_permissions.set(Permission.objects.filter(codename__in=codenames))
        self.client.force_login(user)
        return user

    def test_exportar_pdf_sin_permiso_no_muestra_boton_y_la_vista_lo_rechaza(self):
        self._login_con_permisos('sin_export', ['access_invoice_module'])
        response = self.client.get(reverse('billing:invoice_list'))
        self.assertNotContains(response, 'value="pdf"')
        export_response = self.client.get(reverse('billing:invoice_list'), {'export': 'pdf'})
        self.assertNotEqual(export_response['Content-Type'], 'application/pdf')
        self.assertContains(export_response, 'No tienes permiso para exportar')

    def test_exportar_pdf_con_permiso_funciona(self):
        self._login_con_permisos('con_export_pdf', ['access_invoice_module', 'export_pdf_invoice'])
        response = self.client.get(reverse('billing:invoice_list'), {'export': 'pdf'})
        self.assertEqual(response['Content-Type'], 'application/pdf')

    def test_exportar_excel_con_permiso_funciona(self):
        self._login_con_permisos('con_export_excel', ['access_invoice_module', 'export_excel_invoice'])
        response = self.client.get(reverse('billing:invoice_list'), {'export': 'excel'})
        self.assertEqual(
            response['Content-Type'],
            'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        )

    def test_boton_recordar_whatsapp_exige_permiso_propio(self):
        # make_invoice helper de cobros/tests.py no aplica acá (es billing) —
        # se arma una factura a crédito directo, mismo patrón que otros tests.
        credito = Invoice.objects.create(
            customer=self.customer, subtotal=Decimal('20'), tax=Decimal('3'), total=Decimal('23'),
            tipo_pago=Invoice.CREDITO, saldo=Decimal('23'), estado=Invoice.PENDIENTE, meses_credito=3,
        )
        # El botón es solo-ícono (con tooltip) desde el rediseño de interfaz,
        # así que se verifica por el link a wa.me (su destino real) en vez
        # de un texto visible.
        self._login_con_permisos('sin_whatsapp', ['access_cobrofactura_module'])
        response = self.client.get(reverse('cobros:invoice_pending_list'))
        self.assertNotContains(response, 'wa.me')

        self._login_con_permisos('con_whatsapp', ['access_cobrofactura_module', 'send_whatsapp_invoice'])
        response2 = self.client.get(reverse('cobros:invoice_pending_list'))
        self.assertContains(response2, 'wa.me')


class InvoiceTarjetaModelTests(TestCase):
    """Espejo de InvoiceFormaPagoModelTests para la forma de pago 'tarjeta'
    (captura informativa, sin pasarela real — ver comentario junto a
    Invoice.FORMA_PAGO_CHOICES)."""

    def setUp(self):
        self.customer = Customer.objects.create(dni='1700000060', first_name='Ana', last_name='Gómez')

    def test_tarjeta_esta_en_forma_pago_choices(self):
        self.assertIn(Invoice.TARJETA, dict(Invoice.FORMA_PAGO_CHOICES))

    def test_contado_con_tarjeta_y_datos_es_valido(self):
        invoice = Invoice(
            customer=self.customer, total=Decimal('100'), tipo_pago=Invoice.CONTADO,
            forma_pago=Invoice.TARJETA, tarjeta_titular='Ana Gómez',
            tarjeta_cvv='1234', tarjeta_expiracion=date.today() + timedelta(days=365),
        )
        invoice.full_clean()  # no debe lanzar

    def test_tarjeta_no_genera_cambio(self):
        invoice = Invoice(
            customer=self.customer, total=Decimal('100'), tipo_pago=Invoice.CONTADO,
            forma_pago=Invoice.TARJETA,
        )
        self.assertIsNone(invoice.cambio)


class InvoiceFormTarjetaValidationTests(TestCase):
    """Espejo de InvoiceFormMesesCreditoTests — cada regla de tarjeta se
    valida en InvoiceForm.clean(), nunca llega a _finalizar_venta() si algo
    falta o está mal formado."""

    def setUp(self):
        self.customer = Customer.objects.create(dni='1700000061', first_name='Ana', last_name='Gómez')

    def _data(self, **overrides):
        data = {
            'customer': self.customer.id, 'tipo_pago': Invoice.CONTADO, 'forma_pago': Invoice.TARJETA,
            'tarjeta_titular': 'Ana Gómez', 'tarjeta_cvv': '1234',
            'tarjeta_expiracion': (date.today() + timedelta(days=365)).isoformat(),
        }
        data.update(overrides)
        return data

    def test_form_tarjeta_con_datos_completos_es_valido(self):
        form = InvoiceForm(data=self._data())
        self.assertTrue(form.is_valid(), form.errors)

    def test_form_tarjeta_con_cvv_de_3_digitos_es_valido(self):
        form = InvoiceForm(data=self._data(tarjeta_cvv='123'))
        self.assertTrue(form.is_valid(), form.errors)

    def test_form_tarjeta_sin_titular_muestra_error(self):
        form = InvoiceForm(data=self._data(tarjeta_titular=''))
        self.assertFalse(form.is_valid())
        self.assertIn('tarjeta_titular', form.errors)

    def test_form_tarjeta_con_cvv_no_numerico_muestra_error(self):
        form = InvoiceForm(data=self._data(tarjeta_cvv='12ab'))
        self.assertFalse(form.is_valid())
        self.assertIn('tarjeta_cvv', form.errors)

    def test_form_tarjeta_con_cvv_de_largo_incorrecto_muestra_error(self):
        form = InvoiceForm(data=self._data(tarjeta_cvv='12'))
        self.assertFalse(form.is_valid())
        self.assertIn('tarjeta_cvv', form.errors)

    def test_form_tarjeta_sin_expiracion_muestra_error(self):
        form = InvoiceForm(data=self._data(tarjeta_expiracion=''))
        self.assertFalse(form.is_valid())
        self.assertIn('tarjeta_expiracion', form.errors)

    def test_form_tarjeta_con_expiracion_vencida_muestra_error(self):
        form = InvoiceForm(data=self._data(
            tarjeta_expiracion=(date.today() - timedelta(days=1)).isoformat()
        ))
        self.assertFalse(form.is_valid())
        self.assertIn('tarjeta_expiracion', form.errors)


class InvoiceCreateViewTarjetaTests(TestCase):
    """Espejo de CajaIntegracionInvoiceTests: tarjeta también exige caja
    abierta (decisión explícita del usuario — toda venta de mostrador, sea
    efectivo o tarjeta, ocurre durante un turno de caja abierto), pero a
    diferencia de efectivo NUNCA genera un MovimientoCaja (el dinero no
    entra físicamente a la caja, va a un datáfono externo)."""

    def setUp(self):
        self.brand = Brand.objects.create(name='Marca Tarjeta')
        self.group = ProductGroup.objects.create(name='Grupo Tarjeta')
        self.customer = Customer.objects.create(dni='1700000062', first_name='Ana', last_name='Gómez')
        self.product = Product.objects.create(
            name='Producto Tarjeta', brand=self.brand, group=self.group, unit_price=Decimal('10'), stock=50
        )
        self.user = User.objects.create_user('cajero_tarjeta', password='clave-test-123')
        perms = Permission.objects.filter(
            codename__in=['view_invoice', 'add_invoice', 'view_invoicedetail', 'add_invoicedetail']
        )
        self.user.user_permissions.set(perms)
        self.client.force_login(self.user)

    def _post_tarjeta(self, **overrides):
        data = {
            'customer': self.customer.id, 'tipo_pago': Invoice.CONTADO, 'forma_pago': Invoice.TARJETA,
            'tarjeta_titular': 'Ana Gómez', 'tarjeta_cvv': '1234',
            'tarjeta_expiracion': (date.today() + timedelta(days=365)).isoformat(),
            'details-TOTAL_FORMS': '1', 'details-INITIAL_FORMS': '0', 'details-MIN_NUM_FORMS': '0', 'details-MAX_NUM_FORMS': '1000',
            'details-0-id': '', 'details-0-product': self.product.id, 'details-0-quantity': '2', 'details-0-unit_price': '10.00',
        }
        data.update(overrides)
        return self.client.post(reverse('billing:invoice_create'), data)

    def test_venta_con_tarjeta_sin_caja_abierta_es_bloqueada(self):
        response = self._post_tarjeta()
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Invoice.objects.filter(customer=self.customer).exists())

    def test_venta_con_tarjeta_con_caja_abierta_se_crea_pagada_sin_movimiento(self):
        sesion = SesionCaja.objects.create(usuario=self.user, monto_inicial=Decimal('100.00'))
        response = self._post_tarjeta()
        self.assertEqual(response.status_code, 302)
        invoice = Invoice.objects.get(customer=self.customer)
        self.assertEqual(invoice.estado, Invoice.PAGADA)
        self.assertEqual(invoice.forma_pago, Invoice.TARJETA)
        self.assertEqual(invoice.tarjeta_titular, 'Ana Gómez')
        self.assertEqual(invoice.tarjeta_cvv, '1234')
        self.assertEqual(sesion.movimientos.count(), 0)

    def test_venta_con_tarjeta_datos_invalidos_no_crea_nada(self):
        sesion = SesionCaja.objects.create(usuario=self.user, monto_inicial=Decimal('100.00'))
        response = self._post_tarjeta(tarjeta_cvv='abc')
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Invoice.objects.filter(customer=self.customer).exists())
        self.assertEqual(sesion.movimientos.count(), 0)


class CustomerQuickCreateViewTests(TestCase):
    """Endpoint AJAX del botón '+ Nuevo cliente' del paso 1 del wizard de
    factura (ver static/js/invoice-wizard.js)."""

    def setUp(self):
        self.user = User.objects.create_user('vendedor_quickcreate', password='clave-test-123')
        self.user.user_permissions.set(Permission.objects.filter(codename='add_customer'))
        self.client.force_login(self.user)

    def test_post_valido_crea_cliente_y_responde_201(self):
        # '1700000076' es una cédula con dígito verificador válido (mismo
        # algoritmo que shared.validators.validate_cedula_ec) — a diferencia
        # de los Customer.objects.create() directos de otros tests de este
        # archivo, este endpoint sí corre full_clean() vía ModelForm.
        response = self.client.post(reverse('billing:customer_quick_create'), {
            'tipo_identificacion': 'cedula', 'dni': '1700000076', 'first_name': 'Luis', 'last_name': 'Pérez',
            'email': 'luis@example.com', 'phone': '', 'address': '',
        })
        self.assertEqual(response.status_code, 201)
        payload = response.json()
        self.assertTrue(payload['ok'])
        self.assertEqual(payload['customer']['dni'], '1700000076')
        self.assertEqual(payload['customer']['tipo_identificacion'], 'cedula')
        self.assertTrue(Customer.objects.filter(dni='1700000076').exists())

    def test_post_valido_con_ruc_crea_cliente(self):
        response = self.client.post(reverse('billing:customer_quick_create'), {
            'tipo_identificacion': 'ruc', 'dni': '1700000076001', 'first_name': 'Empresa', 'last_name': 'S.A.',
        })
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()['customer']['tipo_identificacion'], 'ruc')

    def test_post_valido_con_pasaporte_crea_cliente(self):
        # El pasaporte es alfanumérico — no pasaría validate_cedula_ec, por
        # eso necesita su propio tipo_identificacion para usar
        # validate_pasaporte en Customer.clean() en su lugar.
        response = self.client.post(reverse('billing:customer_quick_create'), {
            'tipo_identificacion': 'pasaporte', 'dni': 'AB123456', 'first_name': 'John', 'last_name': 'Doe',
        })
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()['customer']['tipo_identificacion'], 'pasaporte')

    def test_post_pasaporte_invalido_responde_400(self):
        response = self.client.post(reverse('billing:customer_quick_create'), {
            'tipo_identificacion': 'pasaporte', 'dni': 'ab', 'first_name': 'John', 'last_name': 'Doe',
        })
        self.assertEqual(response.status_code, 400)
        self.assertFalse(Customer.objects.filter(dni='ab').exists())

    def test_post_invalido_responde_400_sin_crear_nada(self):
        response = self.client.post(reverse('billing:customer_quick_create'), {
            'tipo_identificacion': 'cedula', 'dni': 'no-es-una-cedula-valida', 'first_name': '', 'last_name': '',
        })
        self.assertEqual(response.status_code, 400)
        payload = response.json()
        self.assertFalse(payload['ok'])
        self.assertFalse(Customer.objects.filter(dni='no-es-una-cedula-valida').exists())

    def test_usuario_sin_permiso_queda_bloqueado(self):
        user_sin_permiso = User.objects.create_user('sin_permiso_quickcreate', password='clave-test-123')
        self.client.force_login(user_sin_permiso)
        response = self.client.post(reverse('billing:customer_quick_create'), {
            'tipo_identificacion': 'cedula', 'dni': '1700000071', 'first_name': 'Luis', 'last_name': 'Pérez',
        })
        # permission_required_redirect redirige (no crea el cliente) en vez
        # de responder 403 — mismo criterio que el resto de vistas FBV del
        # archivo, ver shared/decorators.py.
        self.assertEqual(response.status_code, 302)
        self.assertFalse(Customer.objects.filter(dni='1700000071').exists())


class SupplierQuickCreateViewTests(TestCase):
    """Endpoint AJAX del botón '+ Nuevo proveedor' del paso 1 del wizard de
    compra (ver static/js/purchase-wizard.js) — mismo patrón exacto que
    CustomerQuickCreateViewTests de arriba."""

    def setUp(self):
        self.user = User.objects.create_user('comprador_quickcreate', password='clave-test-123')
        self.user.user_permissions.set(Permission.objects.filter(codename='add_supplier'))
        self.client.force_login(self.user)

    def test_post_valido_crea_proveedor_y_responde_201(self):
        response = self.client.post(reverse('billing:supplier_quick_create'), {
            'name': 'Distribuidora Test', 'contact_name': 'Juan Pérez',
            'email': 'juan@example.com', 'phone': '', 'address': '',
        })
        self.assertEqual(response.status_code, 201)
        payload = response.json()
        self.assertTrue(payload['ok'])
        self.assertEqual(payload['supplier']['name'], 'Distribuidora Test')
        self.assertTrue(Supplier.objects.filter(name='Distribuidora Test').exists())

    def test_post_invalido_responde_400_sin_crear_nada(self):
        response = self.client.post(reverse('billing:supplier_quick_create'), {
            'name': '', 'contact_name': '', 'email': 'no-es-un-email',
        })
        self.assertEqual(response.status_code, 400)
        payload = response.json()
        self.assertFalse(payload['ok'])
        self.assertFalse(Supplier.objects.filter(email='no-es-un-email').exists())

    def test_usuario_sin_permiso_queda_bloqueado(self):
        user_sin_permiso = User.objects.create_user('sin_permiso_quickcreate_supplier', password='clave-test-123')
        self.client.force_login(user_sin_permiso)
        response = self.client.post(reverse('billing:supplier_quick_create'), {
            'name': 'Distribuidora Bloqueada',
        })
        self.assertEqual(response.status_code, 302)
        self.assertFalse(Supplier.objects.filter(name='Distribuidora Bloqueada').exists())
