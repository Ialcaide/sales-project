from decimal import Decimal

from django.contrib.auth.models import Permission, User
from django.test import TestCase
from django.urls import reverse

from .models import ConfiguracionSistema


class ConfiguracionSistemaModelTests(TestCase):
    def test_get_solo_es_idempotente(self):
        c1 = ConfiguracionSistema.get_solo()
        c2 = ConfiguracionSistema.get_solo()
        self.assertEqual(c1.pk, c2.pk)
        self.assertEqual(ConfiguracionSistema.objects.count(), 1)

    def test_save_fuerza_pk_1(self):
        c = ConfiguracionSistema(empresa_nombre='Otra cosa')
        c.save()
        self.assertEqual(c.pk, 1)
        c2 = ConfiguracionSistema(empresa_nombre='Otra cosa 2')
        c2.save()
        self.assertEqual(ConfiguracionSistema.objects.count(), 1)

    def test_defaults_coinciden_con_el_comportamiento_previo(self):
        c = ConfiguracionSistema.get_solo()
        self.assertEqual(c.iva_porcentaje, Decimal('15.00'))
        self.assertEqual(c.iva_fraccion, Decimal('0.15'))
        self.assertEqual(c.credito_porcentaje_por_compras, Decimal('30.00'))
        self.assertEqual(c.credito_fraccion, Decimal('0.30'))
        self.assertEqual(c.stock_minimo_default, 5)
        self.assertEqual(c.empresa_nombre, 'TecnoStock S.A.')


class ConfiguracionEditarViewTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user('config_admin', password='clave-test-123')
        self.admin.user_permissions.set(
            Permission.objects.filter(codename='change_configuracionsistema')
        )
        self.vendedor = User.objects.create_user('config_vendedor', password='clave-test-123')

    def test_administrador_puede_ver_y_guardar(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse('configuracion:configuracion_editar'))
        self.assertEqual(response.status_code, 200)

        data = {
            'empresa_nombre': 'Nueva Empresa S.A.', 'empresa_ruc': '1790000000001',
            'empresa_direccion': 'Av. Siempre Viva 123', 'empresa_telefono': '0999999999',
            'iva_porcentaje': '10.00', 'moneda_simbolo': '$',
            'stock_minimo_default': '8', 'credito_porcentaje_por_compras': '20.00',
            'dias_aviso_vencimiento_producto': '15', 'dias_aviso_pago_compra': '3',
            'dias_credito_factura_default': '45',
            'sri_establecimiento': '001', 'sri_punto_emision': '001',
        }
        response = self.client.post(reverse('configuracion:configuracion_editar'), data)
        self.assertEqual(response.status_code, 302)

        config = ConfiguracionSistema.get_solo()
        self.assertEqual(config.empresa_nombre, 'Nueva Empresa S.A.')
        self.assertEqual(config.iva_porcentaje, Decimal('10.00'))
        self.assertEqual(config.iva_fraccion, Decimal('0.10'))
        self.assertEqual(config.credito_porcentaje_por_compras, Decimal('20.00'))
        self.assertEqual(config.stock_minimo_default, 8)

    def test_usuario_sin_permiso_es_redirigido(self):
        self.client.force_login(self.vendedor)
        response = self.client.get(reverse('configuracion:configuracion_editar'))
        self.assertEqual(response.status_code, 302)
