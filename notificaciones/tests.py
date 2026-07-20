from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth.models import Permission, User
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from billing.models import Brand, Customer, CustomerProfile, Invoice, Product, ProductGroup, Supplier
from caja.models import SesionCaja
from purchasing.models import Purchase

from .models import Notificacion
from .services import (
    notificar_caja_diferencia,
    notificar_stock_bajo,
    sincronizar_pagos_pendientes,
    sincronizar_productos_por_vencer,
)


class NotificacionModelTests(TestCase):
    def test_dedup_por_clave_mientras_no_leida(self):
        Notificacion.objects.create(tipo=Notificacion.STOCK_BAJO, mensaje='a', clave='x')
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Notificacion.objects.create(tipo=Notificacion.STOCK_BAJO, mensaje='b', clave='x')

    def test_se_puede_recrear_clave_una_vez_leida(self):
        n = Notificacion.objects.create(tipo=Notificacion.STOCK_BAJO, mensaje='a', clave='x')
        n.leida = True
        n.save()
        # no debe explotar: la constraint solo aplica a leida=False
        Notificacion.objects.create(tipo=Notificacion.STOCK_BAJO, mensaje='b', clave='x')
        self.assertEqual(Notificacion.objects.filter(clave='x').count(), 2)


class NotificarStockBajoTests(TestCase):
    def setUp(self):
        brand = Brand.objects.create(name='Marca')
        group = ProductGroup.objects.create(name='Grupo')
        self.product = Product.objects.create(
            name='Producto', brand=brand, group=group,
            unit_price=Decimal('10'), stock=10, stock_minimo=5,
        )

    def test_no_notifica_si_stock_esta_por_encima_del_minimo(self):
        self.product.stock = 6
        self.product.save()
        self.assertIsNone(notificar_stock_bajo(self.product))
        self.assertEqual(Notificacion.objects.count(), 0)

    def test_notifica_warning_si_stock_llega_al_minimo(self):
        self.product.stock = 5
        self.product.save()
        n = notificar_stock_bajo(self.product)
        self.assertIsNotNone(n)
        self.assertEqual(n.nivel, Notificacion.WARNING)

    def test_notifica_danger_si_stock_queda_en_cero(self):
        self.product.stock = 0
        self.product.save()
        n = notificar_stock_bajo(self.product)
        self.assertEqual(n.nivel, Notificacion.DANGER)

    def test_no_duplica_mientras_siga_sin_leerse(self):
        self.product.stock = 0
        self.product.save()
        notificar_stock_bajo(self.product)
        notificar_stock_bajo(self.product)
        self.assertEqual(Notificacion.objects.filter(tipo=Notificacion.STOCK_BAJO).count(), 1)


class CrearSiNoExisteEnviaTelegramTests(TestCase):
    """Las 4 alertas internas (stock bajo, caja, producto por vencer, pago
    pendiente) pasan todas por _crear_si_no_existe() — probar acá alcanza
    para cubrir la integración con Telegram sin repetirla en cada función."""

    def setUp(self):
        brand = Brand.objects.create(name='Marca')
        group = ProductGroup.objects.create(name='Grupo')
        self.product = Product.objects.create(
            name='Producto', brand=brand, group=group,
            unit_price=Decimal('10'), stock=0, stock_minimo=5,
        )

    @patch('notificaciones.services.send_telegram_message')
    def test_manda_telegram_cuando_se_crea_una_notificacion_nueva(self, mock_telegram):
        notificar_stock_bajo(self.product)
        mock_telegram.assert_called_once()
        self.assertIn(self.product.name, mock_telegram.call_args[0][0])

    @patch('notificaciones.services.send_telegram_message')
    def test_no_manda_telegram_si_ya_existia_sin_leer(self, mock_telegram):
        notificar_stock_bajo(self.product)
        mock_telegram.reset_mock()
        notificar_stock_bajo(self.product)
        mock_telegram.assert_not_called()


class NotificarCajaDiferenciaTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('cajero_notif', password='clave-test-123')

    def test_no_notifica_si_no_hay_diferencia(self):
        sesion = SesionCaja.objects.create(usuario=self.user, monto_inicial=Decimal('100.00'))
        sesion.monto_contado_cierre = Decimal('100.00')
        sesion.estado = SesionCaja.CERRADA
        sesion.save()
        self.assertIsNone(notificar_caja_diferencia(sesion))

    def test_notifica_si_hay_diferencia(self):
        sesion = SesionCaja.objects.create(usuario=self.user, monto_inicial=Decimal('100.00'))
        sesion.monto_contado_cierre = Decimal('90.00')
        sesion.estado = SesionCaja.CERRADA
        sesion.save()
        n = notificar_caja_diferencia(sesion)
        self.assertIsNotNone(n)
        self.assertEqual(n.usuario, self.user)
        self.assertIn('falta', n.mensaje)


class SincronizarProductosPorVencerTests(TestCase):
    def setUp(self):
        self.brand = Brand.objects.create(name='Marca')
        self.group = ProductGroup.objects.create(name='Grupo')

    def _producto(self, **kwargs):
        return Product.objects.create(
            name='Producto', brand=self.brand, group=self.group,
            unit_price=Decimal('10'), stock=10, **kwargs
        )

    def test_ignora_productos_sin_fecha_vencimiento(self):
        self._producto()
        self.assertEqual(sincronizar_productos_por_vencer(), [])

    def test_ignora_productos_fuera_de_la_ventana(self):
        self._producto(fecha_vencimiento=timezone.now().date() + timedelta(days=60))
        self.assertEqual(sincronizar_productos_por_vencer(dias=30), [])

    def test_notifica_producto_por_vencer_dentro_de_la_ventana(self):
        self._producto(fecha_vencimiento=timezone.now().date() + timedelta(days=10))
        creadas = sincronizar_productos_por_vencer(dias=30)
        self.assertEqual(len(creadas), 1)
        self.assertEqual(creadas[0].nivel, Notificacion.WARNING)

    def test_notifica_danger_si_ya_vencio(self):
        self._producto(fecha_vencimiento=timezone.now().date() - timedelta(days=1))
        creadas = sincronizar_productos_por_vencer(dias=30)
        self.assertEqual(creadas[0].nivel, Notificacion.DANGER)


class SincronizarPagosPendientesTests(TestCase):
    def setUp(self):
        self.brand = Brand.objects.create(name='Marca')
        self.group = ProductGroup.objects.create(name='Grupo')
        self.supplier = Supplier.objects.create(name='Proveedor')
        self.customer = Customer.objects.create(dni='1234567890', first_name='Ana', last_name='Gómez')

    def test_notifica_compra_a_credito_por_vencer(self):
        purchase = Purchase.objects.create(
            supplier=self.supplier, document_number='F-001',
            total=Decimal('100.00'), tipo_pago=Purchase.CREDITO,
            meses_credito=1, saldo=Decimal('100.00'), estado=Purchase.PENDIENTE,
        )
        # backdatea la compra para que su fecha_limite_pago quede a 2 días (dentro de la ventana de aviso)
        fecha_pasada = timezone.now() - timedelta(days=28)
        Purchase.objects.filter(pk=purchase.pk).update(purchase_date=fecha_pasada)
        purchase.refresh_from_db()
        creadas = sincronizar_pagos_pendientes()
        self.assertTrue(any(n.tipo == Notificacion.PAGO_PENDIENTE for n in creadas))

    def test_no_notifica_compra_al_contado(self):
        Purchase.objects.create(
            supplier=self.supplier, document_number='F-002',
            total=Decimal('100.00'), tipo_pago=Purchase.CONTADO, estado=Purchase.PAGADA,
        )
        self.assertEqual(sincronizar_pagos_pendientes(), [])

    def test_notifica_factura_a_credito_vencida(self):
        invoice = Invoice.objects.create(
            customer=self.customer, total=Decimal('50.00'), saldo=Decimal('50.00'),
            tipo_pago=Invoice.CREDITO, estado=Invoice.PENDIENTE,
        )
        fecha_pasada = timezone.now() - timedelta(days=40)
        Invoice.objects.filter(pk=invoice.pk).update(invoice_date=fecha_pasada)
        creadas = sincronizar_pagos_pendientes()
        self.assertTrue(any(f'factura:{invoice.id}' in n.clave for n in creadas))

    def test_no_notifica_factura_dentro_del_plazo(self):
        CustomerProfile.objects.create(customer=self.customer, payment_terms='credit_30')
        Invoice.objects.create(
            customer=self.customer, total=Decimal('50.00'), saldo=Decimal('50.00'),
            tipo_pago=Invoice.CREDITO, estado=Invoice.PENDIENTE,
        )
        self.assertEqual(sincronizar_pagos_pendientes(), [])


class ConfiguracionDiasAvisoTests(TestCase):
    """Confirma que sincronizar_* usan los días configurados en
    ConfiguracionSistema (configuracion/models.py) cuando no se pasa un valor explícito."""

    def setUp(self):
        self.brand = Brand.objects.create(name='Marca Dias')
        self.group = ProductGroup.objects.create(name='Grupo Dias')
        self.customer = Customer.objects.create(dni='1700000077', first_name='Ana', last_name='Gómez')

    def test_sincronizar_productos_por_vencer_usa_el_valor_configurado(self):
        from configuracion.models import ConfiguracionSistema
        config = ConfiguracionSistema.get_solo()
        config.dias_aviso_vencimiento_producto = 5
        config.save()

        # a 10 días: fuera de la ventana configurada (5), NO debería notificar
        Product.objects.create(
            name='Producto Dias', brand=self.brand, group=self.group,
            unit_price=Decimal('10'), stock=10,
            fecha_vencimiento=timezone.now().date() + timedelta(days=10),
        )
        self.assertEqual(sincronizar_productos_por_vencer(), [])

        config.dias_aviso_vencimiento_producto = 15
        config.save()
        creadas = sincronizar_productos_por_vencer()
        self.assertEqual(len(creadas), 1)

    def test_sincronizar_pagos_pendientes_usa_dias_credito_factura_default_configurado(self):
        from configuracion.models import ConfiguracionSistema
        config = ConfiguracionSistema.get_solo()
        config.dias_credito_factura_default = 10
        config.save()

        invoice = Invoice.objects.create(
            customer=self.customer, total=Decimal('50.00'), saldo=Decimal('50.00'),
            tipo_pago=Invoice.CREDITO, estado=Invoice.PENDIENTE,
        )
        # sin perfil -> usa dias_credito_factura_default; backdatea 12 días (> 10 configurados)
        Invoice.objects.filter(pk=invoice.pk).update(invoice_date=timezone.now() - timedelta(days=12))
        creadas = sincronizar_pagos_pendientes()
        self.assertTrue(any(f'factura:{invoice.id}' in n.clave for n in creadas))


class NotificacionListViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('notif_user', password='clave-test-123')
        perms = Permission.objects.filter(codename__in=['view_notificacion', 'change_notificacion'])
        self.user.user_permissions.set(perms)
        self.client.force_login(self.user)

    def test_lista_muestra_notificaciones_generales(self):
        Notificacion.objects.create(tipo=Notificacion.STOCK_BAJO, mensaje='Stock bajo', clave='k1')
        response = self.client.get(reverse('notificaciones:notificacion_list'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Stock bajo')

    def test_marcar_leida_redirige_a_url_si_existe(self):
        n = Notificacion.objects.create(
            tipo=Notificacion.STOCK_BAJO, mensaje='Stock bajo', clave='k2', url='/products/',
        )
        response = self.client.post(reverse('notificaciones:notificacion_marcar_leida', args=[n.pk]))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, '/products/')
        n.refresh_from_db()
        self.assertTrue(n.leida)

    def test_marcar_todas_leidas(self):
        Notificacion.objects.create(tipo=Notificacion.STOCK_BAJO, mensaje='a', clave='k3')
        Notificacion.objects.create(tipo=Notificacion.CAJA_ALERTA, mensaje='b', clave='k4')
        response = self.client.post(reverse('notificaciones:notificacion_marcar_todas_leidas'))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Notificacion.objects.filter(leida=False).count(), 0)
