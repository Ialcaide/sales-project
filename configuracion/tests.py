from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth.models import Permission, User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from facturacion_electronica.services import SRIError

from .models import ConfiguracionSistema, EmpresaFacturacionElectronica


def _archivo_certificado():
    return SimpleUploadedFile('firma.p12', b'contenido-binario-falso', content_type='application/x-pkcs12')


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
            'retencion_porcentaje_default': '2.50',
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
        self.assertEqual(config.retencion_porcentaje_default, Decimal('2.50'))
        self.assertEqual(config.stock_minimo_default, 8)

    def test_usuario_sin_permiso_es_redirigido(self):
        self.client.force_login(self.vendedor)
        response = self.client.get(reverse('configuracion:configuracion_editar'))
        self.assertEqual(response.status_code, 302)

    def test_cards_de_facturacion_electronica_tienen_nombres_distintos_y_sin_ambiguedad(self):
        # Regresión: antes las dos cards se llamaban "Facturación Electrónica
        # (SRI)" y "Facturación Electrónica — Empresa Activa" — nombres tan
        # parecidos que se leían como la misma sección. Ahora deben ser
        # claramente distintas, y la de "valores por defecto" debe aclarar
        # que no afecta a la empresa que factura hoy.
        self.client.force_login(self.admin)
        response = self.client.get(reverse('configuracion:configuracion_editar'))

        self.assertContains(response, 'Valores por Defecto — Nueva Empresa (SRI)')
        self.assertContains(response, 'Empresa Facturando Actualmente')
        self.assertNotContains(response, 'Facturación Electrónica (SRI)')
        self.assertNotContains(response, 'Facturación Electrónica — Empresa Activa')
        self.assertContains(response, 'no</strong> afectan a la empresa que está facturando hoy')

    def test_retencion_porcentaje_default_visible_y_persiste_al_recargar(self):
        self.client.force_login(self.admin)
        config = ConfiguracionSistema.get_solo()
        config.retencion_porcentaje_default = Decimal('7.75')
        config.save()

        response = self.client.get(reverse('configuracion:configuracion_editar'))

        self.assertContains(response, '% de retención por defecto (compras)')
        self.assertContains(response, 'value="7.75"')


class EmpresaFacturacionElectronicaModelTests(TestCase):
    def _crear(self, **overrides):
        datos = {
            'ruc': '1790000000001', 'razon_social': 'TecnoStock S.A.', 'direccion_matriz': 'Av. Siempre Viva 123',
            'codigo_establecimiento': '001', 'codigo_punto_emision': '001',
            'empresa_id_microservicio': '1', 'api_key': 'clave-1',
        }
        datos.update(overrides)
        return EmpresaFacturacionElectronica.objects.create(**datos)

    def test_activar_una_desactiva_las_demas(self):
        e1 = self._crear(empresa_id_microservicio='1', api_key='clave-1', activa=True)
        e2 = self._crear(empresa_id_microservicio='2', api_key='clave-2', activa=False)

        e2.activa = True
        e2.save()
        e1.refresh_from_db()

        self.assertFalse(e1.activa)
        self.assertTrue(e2.activa)
        self.assertEqual(EmpresaFacturacionElectronica.objects.filter(activa=True).count(), 1)

    def test_get_activa_devuelve_la_marcada_activa(self):
        self._crear(empresa_id_microservicio='1', api_key='clave-1', activa=False)
        activa = self._crear(empresa_id_microservicio='2', api_key='clave-2', activa=True)

        self.assertEqual(EmpresaFacturacionElectronica.get_activa(), activa)

    def test_get_activa_devuelve_none_si_ninguna_esta_activa(self):
        self._crear(empresa_id_microservicio='1', api_key='clave-1', activa=False)
        self.assertIsNone(EmpresaFacturacionElectronica.get_activa())


class ConectarFacturacionElectronicaViewTests(TestCase):
    """Conectar una empresa NUEVA siempre AGREGA un registro (no reemplaza
    ninguno): ver configuracion/views.py -> conectar_facturacion_electronica."""

    def setUp(self):
        self.admin = User.objects.create_user('config_admin_fe', password='clave-test-123')
        self.admin.user_permissions.set(
            Permission.objects.filter(codename='change_configuracionsistema')
        )
        self.vendedor = User.objects.create_user('config_vendedor_fe', password='clave-test-123')
        self.datos_formulario = {
            'ruc': '1790000000001',
            'razon_social': 'TecnoStock S.A.',
            'direccion_matriz': 'Av. Siempre Viva 123',
            'establecimiento': '001',
            'punto_emision': '001',
            'ambiente': ConfiguracionSistema.AMBIENTE_PRUEBAS,
        }

    @patch('facturacion_electronica.services.subir_certificado')
    @patch('facturacion_electronica.services.crear_empresa')
    def test_conecta_crea_empresa_sube_certificado_y_queda_activa(self, mock_crear, mock_subir):
        self.client.force_login(self.admin)
        mock_crear.return_value = {'id': 42, 'api_key': 'clave-generada-123'}
        mock_subir.return_value = {'ok': True}

        response = self.client.post(
            reverse('configuracion:conectar_facturacion_electronica'),
            {**self.datos_formulario, 'certificado_password': 'secreta123', 'certificado_p12': _archivo_certificado()},
        )

        self.assertEqual(response.status_code, 302)
        mock_crear.assert_called_once_with({
            'ruc': '1790000000001', 'razon_social': 'TecnoStock S.A.',
            'direccion_matriz': 'Av. Siempre Viva 123', 'establecimiento': '001',
            'punto_emision': '001', 'ambiente': ConfiguracionSistema.AMBIENTE_PRUEBAS,
        })
        mock_subir.assert_called_once()
        args, _kwargs = mock_subir.call_args
        self.assertEqual(args[0], '42')
        self.assertEqual(args[1], 'clave-generada-123')
        self.assertEqual(args[3], 'secreta123')

        self.assertEqual(EmpresaFacturacionElectronica.objects.count(), 1)
        empresa = EmpresaFacturacionElectronica.objects.get()
        self.assertEqual(empresa.empresa_id_microservicio, '42')
        self.assertEqual(empresa.api_key, 'clave-generada-123')
        self.assertEqual(empresa.ruc, '1790000000001')
        self.assertTrue(empresa.activa)

    @patch('facturacion_electronica.services.subir_certificado')
    @patch('facturacion_electronica.services.crear_empresa')
    def test_conectar_una_segunda_empresa_desactiva_la_primera(self, mock_crear, mock_subir):
        self.client.force_login(self.admin)
        primera = EmpresaFacturacionElectronica.objects.create(
            ruc='0999999999001', razon_social='Empresa Vieja', direccion_matriz='Otra dirección',
            codigo_establecimiento='001', codigo_punto_emision='001',
            empresa_id_microservicio='1', api_key='clave-vieja', activa=True,
        )
        mock_crear.return_value = {'id': 42, 'api_key': 'clave-nueva'}
        mock_subir.return_value = {'ok': True}

        response = self.client.post(
            reverse('configuracion:conectar_facturacion_electronica'),
            {**self.datos_formulario, 'certificado_password': 'secreta123', 'certificado_p12': _archivo_certificado()},
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(EmpresaFacturacionElectronica.objects.count(), 2)
        primera.refresh_from_db()
        self.assertFalse(primera.activa)
        nueva = EmpresaFacturacionElectronica.objects.exclude(pk=primera.pk).get()
        self.assertTrue(nueva.activa)

    @patch('facturacion_electronica.services.crear_empresa')
    def test_error_al_crear_empresa_muestra_el_mensaje_real_y_no_crea_nada(self, mock_crear):
        self.client.force_login(self.admin)
        mock_crear.side_effect = SRIError('El RUC no coincide con el certificado.')

        response = self.client.post(
            reverse('configuracion:conectar_facturacion_electronica'),
            {**self.datos_formulario, 'certificado_password': 'secreta123', 'certificado_p12': _archivo_certificado()},
            follow=True,
        )

        mensajes = [str(m) for m in response.context['messages']]
        self.assertIn('El RUC no coincide con el certificado.', mensajes)
        self.assertEqual(EmpresaFacturacionElectronica.objects.count(), 0)

    @patch('facturacion_electronica.services.subir_certificado')
    @patch('facturacion_electronica.services.crear_empresa')
    def test_error_al_subir_certificado_conserva_la_empresa_creada_pero_inactiva(self, mock_crear, mock_subir):
        self.client.force_login(self.admin)
        mock_crear.return_value = {'id': 99, 'api_key': 'clave-nueva'}
        mock_subir.side_effect = SRIError('Contraseña de certificado incorrecta.')

        response = self.client.post(
            reverse('configuracion:conectar_facturacion_electronica'),
            {**self.datos_formulario, 'certificado_password': 'mala-clave', 'certificado_p12': _archivo_certificado()},
            follow=True,
        )

        mensajes = [str(m) for m in response.context['messages']]
        self.assertIn('Contraseña de certificado incorrecta.', mensajes)

        # La empresa/api_key SÍ quedan guardadas (el alta en el microservicio
        # ya ocurrió, evita un alta duplicada en un reintento), pero NO
        # activa: nunca llegó a tener un certificado válido.
        empresa = EmpresaFacturacionElectronica.objects.get()
        self.assertEqual(empresa.empresa_id_microservicio, '99')
        self.assertEqual(empresa.api_key, 'clave-nueva')
        self.assertFalse(empresa.activa)

    def test_usuario_sin_permiso_no_puede_conectar(self):
        self.client.force_login(self.vendedor)
        response = self.client.post(
            reverse('configuracion:conectar_facturacion_electronica'),
            {**self.datos_formulario, 'certificado_password': 'x', 'certificado_p12': _archivo_certificado()},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(EmpresaFacturacionElectronica.objects.count(), 0)

    @patch('facturacion_electronica.services.subir_certificado')
    @patch('facturacion_electronica.services.crear_empresa')
    def test_la_contrasena_del_certificado_no_queda_guardada_en_ningun_campo(self, mock_crear, mock_subir):
        self.client.force_login(self.admin)
        mock_crear.return_value = {'id': 7, 'api_key': 'clave-7'}
        mock_subir.return_value = {'ok': True}
        password_secreta = 'esta-clave-no-debe-persistir'

        self.client.post(
            reverse('configuracion:conectar_facturacion_electronica'),
            {**self.datos_formulario, 'certificado_password': password_secreta, 'certificado_p12': _archivo_certificado()},
        )

        empresa = EmpresaFacturacionElectronica.objects.get()
        valores_guardados = [getattr(empresa, field.name) for field in EmpresaFacturacionElectronica._meta.fields]
        self.assertNotIn(password_secreta, valores_guardados)
        config = ConfiguracionSistema.get_solo()
        valores_config = [getattr(config, field.name) for field in ConfiguracionSistema._meta.fields]
        self.assertNotIn(password_secreta, valores_config)


class ActivarEmpresaFacturacionElectronicaViewTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user('config_admin_activar', password='clave-test-123')
        self.admin.user_permissions.set(
            Permission.objects.filter(codename='change_configuracionsistema')
        )
        self.vendedor = User.objects.create_user('config_vendedor_activar', password='clave-test-123')
        self.activa = EmpresaFacturacionElectronica.objects.create(
            ruc='1790000000001', razon_social='Empresa Activa', direccion_matriz='Dirección 1',
            codigo_establecimiento='001', codigo_punto_emision='001',
            empresa_id_microservicio='1', api_key='clave-1', activa=True,
        )
        self.inactiva = EmpresaFacturacionElectronica.objects.create(
            ruc='0999999999001', razon_social='Empresa Inactiva', direccion_matriz='Dirección 2',
            codigo_establecimiento='001', codigo_punto_emision='001',
            empresa_id_microservicio='2', api_key='clave-2', activa=False,
        )

    def test_activar_una_empresa_desactiva_la_anterior(self):
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse('configuracion:activar_empresa_facturacion_electronica', args=[self.inactiva.pk])
        )
        self.assertEqual(response.status_code, 302)

        self.inactiva.refresh_from_db()
        self.activa.refresh_from_db()
        self.assertTrue(self.inactiva.activa)
        self.assertFalse(self.activa.activa)

    def test_usuario_sin_permiso_no_puede_activar(self):
        self.client.force_login(self.vendedor)
        self.client.post(
            reverse('configuracion:activar_empresa_facturacion_electronica', args=[self.inactiva.pk])
        )
        self.inactiva.refresh_from_db()
        self.assertFalse(self.inactiva.activa)

    def test_empresa_inexistente_responde_404(self):
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse('configuracion:activar_empresa_facturacion_electronica', args=[9999])
        )
        self.assertEqual(response.status_code, 404)


class VincularEmpresaExistenteViewTests(TestCase):
    """"Ya tengo una empresa conectada": trae sus datos con GET /empresas/me
    a partir de la api_key, sin volver a darla de alta."""

    def setUp(self):
        self.admin = User.objects.create_user('config_admin_vincular', password='clave-test-123')
        self.admin.user_permissions.set(
            Permission.objects.filter(codename='change_configuracionsistema')
        )
        self.vendedor = User.objects.create_user('config_vendedor_vincular', password='clave-test-123')

    @patch('facturacion_electronica.services.obtener_empresa_actual')
    def test_vincula_con_los_datos_del_microservicio_y_queda_activa(self, mock_obtener):
        self.client.force_login(self.admin)
        mock_obtener.return_value = {
            'id': 5, 'ruc': '1756927560001', 'razon_social': 'Mi Empresa Real',
            'direccion_matriz': 'Av. Real 123', 'codigo_establecimiento': '001',
            'codigo_punto_emision': '001', 'ambiente': 'produccion',
        }

        response = self.client.post(
            reverse('configuracion:vincular_empresa_existente'), {'api_key': 'clave-existente'},
        )

        self.assertEqual(response.status_code, 302)
        mock_obtener.assert_called_once_with('clave-existente')
        empresa = EmpresaFacturacionElectronica.objects.get()
        self.assertEqual(empresa.ruc, '1756927560001')
        self.assertEqual(empresa.empresa_id_microservicio, '5')
        self.assertEqual(empresa.api_key, 'clave-existente')
        self.assertEqual(empresa.ambiente, ConfiguracionSistema.AMBIENTE_PRODUCCION)
        self.assertTrue(empresa.activa)

    @patch('facturacion_electronica.services.obtener_empresa_actual')
    def test_vincular_de_nuevo_actualiza_en_vez_de_duplicar(self, mock_obtener):
        self.client.force_login(self.admin)
        EmpresaFacturacionElectronica.objects.create(
            ruc='1756927560001', razon_social='Nombre Viejo', direccion_matriz='Dirección vieja',
            codigo_establecimiento='001', codigo_punto_emision='001',
            empresa_id_microservicio='5', api_key='clave-vieja', activa=False,
        )
        mock_obtener.return_value = {
            'id': 5, 'ruc': '1756927560001', 'razon_social': 'Nombre Actualizado',
            'direccion_matriz': 'Av. Real 123', 'codigo_establecimiento': '001',
            'codigo_punto_emision': '001', 'ambiente': 'pruebas',
        }

        self.client.post(reverse('configuracion:vincular_empresa_existente'), {'api_key': 'clave-nueva'})

        self.assertEqual(EmpresaFacturacionElectronica.objects.count(), 1)
        empresa = EmpresaFacturacionElectronica.objects.get()
        self.assertEqual(empresa.razon_social, 'Nombre Actualizado')
        self.assertEqual(empresa.api_key, 'clave-nueva')
        self.assertTrue(empresa.activa)

    @patch('facturacion_electronica.services.obtener_empresa_actual')
    def test_api_key_invalida_muestra_el_mensaje_real_y_no_crea_nada(self, mock_obtener):
        self.client.force_login(self.admin)
        mock_obtener.side_effect = SRIError('Api key inválida.')

        response = self.client.post(
            reverse('configuracion:vincular_empresa_existente'), {'api_key': 'clave-mala'}, follow=True,
        )

        mensajes = [str(m) for m in response.context['messages']]
        self.assertIn('Api key inválida.', mensajes)
        self.assertEqual(EmpresaFacturacionElectronica.objects.count(), 0)

    def test_usuario_sin_permiso_no_puede_vincular(self):
        self.client.force_login(self.vendedor)
        response = self.client.post(
            reverse('configuracion:vincular_empresa_existente'), {'api_key': 'clave-cualquiera'},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(EmpresaFacturacionElectronica.objects.count(), 0)


class ConfiguracionFormEmpresaActivaRenderTests(TestCase):
    """Que el badge de ambiente y el texto de confirmación de
    'Cambiar de ambiente' reflejen el ambiente REAL de la empresa activa —
    ambos comparan contra config.AMBIENTE_PRODUCCION/PRUEBAS (no
    empresa_activa.AMBIENTE_*, que ni existe en ese modelo: si se usa por
    error, el template no truena — Django resuelve el atributo faltante a
    '', así que la comparación siempre da falso y el badge/modal quedan
    pegados en 'Pruebas' pase lo que pase)."""

    def setUp(self):
        self.admin = User.objects.create_user('config_admin_render', password='clave-test-123')
        self.admin.user_permissions.set(
            Permission.objects.filter(codename='change_configuracionsistema')
        )
        self.client.force_login(self.admin)

    def test_badge_y_modal_muestran_produccion_cuando_la_empresa_activa_esta_en_produccion(self):
        EmpresaFacturacionElectronica.objects.create(
            ruc='1790000000001', razon_social='Empresa Producción', direccion_matriz='Dirección',
            codigo_establecimiento='001', codigo_punto_emision='001', empresa_id_microservicio='1',
            api_key='clave-1', activa=True, ambiente=ConfiguracionSistema.AMBIENTE_PRODUCCION,
        )

        response = self.client.get(reverse('configuracion:configuracion_editar'))

        self.assertContains(response, 'badge bg-success">Producción')
        self.assertNotContains(response, 'badge bg-warning text-dark">Pruebas')
        # El modal de confirmación debe advertir "producción -> pruebas" (el sentido inverso).
        self.assertContains(response, 'de <strong>Producción</strong> a <strong>Pruebas</strong>')

    def test_badge_y_modal_muestran_pruebas_cuando_la_empresa_activa_esta_en_pruebas(self):
        EmpresaFacturacionElectronica.objects.create(
            ruc='1790000000001', razon_social='Empresa Pruebas', direccion_matriz='Dirección',
            codigo_establecimiento='001', codigo_punto_emision='001', empresa_id_microservicio='1',
            api_key='clave-1', activa=True, ambiente=ConfiguracionSistema.AMBIENTE_PRUEBAS,
        )

        response = self.client.get(reverse('configuracion:configuracion_editar'))

        self.assertContains(response, 'badge bg-warning text-dark">Pruebas')
        self.assertNotContains(response, 'badge bg-success">Producción')
        self.assertContains(response, 'de <strong>Pruebas</strong> a <strong>Producción</strong>')


class EditarEmpresaActivaViewTests(TestCase):
    """Modal 'Editar datos' de la empresa activa (configuracion/views.py ->
    editar_empresa_activa)."""

    def setUp(self):
        self.admin = User.objects.create_user('config_admin_editar', password='clave-test-123')
        self.admin.user_permissions.set(
            Permission.objects.filter(codename='change_configuracionsistema')
        )
        self.vendedor = User.objects.create_user('config_vendedor_editar', password='clave-test-123')
        self.empresa = EmpresaFacturacionElectronica.objects.create(
            ruc='1790000000001', razon_social='Nombre Viejo', direccion_matriz='Dirección Vieja',
            codigo_establecimiento='001', codigo_punto_emision='001',
            empresa_id_microservicio='42', api_key='clave-activa', activa=True,
        )
        self.datos_formulario = {
            'razon_social': 'Nombre Nuevo', 'direccion_matriz': 'Dirección Nueva',
            'establecimiento': '002', 'punto_emision': '002', 'ambiente': ConfiguracionSistema.AMBIENTE_PRODUCCION,
        }

    @patch('facturacion_electronica.services.editar_empresa')
    def test_edita_datos_exitosamente_sin_tocar_el_ruc(self, mock_editar):
        self.client.force_login(self.admin)
        mock_editar.return_value = {'id': 42, 'razon_social': 'Nombre Nuevo'}

        response = self.client.post(
            reverse('configuracion:editar_empresa_activa'),
            {**self.datos_formulario, 'certificado_p12': '', 'certificado_password': ''},
        )

        self.assertEqual(response.status_code, 302)
        mock_editar.assert_called_once_with('42', {
            'razon_social': 'Nombre Nuevo', 'direccion_matriz': 'Dirección Nueva',
            'establecimiento': '002', 'punto_emision': '002', 'ambiente': ConfiguracionSistema.AMBIENTE_PRODUCCION,
        })
        self.empresa.refresh_from_db()
        self.assertEqual(self.empresa.razon_social, 'Nombre Nuevo')
        self.assertEqual(self.empresa.ambiente, ConfiguracionSistema.AMBIENTE_PRODUCCION)
        self.assertEqual(self.empresa.ruc, '1790000000001')  # el RUC no cambió

    @patch('facturacion_electronica.services.subir_certificado')
    @patch('facturacion_electronica.services.editar_empresa')
    def test_edita_datos_y_renueva_certificado_cuando_se_adjunta(self, mock_editar, mock_subir):
        self.client.force_login(self.admin)
        mock_editar.return_value = {'id': 42}
        mock_subir.return_value = {'ok': True}

        response = self.client.post(
            reverse('configuracion:editar_empresa_activa'),
            {**self.datos_formulario, 'certificado_p12': _archivo_certificado(), 'certificado_password': 'secreta123'},
        )

        self.assertEqual(response.status_code, 302)
        mock_subir.assert_called_once()
        args = mock_subir.call_args[0]
        self.assertEqual(args[0], '42')
        self.assertEqual(args[1], 'clave-activa')
        self.assertEqual(args[3], 'secreta123')

    def test_certificado_requiere_archivo_y_password_juntos(self):
        self.client.force_login(self.admin)

        response = self.client.post(
            reverse('configuracion:editar_empresa_activa'),
            {**self.datos_formulario, 'certificado_p12': _archivo_certificado(), 'certificado_password': ''},
            follow=True,
        )

        mensajes = [str(m) for m in response.context['messages']]
        self.assertTrue(any('los dos juntos' in m for m in mensajes))
        self.empresa.refresh_from_db()
        self.assertEqual(self.empresa.razon_social, 'Nombre Viejo')  # no se guardó nada

    @patch('facturacion_electronica.services.editar_empresa')
    def test_error_del_microservicio_muestra_mensaje_claro_no_500(self, mock_editar):
        self.client.force_login(self.admin)
        mock_editar.side_effect = SRIError('Código de establecimiento inválido.')

        response = self.client.post(
            reverse('configuracion:editar_empresa_activa'),
            {**self.datos_formulario, 'certificado_p12': '', 'certificado_password': ''},
            follow=True,
        )

        self.assertEqual(response.status_code, 200)  # nunca 500
        mensajes = [str(m) for m in response.context['messages']]
        self.assertIn('Código de establecimiento inválido.', mensajes)
        self.empresa.refresh_from_db()
        self.assertEqual(self.empresa.razon_social, 'Nombre Viejo')  # no se guardó nada

    def test_sin_empresa_activa_muestra_error(self):
        self.empresa.delete()
        self.client.force_login(self.admin)

        response = self.client.post(
            reverse('configuracion:editar_empresa_activa'),
            {**self.datos_formulario, 'certificado_p12': '', 'certificado_password': ''},
            follow=True,
        )

        mensajes = [str(m) for m in response.context['messages']]
        self.assertIn('No hay ninguna empresa activa para editar.', mensajes)

    def test_usuario_sin_permiso_no_puede_editar(self):
        self.client.force_login(self.vendedor)
        response = self.client.post(
            reverse('configuracion:editar_empresa_activa'),
            {**self.datos_formulario, 'certificado_p12': '', 'certificado_password': ''},
        )
        self.assertEqual(response.status_code, 302)
        self.empresa.refresh_from_db()
        self.assertEqual(self.empresa.razon_social, 'Nombre Viejo')


class CambiarAmbienteEmpresaActivaViewTests(TestCase):
    """Botón 'Cambiar de ambiente' con confirmación (configuracion/views.py
    -> cambiar_ambiente_empresa_activa)."""

    def setUp(self):
        self.admin = User.objects.create_user('config_admin_ambiente', password='clave-test-123')
        self.admin.user_permissions.set(
            Permission.objects.filter(codename='change_configuracionsistema')
        )
        self.vendedor = User.objects.create_user('config_vendedor_ambiente', password='clave-test-123')

    @patch('facturacion_electronica.services.editar_empresa')
    def test_cambia_de_pruebas_a_produccion(self, mock_editar):
        empresa = EmpresaFacturacionElectronica.objects.create(
            ruc='1790000000001', razon_social='TecnoStock S.A.', direccion_matriz='Dirección',
            codigo_establecimiento='001', codigo_punto_emision='001', empresa_id_microservicio='42',
            api_key='clave-activa', activa=True, ambiente=ConfiguracionSistema.AMBIENTE_PRUEBAS,
        )
        self.client.force_login(self.admin)
        mock_editar.return_value = {'id': 42, 'ambiente': 'produccion'}

        response = self.client.post(reverse('configuracion:cambiar_ambiente_empresa_activa'))

        self.assertEqual(response.status_code, 302)
        mock_editar.assert_called_once_with('42', {'ambiente': ConfiguracionSistema.AMBIENTE_PRODUCCION})
        empresa.refresh_from_db()
        self.assertEqual(empresa.ambiente, ConfiguracionSistema.AMBIENTE_PRODUCCION)

    @patch('facturacion_electronica.services.editar_empresa')
    def test_cambia_de_produccion_a_pruebas(self, mock_editar):
        empresa = EmpresaFacturacionElectronica.objects.create(
            ruc='1790000000001', razon_social='TecnoStock S.A.', direccion_matriz='Dirección',
            codigo_establecimiento='001', codigo_punto_emision='001', empresa_id_microservicio='42',
            api_key='clave-activa', activa=True, ambiente=ConfiguracionSistema.AMBIENTE_PRODUCCION,
        )
        self.client.force_login(self.admin)
        mock_editar.return_value = {'id': 42, 'ambiente': 'pruebas'}

        response = self.client.post(reverse('configuracion:cambiar_ambiente_empresa_activa'))

        self.assertEqual(response.status_code, 302)
        mock_editar.assert_called_once_with('42', {'ambiente': ConfiguracionSistema.AMBIENTE_PRUEBAS})
        empresa.refresh_from_db()
        self.assertEqual(empresa.ambiente, ConfiguracionSistema.AMBIENTE_PRUEBAS)

    @patch('facturacion_electronica.services.editar_empresa')
    def test_error_del_microservicio_muestra_mensaje_claro_no_500(self, mock_editar):
        empresa = EmpresaFacturacionElectronica.objects.create(
            ruc='1790000000001', razon_social='TecnoStock S.A.', direccion_matriz='Dirección',
            codigo_establecimiento='001', codigo_punto_emision='001', empresa_id_microservicio='42',
            api_key='clave-activa', activa=True, ambiente=ConfiguracionSistema.AMBIENTE_PRUEBAS,
        )
        self.client.force_login(self.admin)
        mock_editar.side_effect = SRIError('El microservicio no está disponible.')

        response = self.client.post(reverse('configuracion:cambiar_ambiente_empresa_activa'), follow=True)

        self.assertEqual(response.status_code, 200)  # nunca 500
        mensajes = [str(m) for m in response.context['messages']]
        self.assertIn('El microservicio no está disponible.', mensajes)
        empresa.refresh_from_db()
        self.assertEqual(empresa.ambiente, ConfiguracionSistema.AMBIENTE_PRUEBAS)  # no cambió

    def test_sin_empresa_activa_muestra_error(self):
        self.client.force_login(self.admin)
        response = self.client.post(reverse('configuracion:cambiar_ambiente_empresa_activa'), follow=True)
        mensajes = [str(m) for m in response.context['messages']]
        self.assertIn('No hay ninguna empresa activa.', mensajes)

    def test_usuario_sin_permiso_no_puede_cambiar(self):
        empresa = EmpresaFacturacionElectronica.objects.create(
            ruc='1790000000001', razon_social='TecnoStock S.A.', direccion_matriz='Dirección',
            codigo_establecimiento='001', codigo_punto_emision='001', empresa_id_microservicio='42',
            api_key='clave-activa', activa=True, ambiente=ConfiguracionSistema.AMBIENTE_PRUEBAS,
        )
        self.client.force_login(self.vendedor)
        response = self.client.post(reverse('configuracion:cambiar_ambiente_empresa_activa'))
        self.assertEqual(response.status_code, 302)
        empresa.refresh_from_db()
        self.assertEqual(empresa.ambiente, ConfiguracionSistema.AMBIENTE_PRUEBAS)
