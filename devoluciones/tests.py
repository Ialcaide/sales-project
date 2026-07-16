from decimal import Decimal

from django.contrib.auth.models import Permission, User
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from billing.models import Brand, Customer, Invoice, InvoiceDetail, Product, ProductGroup
from caja.models import MovimientoCaja, SesionCaja

from .models import DevolucionDetalle, DevolucionVenta, registrar_devolucion


def make_invoice_with_detail(quantity=5, unit_price='10.00', tipo_pago=Invoice.CONTADO,
                              forma_pago=Invoice.EFECTIVO, saldo='0.00', estado=Invoice.PAGADA):
    brand = Brand.objects.create(name='Marca Test Dev')
    group = ProductGroup.objects.create(name='Grupo Test Dev')
    customer = Customer.objects.create(dni='1234567890', first_name='Ana', last_name='Gómez')
    product = Product.objects.create(
        name='Producto Test Dev', brand=brand, group=group,
        unit_price=Decimal(unit_price), stock=100,
    )
    subtotal = Decimal(unit_price) * quantity
    tax = (subtotal * Decimal('0.15')).quantize(Decimal('0.01'))
    invoice = Invoice.objects.create(
        customer=customer, subtotal=subtotal, tax=tax, total=subtotal + tax,
        tipo_pago=tipo_pago, forma_pago=forma_pago, saldo=Decimal(saldo), estado=estado,
    )
    detail = InvoiceDetail.objects.create(invoice=invoice, product=product, quantity=quantity, unit_price=Decimal(unit_price))
    return invoice, detail, product


class DevolucionDetalleModelTests(TestCase):
    def test_no_se_puede_devolver_mas_de_lo_vendido(self):
        invoice, detail, product = make_invoice_with_detail(quantity=5)
        devolucion = DevolucionVenta.objects.create(factura=invoice, motivo='Prueba', usuario=User.objects.create_user('u1'))
        detalle = DevolucionDetalle(devolucion=devolucion, invoice_detail=detail, quantity=6)
        with self.assertRaises(ValidationError):
            detalle.full_clean()

    def test_cantidad_ya_devuelta_se_descuenta_del_disponible(self):
        invoice, detail, product = make_invoice_with_detail(quantity=5)
        user = User.objects.create_user('u2')
        devolucion1 = DevolucionVenta.objects.create(factura=invoice, motivo='Prueba', usuario=user)
        DevolucionDetalle.objects.create(devolucion=devolucion1, invoice_detail=detail, quantity=3)

        devolucion2 = DevolucionVenta.objects.create(factura=invoice, motivo='Prueba 2', usuario=user)
        detalle2 = DevolucionDetalle(devolucion=devolucion2, invoice_detail=detail, quantity=3)
        with self.assertRaises(ValidationError):
            detalle2.full_clean()  # ya se devolvieron 3 de 5, solo quedan 2 disponibles

    def test_cantidad_cero_o_negativa_rechazada(self):
        invoice, detail, product = make_invoice_with_detail(quantity=5)
        devolucion = DevolucionVenta.objects.create(factura=invoice, motivo='Prueba', usuario=User.objects.create_user('u3'))
        for qty in (0, -1):
            detalle = DevolucionDetalle(devolucion=devolucion, invoice_detail=detail, quantity=qty)
            with self.assertRaises(ValidationError):
                detalle.full_clean()


class RegistrarDevolucionTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('u4')

    def test_aumenta_stock_y_reduce_total_de_la_factura(self):
        invoice, detail, product = make_invoice_with_detail(quantity=5, unit_price='10.00')
        stock_antes = product.stock
        total_antes = invoice.total

        devolucion = registrar_devolucion(
            factura=invoice, motivo='Producto defectuoso', usuario=self.user,
            lineas=[(detail, 2)],
        )

        product.refresh_from_db()
        invoice.refresh_from_db()
        self.assertEqual(product.stock, stock_antes + 2)
        # 2 unidades x $10 = $20 subtotal + 15% IVA = $23
        self.assertEqual(devolucion.total, Decimal('23.00'))
        self.assertEqual(invoice.total, total_antes - Decimal('23.00'))

    def test_reduce_saldo_de_factura_a_credito(self):
        invoice, detail, product = make_invoice_with_detail(
            quantity=5, unit_price='10.00', tipo_pago=Invoice.CREDITO, forma_pago=None,
            saldo='57.50', estado=Invoice.PENDIENTE,
        )
        registrar_devolucion(factura=invoice, motivo='Talla incorrecta', usuario=self.user, lineas=[(detail, 2)])
        invoice.refresh_from_db()
        self.assertEqual(invoice.saldo, Decimal('34.50'))  # 57.50 - 23.00
        self.assertEqual(invoice.estado, Invoice.PENDIENTE)

    def test_factura_credito_queda_pagada_si_saldo_llega_a_cero(self):
        invoice, detail, product = make_invoice_with_detail(
            quantity=5, unit_price='10.00', tipo_pago=Invoice.CREDITO, forma_pago=None,
            saldo='23.00', estado=Invoice.PENDIENTE,
        )
        registrar_devolucion(factura=invoice, motivo='Devolución total', usuario=self.user, lineas=[(detail, 2)])
        invoice.refresh_from_db()
        self.assertEqual(invoice.saldo, Decimal('0.00'))
        self.assertEqual(invoice.estado, Invoice.PAGADA)

    def test_registra_egreso_en_caja_abierta_si_fue_efectivo(self):
        invoice, detail, product = make_invoice_with_detail(quantity=5, unit_price='10.00', forma_pago=Invoice.EFECTIVO)
        sesion = SesionCaja.objects.create(usuario=self.user, monto_inicial=Decimal('100.00'))

        registrar_devolucion(
            factura=invoice, motivo='Prueba', usuario=self.user, lineas=[(detail, 2)], sesion_caja=sesion,
        )
        self.assertEqual(sesion.movimientos.count(), 1)
        movimiento = sesion.movimientos.first()
        self.assertEqual(movimiento.tipo, MovimientoCaja.EGRESO)
        self.assertEqual(movimiento.monto, Decimal('23.00'))

    def test_no_registra_egreso_si_no_hay_caja_abierta(self):
        invoice, detail, product = make_invoice_with_detail(quantity=5, unit_price='10.00', forma_pago=Invoice.EFECTIVO)
        registrar_devolucion(factura=invoice, motivo='Prueba', usuario=self.user, lineas=[(detail, 2)], sesion_caja=None)
        self.assertEqual(MovimientoCaja.objects.count(), 0)

    def test_no_se_puede_devolver_sobre_factura_anulada(self):
        invoice, detail, product = make_invoice_with_detail(quantity=5)
        invoice.is_active = False
        invoice.save(update_fields=['is_active'])
        with self.assertRaises(ValidationError):
            registrar_devolucion(factura=invoice, motivo='Prueba', usuario=self.user, lineas=[(detail, 1)])

    def test_sin_lineas_es_invalido(self):
        invoice, detail, product = make_invoice_with_detail(quantity=5)
        with self.assertRaises(ValidationError):
            registrar_devolucion(factura=invoice, motivo='Prueba', usuario=self.user, lineas=[])

    def test_usa_la_tasa_de_iva_real_de_la_factura_no_la_configurada_hoy(self):
        # La factura se emitió con 20% de IVA (subtotal $50, tax $10) — si el
        # administrador después cambia ConfiguracionSistema a otro %, la
        # devolución de ESTA factura debe seguir usando su propio 20%, no el
        # valor configurado hoy (ver devoluciones/models.py -> registrar_devolucion).
        invoice, detail, product = make_invoice_with_detail(quantity=5, unit_price='10.00')
        invoice.subtotal = Decimal('50.00')
        invoice.tax = Decimal('10.00')  # 20% real
        invoice.total = Decimal('60.00')
        invoice.save()

        from configuracion.models import ConfiguracionSistema
        config = ConfiguracionSistema.get_solo()
        config.iva_porcentaje = Decimal('8.00')
        config.save()

        devolucion = registrar_devolucion(factura=invoice, motivo='Prueba', usuario=self.user, lineas=[(detail, 2)])
        # 2 unidades x $10 = $20 subtotal devuelto; al 20% real = $4 de IVA -> $24 total
        self.assertEqual(devolucion.total, Decimal('24.00'))


class DevolucionViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('vendedor_dev', password='clave-test-123')
        perms = Permission.objects.filter(
            codename__in=['view_devolucionventa', 'add_devolucionventa', 'view_invoice']
        )
        self.user.user_permissions.set(perms)
        self.client.force_login(self.user)

    def test_devolucion_create_registra_correctamente(self):
        invoice, detail, product = make_invoice_with_detail(quantity=5, unit_price='10.00')
        url = reverse('devoluciones:devolucion_create', args=[invoice.pk])
        response = self.client.post(url, {
            'motivo': 'Producto en mal estado',
            f'cantidad_{detail.id}': '2',
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(DevolucionVenta.objects.filter(factura=invoice).count(), 1)
        product.refresh_from_db()
        self.assertEqual(product.stock, 102)

    def test_devolucion_sin_motivo_no_se_guarda(self):
        invoice, detail, product = make_invoice_with_detail(quantity=5, unit_price='10.00')
        url = reverse('devoluciones:devolucion_create', args=[invoice.pk])
        response = self.client.post(url, {'motivo': '', f'cantidad_{detail.id}': '2'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(DevolucionVenta.objects.filter(factura=invoice).count(), 0)

    def test_devolucion_bloqueada_en_factura_anulada(self):
        invoice, detail, product = make_invoice_with_detail(quantity=5)
        invoice.is_active = False
        invoice.save(update_fields=['is_active'])
        url = reverse('devoluciones:devolucion_create', args=[invoice.pk])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 302)

    def test_usuario_sin_permiso_es_redirigido(self):
        self.client.logout()
        other = User.objects.create_user('sinpermiso_dev', password='clave-test-123')
        self.client.force_login(other)
        response = self.client.get(reverse('devoluciones:devolucion_list'))
        self.assertEqual(response.status_code, 302)
