from django.core.management.base import BaseCommand
from django.contrib.auth.models import Group, Permission

ROLES = {
    'Administrador': '__all__',
    'Vendedor': [
        'view_customer', 'add_customer', 'change_customer', 'access_customer_module',
        'export_pdf_customer', 'export_excel_customer',
        'view_customerprofile', 'add_customerprofile', 'change_customerprofile',
        'view_invoice', 'add_invoice', 'change_invoice', 'access_invoice_module',
        'export_pdf_invoice', 'export_excel_invoice', 'send_whatsapp_invoice',
        'view_invoicedetail', 'add_invoicedetail', 'change_invoicedetail',
        'view_product', 'access_product_module',
        'view_cobrofactura', 'add_cobrofactura', 'change_cobrofactura', 'delete_cobrofactura',
        'access_cobrofactura_module',
        # Caja: un vendedor puede abrir/usar su propia caja para vender al
        # contado en efectivo (invoice_create exige una SesionCaja propia
        # abierta cuando forma_pago == 'efectivo', ver billing/views.py).
        'view_sesioncaja', 'add_sesioncaja', 'change_sesioncaja', 'add_movimientocaja', 'access_sesioncaja_module',
        'view_devolucionventa', 'add_devolucionventa', 'access_devolucionventa_module',
        'view_notificacion', 'change_notificacion',
        # Facturación electrónica (SRI): ver el estado/RIDE de sus ventas y
        # poder reintentar si el envío automático falló (ver
        # facturacion_electronica/services.py).
        'view_comprobanteelectronico', 'add_comprobanteelectronico',
    ],
    'Analista de Compras': [
        'view_brand', 'add_brand', 'change_brand', 'delete_brand', 'access_brand_module',
        'export_pdf_brand', 'export_excel_brand',
        'view_productgroup', 'add_productgroup', 'change_productgroup', 'delete_productgroup',
        'access_productgroup_module', 'export_pdf_productgroup', 'export_excel_productgroup',
        'view_supplier', 'add_supplier', 'change_supplier', 'delete_supplier', 'access_supplier_module',
        'export_pdf_supplier', 'export_excel_supplier',
        'view_product', 'add_product', 'change_product', 'delete_product', 'access_product_module',
        'export_pdf_product', 'export_excel_product',
        'view_purchase', 'add_purchase', 'change_purchase', 'delete_purchase', 'access_purchase_module',
        'export_pdf_purchase', 'export_excel_purchase',
        'view_purchasedetail', 'add_purchasedetail', 'change_purchasedetail',
        'view_pagocompra', 'add_pagocompra', 'change_pagocompra', 'delete_pagocompra', 'access_pagocompra_module',
        # Caja: un pago en EFECTIVO a un proveedor sale físicamente de una
        # caja abierta del usuario (pago_create exige una SesionCaja propia
        # abierta cuando forma_pago == 'efectivo', ver pagos/views.py) —
        # mismo criterio espejo que Vendedor con las ventas en efectivo.
        'view_sesioncaja', 'add_sesioncaja', 'change_sesioncaja', 'add_movimientocaja',
        'view_notificacion', 'change_notificacion',
    ],
    'Cajero': [
        'view_sesioncaja', 'add_sesioncaja', 'change_sesioncaja', 'access_sesioncaja_module',
        'view_movimientocaja', 'add_movimientocaja',
        'view_invoice', 'add_invoice', 'view_invoicedetail', 'add_invoicedetail', 'access_invoice_module',
        'export_pdf_invoice', 'export_excel_invoice',
        'view_product', 'access_product_module', 'export_pdf_product', 'export_excel_product',
        'view_customer', 'access_customer_module', 'export_pdf_customer', 'export_excel_customer',
        'view_devolucionventa', 'add_devolucionventa', 'access_devolucionventa_module',
        'view_notificacion', 'change_notificacion',
    ],
    # Solo lectura: navega billing/purchasing/caja/cobros/pagos/devoluciones
    # (para el detalle de cada registro) y los 4 reportes de reportes/views.py
    # (que reusan estos mismos view_* — ver la nota en setup_roles sobre por
    # qué reportes no tiene permisos propios).
    'Contador': [
        'view_brand', 'view_productgroup', 'view_supplier', 'view_product',
        'view_customer', 'view_customerprofile',
        'view_invoice', 'view_invoicedetail',
        'view_purchase', 'view_purchasedetail',
        'view_sesioncaja', 'view_movimientocaja',
        'view_cobrofactura', 'view_pagocompra',
        'view_devolucionventa', 'view_devoluciondetalle',
    ],
}

class Command(BaseCommand):
    help = 'Crea los roles iniciales del sistema con sus permisos por defecto'

    def add_arguments(self, parser):
        # Sin --reset (default): solo crea los roles que todavía no existen y
        # deja intactos los permisos de los que ya existen — así, si un
        # administrador agregó o quitó un permiso a mano desde Seguridad >
        # Permisos, volver a correr este comando (ej. en cada deploy) NO le
        # pisa esa personalización. Antes, `group.permissions.set(...)`
        # corría SIEMPRE, incluso sobre roles ya existentes, y cualquier
        # cambio manual quedaba silenciosamente revertido a esta lista fija
        # la próxima vez que alguien ejecutara el comando.
        parser.add_argument(
            '--reset', action='store_true',
            help='Restaura los permisos de TODOS los roles (incluidos los ya existentes) a esta lista por defecto, '
                 'descartando cualquier cambio manual hecho desde Seguridad > Permisos.',
        )

    def handle(self, *args, **kwargs):
        reset = kwargs['reset']
        for role_name, codenames in ROLES.items():
            group, created = Group.objects.get_or_create(name=role_name)

            if not created and not reset:
                self.stdout.write(self.style.WARNING(
                    f'Rol "{role_name}" ya existía — se dejan sus permisos actuales sin tocar '
                    f'(usa --reset si de verdad quieres restaurarlos a los de por defecto).'
                ))
                continue

            if codenames == '__all__':
                perms = Permission.objects.all()
            else:
                perms = Permission.objects.filter(codename__in=codenames)

            group.permissions.set(perms)

            status = 'creado' if created else 'restaurado a los permisos por defecto'
            self.stdout.write(self.style.SUCCESS(
                f'Rol "{role_name}" {status} con {perms.count()} permisos'
            ))