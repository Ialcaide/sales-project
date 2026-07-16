from decimal import Decimal

from django.contrib.auth.models import Group, User
from django.test import TestCase
from django.urls import reverse

from caja.models import SesionCaja


class HomeDashboardPorRolTests(TestCase):
    def setUp(self):
        for nombre in ['Administrador', 'Vendedor', 'Analista de Compras', 'Cajero']:
            Group.objects.get_or_create(name=nombre)

    def _login_con_rol(self, username, grupo):
        user = User.objects.create_user(username, password='clave-test-123')
        user.groups.add(Group.objects.get(name=grupo))
        self.client.force_login(user)
        return user

    def test_administrador_ve_home_admin(self):
        self._login_con_rol('admin_home', 'Administrador')
        response = self.client.get(reverse('home'))
        self.assertTemplateUsed(response, 'home/home_admin.html')

    def test_vendedor_ve_home_vendedor(self):
        self._login_con_rol('vendedor_home', 'Vendedor')
        response = self.client.get(reverse('home'))
        self.assertTemplateUsed(response, 'home/home_vendedor.html')

    def test_analista_compras_ve_home_compras(self):
        self._login_con_rol('compras_home', 'Analista de Compras')
        response = self.client.get(reverse('home'))
        self.assertTemplateUsed(response, 'home/home_compras.html')

    def test_cajero_ve_home_cajero(self):
        self._login_con_rol('cajero_home', 'Cajero')
        response = self.client.get(reverse('home'))
        self.assertTemplateUsed(response, 'home/home_cajero.html')

    def test_sin_rol_conocido_cae_a_home_admin(self):
        user = User.objects.create_user('sin_rol_home', password='clave-test-123')
        self.client.force_login(user)
        response = self.client.get(reverse('home'))
        self.assertTemplateUsed(response, 'home/home_admin.html')


class HomeCajaContextoTests(TestCase):
    def setUp(self):
        Group.objects.get_or_create(name='Cajero')
        self.user = User.objects.create_user('cajero_ctx', password='clave-test-123')
        self.user.groups.add(Group.objects.get(name='Cajero'))
        self.client.force_login(self.user)

    def test_sin_caja_abierta_el_contexto_es_none(self):
        response = self.client.get(reverse('home'))
        self.assertIsNone(response.context['sesion_caja_abierta'])
        self.assertContains(response, 'No tienes una caja abierta')

    def test_con_caja_abierta_el_contexto_trae_la_sesion(self):
        sesion = SesionCaja.objects.create(usuario=self.user, monto_inicial=Decimal('100.00'))
        response = self.client.get(reverse('home'))
        self.assertEqual(response.context['sesion_caja_abierta'], sesion)
        self.assertContains(response, 'Caja abierta')
