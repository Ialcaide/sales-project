# Migración de datos: otorga los permisos de facturación electrónica (SRI)
# al rol "Vendedor" si ya existía — mismo cuidado aditivo que las
# migraciones 0002/0004 (Group.permissions.add(), nunca .set(), para no
# pisar personalizaciones hechas desde Seguridad > Permisos).
from django.db import migrations


def otorgar_permisos(apps, schema_editor):
    Group = apps.get_model('auth', 'Group')
    Permission = apps.get_model('auth', 'Permission')
    ContentType = apps.get_model('contenttypes', 'ContentType')

    content_type, _ = ContentType.objects.get_or_create(
        app_label='facturacion_electronica', model='comprobanteelectronico',
    )
    codenames_y_nombres = [
        ('view_comprobanteelectronico', 'Can view comprobante electrónico'),
        ('add_comprobanteelectronico', 'Can add comprobante electrónico'),
    ]
    permisos = []
    for codename, name in codenames_y_nombres:
        permiso, _ = Permission.objects.get_or_create(
            content_type=content_type, codename=codename, defaults={'name': name},
        )
        permisos.append(permiso)

    vendedor = Group.objects.filter(name='Vendedor').first()
    if vendedor is not None:
        for permiso in permisos:
            vendedor.permissions.add(permiso)


def revertir(apps, schema_editor):
    # No se quita nada al revertir: son permisos aditivos.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('security', '0004_grant_export_and_whatsapp_permissions'),
        ('facturacion_electronica', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(otorgar_permisos, revertir),
    ]
