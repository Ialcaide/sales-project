from urllib.parse import unquote

from django.contrib.auth.models import User
from django.core import mail
from django.test import TestCase
from django.urls import reverse

from .forms import UserUpdateForm
from .models import UserProfile


class UserProfileWhatsappAccesoUrlTests(TestCase):
    """Link 'wa.me' manual (no automatizado) para recordarle a un usuario cómo entrar al sistema."""

    def test_none_si_no_tiene_perfil(self):
        user = User.objects.create_user('sin_perfil', password='clave-test-123')
        self.assertIsNone(getattr(user, 'profile', None))

    def test_none_si_perfil_sin_telefono(self):
        user = User.objects.create_user('vendedor_wa', password='clave-test-123')
        profile = UserProfile.objects.create(user=user, phone='')
        self.assertIsNone(profile.whatsapp_acceso_url)

    def test_url_apunta_a_wa_me_con_el_telefono_sin_el_signo_mas(self):
        user = User.objects.create_user('vendedor_wa2', password='clave-test-123', first_name='Ana')
        profile = UserProfile.objects.create(user=user, phone='+593987654321')
        url = profile.whatsapp_acceso_url
        self.assertTrue(url.startswith('https://wa.me/593987654321?text='))

    def test_mensaje_incluye_usuario_y_url_del_sitio(self):
        from django.conf import settings
        user = User.objects.create_user('vendedor_wa3', password='clave-test-123', first_name='Ana')
        profile = UserProfile.objects.create(user=user, phone='+593987654321')
        mensaje = unquote(profile.whatsapp_acceso_url.split('?text=', 1)[1])
        self.assertIn(user.username, mensaje)
        self.assertIn(settings.SITE_URL, mensaje)


class UserUpdateFormPasswordTests(TestCase):
    """El administrador puede restablecer la contraseña de un usuario al editarlo
    — dejando los campos en blanco, la contraseña actual no se toca."""

    def setUp(self):
        self.user = User.objects.create_user(
            'editado', password='clave-original-123', first_name='Ana', last_name='Gómez', email='ana@example.com',
        )
        UserProfile.objects.create(user=self.user, phone='+593987654321')

    def base_data(self, **overrides):
        data = {
            'username': 'editado', 'first_name': 'Ana', 'last_name': 'Gómez',
            'email': 'ana@example.com', 'is_active': True, 'phone': '+593987654321',
            'new_password1': '', 'new_password2': '',
        }
        data.update(overrides)
        return data

    def test_dejar_en_blanco_no_cambia_la_contraseña(self):
        form = UserUpdateForm(data=self.base_data(), instance=self.user)
        self.assertTrue(form.is_valid(), form.errors)
        user = form.save()
        self.assertTrue(user.check_password('clave-original-123'))

    def test_contraseñas_no_coincidentes_es_invalido(self):
        form = UserUpdateForm(
            data=self.base_data(new_password1='NuevaClave2026!', new_password2='OtraClave2026!'),
            instance=self.user,
        )
        self.assertFalse(form.is_valid())
        self.assertIn('new_password2', form.errors)

    def test_contraseña_debil_es_rechazada(self):
        form = UserUpdateForm(
            data=self.base_data(new_password1='123', new_password2='123'),
            instance=self.user,
        )
        self.assertFalse(form.is_valid())
        self.assertIn('new_password1', form.errors)

    def test_contraseñas_coincidentes_y_validas_cambian_la_contraseña(self):
        form = UserUpdateForm(
            data=self.base_data(new_password1='NuevaClave2026!', new_password2='NuevaClave2026!'),
            instance=self.user,
        )
        self.assertTrue(form.is_valid(), form.errors)
        user = form.save()
        user.refresh_from_db()
        self.assertTrue(user.check_password('NuevaClave2026!'))
        self.assertFalse(user.check_password('clave-original-123'))


class UserUpdateViewPasswordTests(TestCase):
    """El administrador puede restablecer la contraseña de otro usuario desde /security/users/<id>/edit/."""

    def setUp(self):
        self.admin = User.objects.create_superuser('admin_test', 'admin@example.com', 'clave-admin-123')
        self.client.force_login(self.admin)
        self.target = User.objects.create_user(
            'objetivo', password='clave-vieja-123', first_name='Luis', last_name='Pérez', email='luis@example.com',
        )
        UserProfile.objects.create(user=self.target, phone='+593987654322')

    def _post(self, **overrides):
        data = {
            'username': 'objetivo', 'first_name': 'Luis', 'last_name': 'Pérez',
            'email': 'luis@example.com', 'is_active': True, 'phone': '+593987654322',
            'new_password1': '', 'new_password2': '',
        }
        data.update(overrides)
        return self.client.post(reverse('security:user_update', args=[self.target.pk]), data)

    def test_admin_restablece_la_contraseña_de_otro_usuario(self):
        response = self._post(new_password1='OtraClaveNueva2026!', new_password2='OtraClaveNueva2026!')
        self.assertEqual(response.status_code, 302)
        self.target.refresh_from_db()
        self.assertTrue(self.target.check_password('OtraClaveNueva2026!'))

    def test_notificacion_de_actualizacion_incluye_la_nueva_contraseña(self):
        self._post(new_password1='OtraClaveNueva2026!', new_password2='OtraClaveNueva2026!')
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('OtraClaveNueva2026!', mail.outbox[0].body)

    def test_sin_tocar_los_campos_de_contraseña_no_la_cambia(self):
        self._post()
        self.target.refresh_from_db()
        self.assertTrue(self.target.check_password('clave-vieja-123'))


class PermissionListViewProbeTests(TestCase):
    """Reproduce el reporte del usuario: la tabla de marcar permisos en
    Seguridad > Permisos no se vincula correctamente con los roles al
    agregar/quitar. Prueba end-to-end contra la vista real."""

    def setUp(self):
        from django.contrib.auth.models import Group, Permission
        self.admin = User.objects.create_superuser('admin_probe', 'admin@example.com', 'clave-admin-123')
        self.client.force_login(self.admin)
        self.vendedor = Group.objects.create(name='VendedorProbe')
        self.cajero = Group.objects.create(name='CajeroProbe')
        self.perm_delete_invoice = Permission.objects.get(codename='delete_invoice', content_type__app_label='billing')
        self.perm_view_invoice = Permission.objects.get(codename='view_invoice', content_type__app_label='billing')
        self.vendedor.permissions.set([self.perm_view_invoice])

    def test_get_muestra_permisos_del_rol_seleccionado(self):
        from django.urls import reverse
        response = self.client.get(reverse('security:permission_list'), {'target_type': 'group', 'target_id': self.vendedor.id})
        self.assertEqual(response.status_code, 200)
        model_cards = response.context['model_cards']
        invoice_card = model_cards[('billing', 'invoice')]
        checked = {item['id']: item['checked'] for item in invoice_card['items']}
        self.assertTrue(checked[self.perm_view_invoice.id])
        self.assertFalse(checked[self.perm_delete_invoice.id])

    def test_post_agrega_permiso_al_rol(self):
        from django.urls import reverse
        response = self.client.post(reverse('security:permission_list'), {
            'target_type': 'group', 'target_id': self.vendedor.id,
            'perm_ids': [self.perm_view_invoice.id, self.perm_delete_invoice.id],
        })
        self.assertEqual(response.status_code, 302)
        self.vendedor.refresh_from_db()
        self.assertIn(self.perm_delete_invoice, self.vendedor.permissions.all())

    def test_post_quita_permiso_del_rol(self):
        from django.urls import reverse
        self.vendedor.permissions.set([self.perm_view_invoice, self.perm_delete_invoice])
        response = self.client.post(reverse('security:permission_list'), {
            'target_type': 'group', 'target_id': self.vendedor.id,
            'perm_ids': [self.perm_view_invoice.id],
        })
        self.assertEqual(response.status_code, 302)
        self.vendedor.refresh_from_db()
        self.assertNotIn(self.perm_delete_invoice, self.vendedor.permissions.all())

    def test_cambiar_de_rol_no_mezcla_permisos(self):
        from django.urls import reverse
        self.vendedor.permissions.set([self.perm_view_invoice, self.perm_delete_invoice])
        self.cajero.permissions.set([])
        response = self.client.get(reverse('security:permission_list'), {'target_type': 'group', 'target_id': self.cajero.id})
        model_cards = response.context['model_cards']
        invoice_card = model_cards[('billing', 'invoice')]
        checked = {item['id']: item['checked'] for item in invoice_card['items']}
        self.assertFalse(checked[self.perm_delete_invoice.id])
        self.assertFalse(checked[self.perm_view_invoice.id])


class SetupRolesCommandTests(TestCase):
    """El comando setup_roles NO debe pisar permisos que un administrador ya
    haya personalizado a mano desde Seguridad > Permisos — este era el bug
    real detrás del reporte 'si le doy permiso de eliminar a Vendedor no se
    queda guardado': cada vez que alguien corría `setup_roles` de nuevo
    (ej. en un deploy), la lista fija de este archivo pisaba cualquier
    permiso agregado/quitado manualmente."""

    def test_primera_corrida_crea_los_roles_con_sus_permisos_por_defecto(self):
        from io import StringIO
        from django.contrib.auth.models import Group
        from django.core.management import call_command
        call_command('setup_roles', stdout=StringIO())
        vendedor = Group.objects.get(name='Vendedor')
        self.assertTrue(vendedor.permissions.filter(codename='view_invoice').exists())

    def test_correr_de_nuevo_sin_reset_no_pisa_permisos_agregados_a_mano(self):
        from io import StringIO
        from django.contrib.auth.models import Group, Permission
        from django.core.management import call_command
        call_command('setup_roles', stdout=StringIO())

        vendedor = Group.objects.get(name='Vendedor')
        delete_invoice = Permission.objects.get(codename='delete_invoice', content_type__app_label='billing')
        vendedor.permissions.add(delete_invoice)  # simula lo que haría un admin desde la UI

        call_command('setup_roles', stdout=StringIO())  # ej. se vuelve a correr en un deploy

        vendedor.refresh_from_db()
        self.assertIn(delete_invoice, vendedor.permissions.all())

    def test_correr_con_reset_restaura_los_permisos_por_defecto(self):
        from io import StringIO
        from django.contrib.auth.models import Group, Permission
        from django.core.management import call_command
        call_command('setup_roles', stdout=StringIO())

        vendedor = Group.objects.get(name='Vendedor')
        delete_invoice = Permission.objects.get(codename='delete_invoice', content_type__app_label='billing')
        vendedor.permissions.add(delete_invoice)

        call_command('setup_roles', '--reset', stdout=StringIO())

        vendedor.refresh_from_db()
        self.assertNotIn(delete_invoice, vendedor.permissions.all())


class PermissionListShowsModuleAccessTests(TestCase):
    """La pantalla de Gestión de Permisos debe mostrar 'Acceso al módulo'
    como una casilla aparte de 'Ver', para el modelo Invoice (y el resto de
    modelos con lista+detalle)."""

    def setUp(self):
        from django.contrib.auth.models import Group
        self.admin = User.objects.create_superuser('admin_modaccess', 'admin@example.com', 'clave-admin-123')
        self.client.force_login(self.admin)
        self.group = Group.objects.create(name='RolProbeModAccess')

    def test_acceso_al_modulo_aparece_como_casilla_propia(self):
        from django.urls import reverse
        response = self.client.get(reverse('security:permission_list'), {'target_type': 'group', 'target_id': self.group.id})
        self.assertEqual(response.status_code, 200)
        model_cards = response.context['model_cards']
        invoice_card = model_cards[('billing', 'invoice')]
        labels = {item['label'] for item in invoice_card['items']}
        self.assertIn('Acceso al módulo', labels)
        self.assertIn('Ver', labels)
