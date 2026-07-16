# Migración de datos: otorga los nuevos permisos "export_pdf_<modelo>",
# "export_excel_<modelo>" y "send_whatsapp_<modelo>" (agregados junto con
# esta migración en billing/purchasing/security) a los roles que YA existían
# y que hoy usan esos botones — sin usar Group.permissions.set(), que
# pisaría cualquier permiso agregado/quitado a mano desde Seguridad >
# Permisos (mismo cuidado que 0002_grant_module_access_to_existing_roles.py).
from django.db import migrations


# (app_label, model, codename, name) de cada permiso nuevo.
NUEVOS_PERMISOS = [
    ('billing', 'brand', 'export_pdf_brand', 'Puede exportar marcas a PDF'),
    ('billing', 'brand', 'export_excel_brand', 'Puede exportar marcas a Excel'),
    ('billing', 'productgroup', 'export_pdf_productgroup', 'Puede exportar grupos de productos a PDF'),
    ('billing', 'productgroup', 'export_excel_productgroup', 'Puede exportar grupos de productos a Excel'),
    ('billing', 'supplier', 'export_pdf_supplier', 'Puede exportar proveedores a PDF'),
    ('billing', 'supplier', 'export_excel_supplier', 'Puede exportar proveedores a Excel'),
    ('billing', 'product', 'export_pdf_product', 'Puede exportar productos a PDF'),
    ('billing', 'product', 'export_excel_product', 'Puede exportar productos a Excel'),
    ('billing', 'customer', 'export_pdf_customer', 'Puede exportar clientes a PDF'),
    ('billing', 'customer', 'export_excel_customer', 'Puede exportar clientes a Excel'),
    ('billing', 'invoice', 'export_pdf_invoice', 'Puede exportar facturas a PDF'),
    ('billing', 'invoice', 'export_excel_invoice', 'Puede exportar facturas a Excel'),
    ('billing', 'invoice', 'send_whatsapp_invoice', 'Puede enviar recordatorio de pago por WhatsApp'),
    ('purchasing', 'purchase', 'export_pdf_purchase', 'Puede exportar compras a PDF'),
    ('purchasing', 'purchase', 'export_excel_purchase', 'Puede exportar compras a Excel'),
    ('security', 'userprofile', 'send_whatsapp_userprofile', 'Puede enviar acceso al sistema por WhatsApp'),
]

# Qué rol pre-existente necesita cuáles de esos permisos nuevos, para
# conservar exactamente el mismo acceso que ya tenía (antes, exportar o
# enviar el WhatsApp no pedía ningún permiso aparte del que ya diera acceso
# al listado).
ROLES_A_ACTUALIZAR = {
    'Vendedor': [
        'export_pdf_customer', 'export_excel_customer',
        'export_pdf_invoice', 'export_excel_invoice', 'send_whatsapp_invoice',
    ],
    'Analista de Compras': [
        'export_pdf_brand', 'export_excel_brand',
        'export_pdf_productgroup', 'export_excel_productgroup',
        'export_pdf_supplier', 'export_excel_supplier',
        'export_pdf_product', 'export_excel_product',
        'export_pdf_purchase', 'export_excel_purchase',
    ],
    'Cajero': [
        'export_pdf_invoice', 'export_excel_invoice',
        'export_pdf_product', 'export_excel_product',
        'export_pdf_customer', 'export_excel_customer',
    ],
}


def otorgar_permisos(apps, schema_editor):
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
        group = Group.objects.filter(name=role_name).first()
        if group is None:
            continue
        for codename in codenames:
            group.permissions.add(permisos_por_codename[codename])


def revertir(apps, schema_editor):
    # No se quita nada al revertir: son permisos aditivos y quitarlos podría
    # borrar una personalización manual posterior sin relación con esto.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('security', '0003_alter_userprofile_options'),
        ('billing', '0014_alter_brand_options_alter_customer_options_and_more'),
        ('purchasing', '0007_alter_purchase_options'),
    ]

    operations = [
        migrations.RunPython(otorgar_permisos, revertir),
    ]
