from decimal import Decimal

from django.contrib.auth.models import Permission, User
from django.test import TestCase
from django.urls import reverse

from billing.models import Brand, Customer, Invoice, Product, ProductGroup, Supplier
from caja.models import SesionCaja
from purchasing.models import Purchase


class ReportesPermisosTests(TestCase):
    def setUp(self):
        self.contador = User.objects.create_user('contador_test', password='clave-test-123')
        perms = Permission.objects.filter(codename__in=[
            'view_invoice', 'view_purchase', 'view_product', 'view_sesioncaja',
        ])
        self.contador.user_permissions.set(perms)

        self.vendedor = User.objects.create_user('vendedor_test', password='clave-test-123')
        self.vendedor.user_permissions.set(
            Permission.objects.filter(codename__in=['view_invoice', 'add_invoice'])
        )

    def test_contador_accede_a_los_4_reportes(self):
        self.client.force_login(self.contador)
        for url_name in ['reporte_index', 'reporte_ventas', 'reporte_compras', 'reporte_inventario', 'reporte_caja']:
            response = self.client.get(reverse(f'reportes:{url_name}'))
            self.assertEqual(response.status_code, 200, f'{url_name} debería ser accesible')

    def test_usuario_sin_permiso_de_compras_es_redirigido(self):
        self.client.force_login(self.vendedor)
        response = self.client.get(reverse('reportes:reporte_compras'))
        self.assertEqual(response.status_code, 302)

    def test_usuario_sin_permiso_de_caja_es_redirigido(self):
        self.client.force_login(self.vendedor)
        response = self.client.get(reverse('reportes:reporte_caja'))
        self.assertEqual(response.status_code, 302)

    def test_anonimo_es_redirigido_al_login(self):
        response = self.client.get(reverse('reportes:reporte_index'))
        self.assertEqual(response.status_code, 302)


class ReporteVentasTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('reportes_ventas', password='clave-test-123')
        self.user.user_permissions.set(Permission.objects.filter(codename='view_invoice'))
        self.client.force_login(self.user)

        self.customer = Customer.objects.create(dni='1700000051', first_name='Ana', last_name='Gómez')

    def test_totales_por_tipo_de_pago(self):
        Invoice.objects.create(
            customer=self.customer, total=Decimal('100.00'), saldo=Decimal('0.00'),
            tipo_pago=Invoice.CONTADO, estado=Invoice.PAGADA, forma_pago=Invoice.EFECTIVO,
        )
        Invoice.objects.create(
            customer=self.customer, total=Decimal('50.00'), saldo=Decimal('50.00'),
            tipo_pago=Invoice.CREDITO, estado=Invoice.PENDIENTE,
        )
        # anulada: no debe contarse
        Invoice.objects.create(
            customer=self.customer, total=Decimal('999.00'), saldo=Decimal('0.00'),
            tipo_pago=Invoice.CONTADO, estado=Invoice.PAGADA, forma_pago=Invoice.EFECTIVO, is_active=False,
        )

        response = self.client.get(reverse('reportes:reporte_ventas'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['total_general'], Decimal('150.00'))
        por_tipo = {row['tipo_pago']: row for row in response.context['por_tipo_pago']}
        self.assertEqual(por_tipo[Invoice.CONTADO]['total'], Decimal('100.00'))
        self.assertEqual(por_tipo[Invoice.CREDITO]['total'], Decimal('50.00'))

    def test_export_pdf_devuelve_content_type_correcto(self):
        Invoice.objects.create(
            customer=self.customer, total=Decimal('10.00'), saldo=Decimal('0.00'),
            tipo_pago=Invoice.CONTADO, estado=Invoice.PAGADA, forma_pago=Invoice.EFECTIVO,
        )
        response = self.client.get(reverse('reportes:reporte_ventas'), {'export': 'pdf'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/pdf')

    def test_export_excel_devuelve_content_type_correcto(self):
        Invoice.objects.create(
            customer=self.customer, total=Decimal('10.00'), saldo=Decimal('0.00'),
            tipo_pago=Invoice.CONTADO, estado=Invoice.PAGADA, forma_pago=Invoice.EFECTIVO,
        )
        response = self.client.get(reverse('reportes:reporte_ventas'), {'export': 'excel'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response['Content-Type'],
            'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        )


class ReporteComprasTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('reportes_compras', password='clave-test-123')
        self.user.user_permissions.set(Permission.objects.filter(codename='view_purchase'))
        self.client.force_login(self.user)
        self.supplier = Supplier.objects.create(name='Proveedor Reportes')

    def test_totales_por_proveedor(self):
        Purchase.objects.create(
            supplier=self.supplier, document_number='R-001', total=Decimal('300.00'),
            tipo_pago=Purchase.CONTADO, estado=Purchase.PAGADA,
        )
        Purchase.objects.create(
            supplier=self.supplier, document_number='R-002', total=Decimal('200.00'),
            tipo_pago=Purchase.CONTADO, estado=Purchase.PAGADA,
        )
        response = self.client.get(reverse('reportes:reporte_compras'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['total_general'], Decimal('500.00'))
        por_proveedor = list(response.context['por_proveedor'])
        self.assertEqual(por_proveedor[0]['total'], Decimal('500.00'))


class ReporteInventarioTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('reportes_inv', password='clave-test-123')
        self.user.user_permissions.set(Permission.objects.filter(codename='view_product'))
        self.client.force_login(self.user)
        self.brand = Brand.objects.create(name='Marca Reportes')
        self.group = ProductGroup.objects.create(name='Grupo Reportes')

    def test_valor_total_de_inventario(self):
        Product.objects.create(
            name='Producto A', brand=self.brand, group=self.group,
            unit_price=Decimal('10.00'), stock=5, stock_minimo=10,
        )
        Product.objects.create(
            name='Producto B', brand=self.brand, group=self.group,
            unit_price=Decimal('20.00'), stock=3, stock_minimo=1,
        )
        response = self.client.get(reverse('reportes:reporte_inventario'))
        self.assertEqual(response.status_code, 200)
        # 5*10 + 3*20 = 110
        self.assertEqual(response.context['valor_total'], Decimal('110.00'))
        bajo_stock = list(response.context['bajo_stock'])
        self.assertEqual(len(bajo_stock), 1)
        self.assertEqual(bajo_stock[0].name, 'Producto A')


class ReporteCajaTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('reportes_caja', password='clave-test-123')
        self.user.user_permissions.set(Permission.objects.filter(codename='view_sesioncaja'))
        self.client.force_login(self.user)
        self.cajero = User.objects.create_user('cajero_reportes', password='clave-test-123')

    def test_totales_ingresos_egresos_diferencia(self):
        s1 = SesionCaja.objects.create(usuario=self.cajero, monto_inicial=Decimal('100.00'))
        s1.monto_contado_cierre = Decimal('95.00')
        s1.estado = SesionCaja.CERRADA
        s1.save()

        response = self.client.get(reverse('reportes:reporte_caja'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['total_diferencia'], Decimal('-5.00'))
        por_cajero = {row['usuario']: row for row in response.context['por_cajero']}
        self.assertEqual(por_cajero['cajero_reportes']['diferencia_total'], Decimal('-5.00'))
