# Migración de datos: otorga los nuevos permisos "access_<modelo>_module"
# (agregados junto con esta migración en billing/purchasing/pagos/cobros/
# caja/devoluciones) a los roles que YA existían y que hoy dependen de ese
# acceso — sin usar Group.permissions.set(), que pisaría cualquier permiso
# que un administrador haya agregado o quitado a mano desde Seguridad >
# Permisos (ver setup_roles.py, que tiene el mismo cuidado). Se usa .add()
# en su lugar: solo agrega, nunca quita nada.
#
# OJO con el orden: los permisos declarados en Meta.permissions recién se
# crean en la base de datos cuando el signal post_migrate corre, DESPUÉS de
# que TODAS las migraciones de este `migrate` terminan — así que acá no se
# puede asumir que el Permission ya existe. Por eso se crea con
# get_or_create() manualmente (mismo patrón que usa internamente
# django.contrib.auth.management.create_permissions); cuando el
# post_migrate real corra después, va a encontrar la fila ya creada y no
# va a duplicar nada (también matchea por content_type + codename).
from django.db import migrations


# (app_label, model, codename, name) de cada permiso nuevo.
NUEVOS_PERMISOS = [
    ('billing', 'brand', 'access_brand_module', 'Acceso al módulo de marcas'),
    ('billing', 'productgroup', 'access_productgroup_module', 'Acceso al módulo de grupos de productos'),
    ('billing', 'supplier', 'access_supplier_module', 'Acceso al módulo de proveedores'),
    ('billing', 'product', 'access_product_module', 'Acceso al módulo de productos'),
    ('billing', 'customer', 'access_customer_module', 'Acceso al módulo de clientes'),
    ('billing', 'invoice', 'access_invoice_module', 'Acceso al módulo de facturas'),
    ('purchasing', 'purchase', 'access_purchase_module', 'Acceso al módulo de compras'),
    ('pagos', 'pagocompra', 'access_pagocompra_module', 'Acceso al módulo de pagos a proveedores'),
    ('cobros', 'cobrofactura', 'access_cobrofactura_module', 'Acceso al módulo de cobros a clientes'),
    ('caja', 'sesioncaja', 'access_sesioncaja_module', 'Acceso al módulo de caja'),
    ('devoluciones', 'devolucionventa', 'access_devolucionventa_module', 'Acceso al módulo de devoluciones'),
]

# Qué rol pre-existente necesita cuáles de esos permisos nuevos, para
# conservar exactamente el mismo acceso que ya tenía (antes, el permiso
# view_<modelo> alcanzaba tanto para el botón "Ver" como para entrar al
# listado completo; ahora hacen falta los dos por separado).
ROLES_A_ACTUALIZAR = {
    'Vendedor': [
        'access_customer_module', 'access_invoice_module', 'access_product_module',
        'access_cobrofactura_module', 'access_sesioncaja_module', 'access_devolucionventa_module',
    ],
    'Analista de Compras': [
        'access_brand_module', 'access_productgroup_module', 'access_supplier_module',
        'access_product_module', 'access_purchase_module', 'access_pagocompra_module',
    ],
    'Cajero': [
        'access_sesioncaja_module', 'access_invoice_module',
        'access_product_module', 'access_customer_module', 'access_devolucionventa_module',
    ],
}


def otorgar_acceso_a_modulos(apps, schema_editor):
    Group = apps.get_model('auth', 'Group')
    Permission = apps.get_model('auth', 'Permission')
    ContentType = apps.get_model('contenttypes', 'ContentType')

    permisos_por_codename = {}
    for app_label, model, codename, name in NUEVOS_PERMISOS:
        content_type, _ = ContentType.objects.get_or_create(app_label=app_label, model=model)
        permiso, _ = Permission.objects.get_or_create(
            content_type=content_type, codename=codename, defaults={'name': name},
        )
        permisos_por_codename[codename] = permiso

    for role_name, codenames in ROLES_A_ACTUALIZAR.items():
        # Si el rol todavía no existe (instalación nueva, sin setup_roles
        # corrido todavía), no hay nada que actualizar — setup_roles lo va a
        # crear con la lista completa de permisos, nuevos incluidos.
        group = Group.objects.filter(name=role_name).first()
        if group is None:
            continue
        for codename in codenames:
            group.permissions.add(permisos_por_codename[codename])


def revertir(apps, schema_editor):
    # No se quita nada al revertir: son permisos aditivos y quitarlos podría
    # borrar una personalización manual posterior que ya no tiene relación
    # con esta migración.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('security', '0001_initial'),
        ('billing', '0013_alter_brand_options_alter_customer_options_and_more'),
        ('purchasing', '0006_alter_purchase_options'),
        ('pagos', '0004_alter_pagocompra_options'),
        ('cobros', '0004_alter_cobrofactura_options'),
        ('caja', '0004_alter_sesioncaja_options'),
        ('devoluciones', '0002_alter_devolucionventa_options'),
    ]

    operations = [
        migrations.RunPython(otorgar_acceso_a_modulos, revertir),
    ]
