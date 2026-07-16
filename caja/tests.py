from decimal import Decimal

from django.contrib.auth.models import Permission, User
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from notificaciones.models import Notificacion

from .models import MovimientoCaja, SesionCaja


class SesionCajaModelTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('cajero1', password='clave-test-123')

    def test_totales_con_movimientos(self):
        sesion = SesionCaja.objects.create(usuario=self.user, monto_inicial=Decimal('100.00'))
        MovimientoCaja.objects.create(sesion=sesion, tipo=MovimientoCaja.INGRESO, monto=Decimal('50.00'), concepto='Venta 1')
        MovimientoCaja.objects.create(sesion=sesion, tipo=MovimientoCaja.INGRESO, monto=Decimal('30.00'), concepto='Venta 2')
        MovimientoCaja.objects.create(sesion=sesion, tipo=MovimientoCaja.EGRESO, monto=Decimal('20.00'), concepto='Retiro')

        self.assertEqual(sesion.total_ingresos, Decimal('80.00'))
        self.assertEqual(sesion.total_egresos, Decimal('20.00'))
        self.assertEqual(sesion.monto_esperado_cierre, Decimal('160.00'))  # 100 + 80 - 20

    def test_diferencia_none_mientras_abierta(self):
        sesion = SesionCaja.objects.create(usuario=self.user, monto_inicial=Decimal('100.00'))
        self.assertIsNone(sesion.diferencia)

    def test_diferencia_calculada_al_cerrar(self):
        sesion = SesionCaja.objects.create(usuario=self.user, monto_inicial=Decimal('100.00'))
        MovimientoCaja.objects.create(sesion=sesion, tipo=MovimientoCaja.INGRESO, monto=Decimal('50.00'), concepto='Venta')
        sesion.monto_contado_cierre = Decimal('145.00')  # esperado 150, contado 145 -> falta 5
        sesion.estado = SesionCaja.CERRADA
        sesion.save()
        self.assertEqual(sesion.diferencia, Decimal('-5.00'))

    def test_movimiento_negativo_o_cero_rechazado(self):
        sesion = SesionCaja.objects.create(usuario=self.user, monto_inicial=Decimal('100.00'))
        for monto in (Decimal('0.00'), Decimal('-10.00')):
            movimiento = MovimientoCaja(sesion=sesion, tipo=MovimientoCaja.INGRESO, monto=monto, concepto='x')
            with self.assertRaises(ValidationError):
                movimiento.full_clean()

    def test_no_se_puede_registrar_movimiento_en_caja_cerrada(self):
        sesion = SesionCaja.objects.create(
            usuario=self.user, monto_inicial=Decimal('100.00'),
            estado=SesionCaja.CERRADA, monto_contado_cierre=Decimal('100.00'),
        )
        movimiento = MovimientoCaja(sesion=sesion, tipo=MovimientoCaja.INGRESO, monto=Decimal('10.00'), concepto='x')
        with self.assertRaises(ValidationError):
            movimiento.save()


class CajaViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('cajero2', password='clave-test-123')
        perms = Permission.objects.filter(
            codename__in=['view_sesioncaja', 'add_sesioncaja', 'change_sesioncaja',
                           'view_movimientocaja', 'add_movimientocaja']
        )
        self.user.user_permissions.set(perms)
        self.client.force_login(self.user)

    def test_abrir_caja(self):
        response = self.client.post(reverse('caja:caja_abrir'), {'monto_inicial': '100.00'})
        self.assertEqual(response.status_code, 302)
        sesion = SesionCaja.objects.get(usuario=self.user)
        self.assertEqual(sesion.estado, SesionCaja.ABIERTA)
        self.assertEqual(sesion.monto_inicial, Decimal('100.00'))

    def test_no_se_puede_abrir_dos_cajas_a_la_vez(self):
        SesionCaja.objects.create(usuario=self.user, monto_inicial=Decimal('50.00'))
        response = self.client.get(reverse('caja:caja_abrir'))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(SesionCaja.objects.filter(usuario=self.user).count(), 1)

    def test_cerrar_caja_calcula_diferencia(self):
        sesion = SesionCaja.objects.create(usuario=self.user, monto_inicial=Decimal('100.00'))
        response = self.client.post(reverse('caja:caja_cerrar', args=[sesion.pk]), {'monto_contado_cierre': '95.00'})
        self.assertEqual(response.status_code, 302)
        sesion.refresh_from_db()
        self.assertEqual(sesion.estado, SesionCaja.CERRADA)
        self.assertEqual(sesion.diferencia, Decimal('-5.00'))

    def test_cerrar_caja_con_diferencia_crea_notificacion(self):
        sesion = SesionCaja.objects.create(usuario=self.user, monto_inicial=Decimal('100.00'))
        self.client.post(reverse('caja:caja_cerrar', args=[sesion.pk]), {'monto_contado_cierre': '95.00'})
        self.assertTrue(Notificacion.objects.filter(tipo=Notificacion.CAJA_ALERTA, clave=f'caja_alerta:sesion:{sesion.id}').exists())

    def test_cerrar_caja_sin_diferencia_no_crea_notificacion(self):
        sesion = SesionCaja.objects.create(usuario=self.user, monto_inicial=Decimal('100.00'))
        self.client.post(reverse('caja:caja_cerrar', args=[sesion.pk]), {'monto_contado_cierre': '100.00'})
        self.assertFalse(Notificacion.objects.filter(tipo=Notificacion.CAJA_ALERTA).exists())

    def test_cerrar_caja_sin_monto_contado_es_invalido(self):
        sesion = SesionCaja.objects.create(usuario=self.user, monto_inicial=Decimal('100.00'))
        response = self.client.post(reverse('caja:caja_cerrar', args=[sesion.pk]), {'monto_contado_cierre': ''})
        self.assertEqual(response.status_code, 200)
        sesion.refresh_from_db()
        self.assertEqual(sesion.estado, SesionCaja.ABIERTA)

    def test_registrar_movimiento_manual(self):
        sesion = SesionCaja.objects.create(usuario=self.user, monto_inicial=Decimal('100.00'))
        url = reverse('caja:movimiento_crear', args=[sesion.pk])
        response = self.client.post(url, {'tipo': 'egreso', 'monto': '20.00', 'concepto': 'Pago de gasto menor'})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(sesion.movimientos.count(), 1)
        self.assertEqual(sesion.total_egresos, Decimal('20.00'))

    def test_no_se_puede_registrar_movimiento_en_caja_cerrada_via_vista(self):
        sesion = SesionCaja.objects.create(
            usuario=self.user, monto_inicial=Decimal('100.00'),
            estado=SesionCaja.CERRADA, monto_contado_cierre=Decimal('100.00'),
        )
        url = reverse('caja:movimiento_crear', args=[sesion.pk])
        response = self.client.post(url, {'tipo': 'ingreso', 'monto': '20.00', 'concepto': 'x'})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(sesion.movimientos.count(), 0)

    def test_usuario_sin_permiso_es_redirigido(self):
        self.client.logout()
        other = User.objects.create_user('sinpermiso', password='clave-test-123')
        self.client.force_login(other)
        response = self.client.get(reverse('caja:caja_historial'))
        self.assertEqual(response.status_code, 302)
