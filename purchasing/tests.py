from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import Permission, User
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from billing.models import Brand, Product, ProductGroup, Supplier

from .forms import BodegaQuickCreateForm, PurchaseForm
from .models import Bodega, Purchase, PurchaseDetail


class PurchaseMesesCreditoModelTests(TestCase):
    def setUp(self):
        self.supplier = Supplier.objects.create(name='Proveedor Test')

    def make(self, **kwargs):
        defaults = dict(supplier=self.supplier, document_number='FAC-1', total=Decimal('100'))
        defaults.update(kwargs)
        return Purchase(**defaults)

    def test_credito_sin_meses_es_invalido(self):
        purchase = self.make(tipo_pago=Purchase.CREDITO, meses_credito=None)
        with self.assertRaises(ValidationError):
            purchase.full_clean()

    def test_credito_con_meses_en_cero_es_invalido(self):
        # PositiveSmallIntegerField no acepta 0 como "sin meses", pero igual
        # lo validamos explícito por si llega como 0 desde otro lado (admin, API).
        purchase = self.make(tipo_pago=Purchase.CREDITO, meses_credito=0)
        with self.assertRaises(ValidationError):
            purchase.full_clean()

    def test_credito_con_meses_fuera_de_rango_es_invalido(self):
        purchase = self.make(tipo_pago=Purchase.CREDITO, meses_credito=Purchase.MESES_CREDITO_MAX + 1)
        with self.assertRaises(ValidationError):
            purchase.full_clean()

    def test_credito_con_meses_valido_pasa(self):
        purchase = self.make(tipo_pago=Purchase.CREDITO, meses_credito=6)
        purchase.full_clean()  # no debe lanzar

    def test_contado_con_meses_es_invalido(self):
        purchase = self.make(tipo_pago=Purchase.CONTADO, meses_credito=3)
        with self.assertRaises(ValidationError):
            purchase.full_clean()

    def test_contado_sin_meses_pasa(self):
        purchase = self.make(tipo_pago=Purchase.CONTADO, meses_credito=None)
        purchase.full_clean()  # no debe lanzar


class PurchaseFormMesesCreditoTests(TestCase):
    def setUp(self):
        self.supplier = Supplier.objects.create(name='Proveedor Test')

    def test_form_credito_sin_meses_muestra_error(self):
        form = PurchaseForm(data={
            'supplier': self.supplier.id, 'document_number': 'FAC-2',
            'tipo_pago': Purchase.CREDITO,
        })
        self.assertFalse(form.is_valid())
        self.assertIn('meses_credito', form.errors)

    def test_form_credito_con_meses_es_valido(self):
        form = PurchaseForm(data={
            'supplier': self.supplier.id, 'document_number': 'FAC-3',
            'tipo_pago': Purchase.CREDITO, 'meses_credito': 6,
        })
        self.assertTrue(form.is_valid())

    def test_form_contado_con_meses_muestra_error(self):
        form = PurchaseForm(data={
            'supplier': self.supplier.id, 'document_number': 'FAC-4',
            'tipo_pago': Purchase.CONTADO, 'meses_credito': 3,
        })
        self.assertFalse(form.is_valid())
        self.assertIn('meses_credito', form.errors)

    def test_form_contado_sin_meses_es_valido(self):
        form = PurchaseForm(data={
            'supplier': self.supplier.id, 'document_number': 'FAC-5',
            'tipo_pago': Purchase.CONTADO,
        })
        self.assertTrue(form.is_valid())


class PurchaseFinanciamientoTests(TestCase):
    """Tasa de interés según meses, y cuota mínima resultante."""

    def setUp(self):
        self.supplier = Supplier.objects.create(name='Proveedor Test')

    def make(self, meses_credito, total='100.00', tipo_pago=Purchase.CREDITO):
        return Purchase(
            supplier=self.supplier, document_number=f'FAC-{meses_credito}',
            total=Decimal(total), tipo_pago=tipo_pago, meses_credito=meses_credito,
        )

    def test_tasa_interes_por_tramo(self):
        self.assertEqual(Purchase.tasa_interes(1), Decimal('0.05'))
        self.assertEqual(Purchase.tasa_interes(3), Decimal('0.05'))
        self.assertEqual(Purchase.tasa_interes(4), Decimal('0.10'))
        self.assertEqual(Purchase.tasa_interes(6), Decimal('0.10'))
        self.assertEqual(Purchase.tasa_interes(7), Decimal('0.15'))
        self.assertEqual(Purchase.tasa_interes(12), Decimal('0.15'))
        self.assertEqual(Purchase.tasa_interes(13), Decimal('0.20'))
        self.assertEqual(Purchase.tasa_interes(24), Decimal('0.20'))
        self.assertEqual(Purchase.tasa_interes(25), Decimal('0.25'))
        self.assertEqual(Purchase.tasa_interes(36), Decimal('0.25'))

    def test_aplicar_financiamiento_credito_calcula_interes_y_saldo(self):
        purchase = self.make(meses_credito=12, total='100.00')
        purchase.aplicar_financiamiento()
        self.assertEqual(purchase.interes, Decimal('15.00'))
        self.assertEqual(purchase.saldo, Decimal('115.00'))
        self.assertEqual(purchase.estado, Purchase.PENDIENTE)

    def test_aplicar_financiamiento_contado_sin_interes(self):
        purchase = self.make(meses_credito=None, total='100.00', tipo_pago=Purchase.CONTADO)
        purchase.aplicar_financiamiento()
        self.assertEqual(purchase.interes, Decimal('0'))
        self.assertEqual(purchase.saldo, Decimal('0'))
        self.assertEqual(purchase.estado, Purchase.PAGADA)

    def test_cuota_minima_es_total_a_pagar_entre_meses(self):
        purchase = self.make(meses_credito=4, total='100.00')  # tramo 10%
        purchase.aplicar_financiamiento()
        # total_a_pagar = 110.00 / 4 meses = 27.50
        self.assertEqual(purchase.cuota_minima, Decimal('27.50'))

    def test_cuota_minima_none_para_contado(self):
        purchase = self.make(meses_credito=None, total='100.00', tipo_pago=Purchase.CONTADO)
        purchase.aplicar_financiamiento()
        self.assertIsNone(purchase.cuota_minima)

    def test_fecha_limite_pago_suma_meses_a_la_fecha_de_compra(self):
        # purchase_date es auto_now_add, por eso acá sí se guarda (.create())
        # en vez de solo instanciar el objeto en memoria.
        purchase = Purchase.objects.create(
            supplier=self.supplier, document_number='FAC-LIMITE',
            total=Decimal('100'), tipo_pago=Purchase.CREDITO, meses_credito=5,
        )
        fecha_compra = purchase.purchase_date.date()
        limite = purchase.fecha_limite_pago
        self.assertEqual(limite.year, fecha_compra.year + (1 if fecha_compra.month + 5 > 12 else 0))
        self.assertEqual(limite.day, fecha_compra.day)

    def test_fecha_limite_pago_none_para_contado(self):
        purchase = Purchase.objects.create(
            supplier=self.supplier, document_number='FAC-LIMITE-2',
            total=Decimal('100'), tipo_pago=Purchase.CONTADO,
        )
        self.assertIsNone(purchase.fecha_limite_pago)


class PurchaseCreateViewTests(TestCase):
    """Cubre el reporte de que 'guardar compra' no guardaba nada."""

    def setUp(self):
        self.brand = Brand.objects.create(name='Marca Test')
        self.group = ProductGroup.objects.create(name='Grupo Test')
        self.supplier = Supplier.objects.create(name='Proveedor Test')
        self.product = Product.objects.create(
            name='Producto Test', brand=self.brand, group=self.group,
            unit_price=Decimal('10'), stock=0,
        )
        self.product.suppliers.add(self.supplier)

        self.user = User.objects.create_user('comprador', password='clave-test-123')
        perms = Permission.objects.filter(
            codename__in=['view_purchase', 'add_purchase', 'view_purchasedetail', 'add_purchasedetail']
        )
        self.user.user_permissions.set(perms)
        self.client.force_login(self.user)

    def _post(self, tipo_pago, meses_credito=None, document_number='FAC-E2E'):
        data = {
            'supplier': self.supplier.id,
            'document_number': document_number,
            'tipo_pago': tipo_pago,
            'details-TOTAL_FORMS': '1',
            'details-INITIAL_FORMS': '0',
            'details-MIN_NUM_FORMS': '0',
            'details-MAX_NUM_FORMS': '1000',
            'details-0-id': '',
            'details-0-product': self.product.id,
            'details-0-quantity': '5',
            'details-0-unit_cost': '10.00',
        }
        if meses_credito is not None:
            data['meses_credito'] = meses_credito
        return self.client.post(reverse('purchasing:purchase_create'), data)

    def test_guardar_compra_contado_se_guarda(self):
        response = self._post(Purchase.CONTADO)
        self.assertEqual(response.status_code, 302)
        purchase = Purchase.objects.get(document_number='FAC-E2E')
        self.assertEqual(purchase.estado, Purchase.PAGADA)
        self.assertEqual(purchase.saldo, Decimal('0.00'))

    def test_guardar_compra_credito_con_meses_se_guarda(self):
        response = self._post(Purchase.CREDITO, meses_credito=4)
        self.assertEqual(response.status_code, 302)
        purchase = Purchase.objects.get(document_number='FAC-E2E')
        self.assertEqual(purchase.meses_credito, 4)
        self.assertEqual(purchase.estado, Purchase.PENDIENTE)
        # 4 meses cae en el tramo (4-6] -> 10% de interés (ver INTERES_TIERS)
        self.assertEqual(purchase.interes, (purchase.total * Decimal('0.10')).quantize(Decimal('0.01')))
        self.assertEqual(purchase.saldo, purchase.total + purchase.interes)

    def test_guardar_compra_credito_sin_meses_no_se_guarda(self):
        response = self._post(Purchase.CREDITO)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Purchase.objects.filter(document_number='FAC-E2E').exists())

    def test_guardar_compra_invalida_muestra_mensaje_de_error(self):
        # Antes de este fix, un form.is_valid() == False no mostraba ningún
        # mensaje: la página solo se recargaba en silencio.
        response = self._post(Purchase.CREDITO)
        messages = [str(m) for m in response.context['messages']]
        self.assertTrue(any('revisa los errores señalados en el formulario' in m.lower() for m in messages))
        self.assertContains(response, 'mínimo 1')

    def test_documento_duplicado_muestra_error_no_field(self):
        # El UniqueConstraint (supplier+document_number) se valida en
        # form.is_valid() y antes quedaba invisible: no iba ligado a ningún
        # campo del formulario, solo a form.non_field_errors().
        self._post(Purchase.CONTADO, document_number='FAC-DUP')
        response = self._post(Purchase.CONTADO, document_number='FAC-DUP')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'ya existe')
        self.assertEqual(Purchase.objects.filter(document_number='FAC-DUP').count(), 1)

    def test_iva_configurado_afecta_el_impuesto_de_la_compra(self):
        from configuracion.models import ConfiguracionSistema
        config = ConfiguracionSistema.get_solo()
        config.iva_porcentaje = Decimal('8.00')
        config.save()

        self._post(Purchase.CONTADO)
        purchase = Purchase.objects.get(document_number='FAC-E2E')
        # subtotal = 5 * $10 = $50; al 8% = $4.00 (con el 15% por defecto habría sido $7.50)
        self.assertEqual(purchase.tax, Decimal('4.00'))

    def test_compra_nace_en_borrador_sin_tocar_stock_ni_last_cost(self):
        # Antes de este cambio, purchase_create subía el stock/last_cost del
        # producto de una — ahora eso se mueve a purchase_marcar_recibida
        # (ver PurchaseFaseTransitionTests), y la compra nace en Borrador.
        response = self._post(Purchase.CONTADO)
        self.assertEqual(response.status_code, 302)
        purchase = Purchase.objects.get(document_number='FAC-E2E')
        self.assertEqual(purchase.fase, Purchase.BORRADOR)
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock, 0)
        self.assertEqual(self.product.last_cost, Decimal('0.00'))


class BodegaModelTests(TestCase):
    def test_str_devuelve_el_nombre(self):
        bodega = Bodega.objects.create(nombre='Bodega Central')
        self.assertEqual(str(bodega), 'Bodega Central')

    def test_nombre_es_unico(self):
        Bodega.objects.create(nombre='Bodega Central')
        with self.assertRaises(Exception):
            Bodega.objects.create(nombre='Bodega Central')


class PurchaseDetailDescuentoTests(TestCase):
    """descuento_porcentaje debe reducir el subtotal calculado en save()."""

    def setUp(self):
        self.supplier = Supplier.objects.create(name='Proveedor Test')
        self.brand = Brand.objects.create(name='Marca Test')
        self.group = ProductGroup.objects.create(name='Grupo Test')
        self.product = Product.objects.create(
            name='Producto Test', brand=self.brand, group=self.group,
            unit_price=Decimal('10'), stock=0,
        )
        self.purchase = Purchase.objects.create(
            supplier=self.supplier, document_number='FAC-DESC', total=Decimal('0'),
        )

    def test_sin_descuento_subtotal_es_cantidad_por_costo(self):
        detail = PurchaseDetail.objects.create(
            purchase=self.purchase, product=self.product, quantity=10, unit_cost=Decimal('5.00'),
        )
        self.assertEqual(detail.subtotal, Decimal('50.00'))

    def test_con_descuento_subtotal_se_reduce_proporcionalmente(self):
        detail = PurchaseDetail.objects.create(
            purchase=self.purchase, product=self.product, quantity=10, unit_cost=Decimal('5.00'),
            descuento_porcentaje=Decimal('20.00'),
        )
        # 10 * 5.00 = 50.00; menos 20% = 40.00
        self.assertEqual(detail.subtotal, Decimal('40.00'))


class PurchaseRetencionTests(TestCase):
    """retencion_valor y monto_neto_a_pagar — puramente informativos, no
    tocan saldo/estado ni la integración con pagos.PagoCompra."""

    def setUp(self):
        self.supplier = Supplier.objects.create(name='Proveedor Test')

    def test_monto_neto_a_pagar_resta_la_retencion_del_total_a_pagar(self):
        purchase = Purchase.objects.create(
            supplier=self.supplier, document_number='FAC-RET', total=Decimal('100.00'),
            retencion_valor=Decimal('10.00'),
        )
        self.assertEqual(purchase.total_a_pagar, Decimal('100.00'))
        self.assertEqual(purchase.monto_neto_a_pagar, Decimal('90.00'))

    def test_retencion_no_afecta_saldo_ni_estado(self):
        purchase = Purchase.objects.create(
            supplier=self.supplier, document_number='FAC-RET-2', total=Decimal('100.00'),
            tipo_pago=Purchase.CREDITO, meses_credito=3, retencion_porcentaje=Decimal('10.00'),
        )
        purchase.retencion_valor = Decimal('10.00')
        purchase.aplicar_financiamiento()
        # saldo/estado se calculan solo a partir de total + interés, sin
        # restar la retención — esa resta vive solo en monto_neto_a_pagar.
        self.assertEqual(purchase.saldo, purchase.total + purchase.interes)
        self.assertEqual(purchase.estado, Purchase.PENDIENTE)


class PurchaseFacturaAdjuntaTests(TestCase):
    def test_adjunto_se_guarda_en_la_compra(self):
        supplier = Supplier.objects.create(name='Proveedor Test')
        archivo = SimpleUploadedFile('factura.pdf', b'contenido-fake-pdf', content_type='application/pdf')
        purchase = Purchase.objects.create(
            supplier=supplier, document_number='FAC-ADJ', total=Decimal('0'),
            factura_adjunta=archivo,
        )
        self.assertTrue(purchase.factura_adjunta.name.endswith('factura.pdf'))
        purchase.factura_adjunta.delete(save=False)


class PurchaseFaseTransitionTests(TestCase):
    """Flujo Borrador -> Confirmada -> Recibida: cada transición exige la
    fase inmediata anterior, y solo purchase_marcar_recibida sube el stock/
    last_cost del producto (movido acá desde purchase_create)."""

    def setUp(self):
        self.supplier = Supplier.objects.create(name='Proveedor Test')
        self.brand = Brand.objects.create(name='Marca Test')
        self.group = ProductGroup.objects.create(name='Grupo Test')
        self.product = Product.objects.create(
            name='Producto Test', brand=self.brand, group=self.group,
            unit_price=Decimal('10'), stock=5,
        )
        self.purchase = Purchase.objects.create(
            supplier=self.supplier, document_number='FAC-FASE', total=Decimal('50'),
        )
        PurchaseDetail.objects.create(
            purchase=self.purchase, product=self.product, quantity=3, unit_cost=Decimal('7.50'),
        )
        self.user = User.objects.create_user('comprador_fase', password='clave-test-123')
        self.user.user_permissions.set(
            Permission.objects.filter(codename__in=['view_purchase', 'change_purchase'])
        )
        self.client.force_login(self.user)

    def test_confirmar_pasa_de_borrador_a_confirmada(self):
        response = self.client.post(reverse('purchasing:purchase_confirmar', args=[self.purchase.pk]))
        self.assertEqual(response.status_code, 302)
        self.purchase.refresh_from_db()
        self.assertEqual(self.purchase.fase, Purchase.CONFIRMADA)

    def test_marcar_recibida_sin_confirmar_antes_es_rechazado(self):
        response = self.client.post(reverse('purchasing:purchase_marcar_recibida', args=[self.purchase.pk]))
        self.assertEqual(response.status_code, 302)
        self.purchase.refresh_from_db()
        self.assertEqual(self.purchase.fase, Purchase.BORRADOR)
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock, 5)  # sin cambios

    def test_marcar_recibida_despues_de_confirmar_sube_stock_y_last_cost(self):
        self.client.post(reverse('purchasing:purchase_confirmar', args=[self.purchase.pk]))
        response = self.client.post(reverse('purchasing:purchase_marcar_recibida', args=[self.purchase.pk]))
        self.assertEqual(response.status_code, 302)
        self.purchase.refresh_from_db()
        self.assertEqual(self.purchase.fase, Purchase.RECIBIDA)
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock, 8)  # 5 + 3
        self.assertEqual(self.product.last_cost, Decimal('7.50'))

    def test_confirmar_dos_veces_es_rechazado(self):
        self.client.post(reverse('purchasing:purchase_confirmar', args=[self.purchase.pk]))
        response = self.client.post(reverse('purchasing:purchase_confirmar', args=[self.purchase.pk]), follow=True)
        messages = [str(m) for m in response.context['messages']]
        self.assertTrue(any('ya no está en Borrador' in m for m in messages))

    def test_usuario_sin_permiso_no_puede_confirmar(self):
        user_sin_permiso = User.objects.create_user('sin_permiso_fase', password='clave-test-123')
        self.client.force_login(user_sin_permiso)
        response = self.client.post(reverse('purchasing:purchase_confirmar', args=[self.purchase.pk]))
        self.assertEqual(response.status_code, 302)
        self.purchase.refresh_from_db()
        self.assertEqual(self.purchase.fase, Purchase.BORRADOR)


class PurchaseFormRetencionRangeTests(TestCase):
    """retencion_porcentaje no tiene min_value/max_value propios (a
    diferencia de descuento_porcentaje en PurchaseDetailForm) por venir de
    un ModelForm automático — clean_retencion_porcentaje() cierra ese hueco:
    sin validación server-side, un POST directo (sin pasar por el <input
    min/max> del navegador) podía guardar -5% o 250%."""

    def setUp(self):
        self.supplier = Supplier.objects.create(name='Proveedor Test')

    def _form(self, retencion):
        return PurchaseForm(data={
            'supplier': self.supplier.id, 'document_number': 'FAC-RET',
            'tipo_pago': Purchase.CONTADO, 'retencion_porcentaje': retencion,
        })

    def test_retencion_negativa_es_invalida(self):
        form = self._form('-5')
        self.assertFalse(form.is_valid())
        self.assertIn('retencion_porcentaje', form.errors)

    def test_retencion_mayor_a_100_es_invalida(self):
        form = self._form('250')
        self.assertFalse(form.is_valid())
        self.assertIn('retencion_porcentaje', form.errors)

    def test_retencion_en_rango_es_valida(self):
        form = self._form('10')
        self.assertTrue(form.is_valid())

    def test_retencion_en_cero_es_valida(self):
        form = self._form('0')
        self.assertTrue(form.is_valid())


class BodegaQuickCreateFormTests(TestCase):
    def test_nombre_vacio_es_invalido(self):
        form = BodegaQuickCreateForm(data={'nombre': ''})
        self.assertFalse(form.is_valid())

    def test_nombre_valido_crea_bodega(self):
        form = BodegaQuickCreateForm(data={'nombre': 'Bodega Norte'})
        self.assertTrue(form.is_valid())
        bodega = form.save()
        self.assertEqual(bodega.nombre, 'Bodega Norte')


class BodegaQuickCreateViewTests(TestCase):
    """Endpoint AJAX del botón '+ Nueva bodega' del paso 1 del wizard de
    compra — hoy es la única forma de crear bodegas fuera de /admin/."""

    def setUp(self):
        self.user = User.objects.create_user('comprador_bodega', password='clave-test-123')
        self.user.user_permissions.set(Permission.objects.filter(codename='add_purchase'))
        self.client.force_login(self.user)

    def test_post_valido_crea_bodega_y_responde_201(self):
        response = self.client.post(reverse('purchasing:bodega_quick_create'), {'nombre': 'Bodega Sur'})
        self.assertEqual(response.status_code, 201)
        payload = response.json()
        self.assertTrue(payload['ok'])
        self.assertEqual(payload['bodega']['label'], 'Bodega Sur')
        self.assertTrue(Bodega.objects.filter(nombre='Bodega Sur').exists())

    def test_post_invalido_responde_400_sin_crear_nada(self):
        response = self.client.post(reverse('purchasing:bodega_quick_create'), {'nombre': ''})
        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.json()['ok'])

    def test_usuario_sin_permiso_queda_bloqueado(self):
        user_sin_permiso = User.objects.create_user('sin_permiso_bodega', password='clave-test-123')
        self.client.force_login(user_sin_permiso)
        response = self.client.post(reverse('purchasing:bodega_quick_create'), {'nombre': 'Bodega Bloqueada'})
        self.assertEqual(response.status_code, 302)
        self.assertFalse(Bodega.objects.filter(nombre='Bodega Bloqueada').exists())


class PurchaseFechaEntregaEstimadaAutomaticaTests(TestCase):
    """fecha_entrega_estimada ya no se pide en el wizard — es un cálculo
    automático (purchase_date + 24h) que se muestra como aviso de
    seguimiento, no como campo editable."""

    def setUp(self):
        self.brand = Brand.objects.create(name='Marca Test')
        self.group = ProductGroup.objects.create(name='Grupo Test')
        self.supplier = Supplier.objects.create(name='Proveedor Test')
        self.product = Product.objects.create(
            name='Producto Test', brand=self.brand, group=self.group,
            unit_price=Decimal('10'), stock=0,
        )
        self.user = User.objects.create_user('comprador_fecha', password='clave-test-123')
        perms = Permission.objects.filter(
            codename__in=['view_purchase', 'add_purchase', 'view_purchasedetail', 'add_purchasedetail']
        )
        self.user.user_permissions.set(perms)
        self.client.force_login(self.user)

    def test_fecha_entrega_estimada_es_24h_despues_de_la_compra(self):
        purchase = Purchase.objects.create(
            supplier=self.supplier, document_number='FAC-ETA', total=Decimal('50'),
        )
        self.assertEqual(purchase.fecha_entrega_estimada, purchase.purchase_date + timedelta(hours=24))

    def test_fecha_entrega_estimada_none_sin_guardar(self):
        purchase = Purchase(supplier=self.supplier, document_number='FAC-ETA-2', total=Decimal('50'))
        self.assertIsNone(purchase.fecha_entrega_estimada)

    def test_guardar_compra_muestra_aviso_de_seguimiento_con_eta(self):
        response = self.client.post(reverse('purchasing:purchase_create'), {
            'supplier': self.supplier.id,
            'document_number': 'FAC-ETA-3',
            'tipo_pago': Purchase.CONTADO,
            'details-TOTAL_FORMS': '1',
            'details-INITIAL_FORMS': '0',
            'details-MIN_NUM_FORMS': '0',
            'details-MAX_NUM_FORMS': '1000',
            'details-0-id': '',
            'details-0-product': self.product.id,
            'details-0-quantity': '5',
            'details-0-unit_cost': '10.00',
        })
        self.assertEqual(response.status_code, 302)
        purchase = Purchase.objects.get(document_number='FAC-ETA-3')
        from django.contrib.messages import get_messages
        messages_list = [str(m) for m in get_messages(response.wsgi_request)]
        self.assertTrue(any('Seguimiento' in m and '~24 horas' in m for m in messages_list))
        self.assertIsNotNone(purchase.fecha_entrega_estimada)
