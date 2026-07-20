from django.db import migrations


def migrar_conexion_existente(apps, schema_editor):
    """Si ConfiguracionSistema ya tenía una empresa conectada
    (empresa_id_facturacion_electronica no vacío), la traslada a un
    EmpresaFacturacionElectronica marcado activo — para no perder la
    conexión al eliminar esos campos del singleton (ver migración 0008)."""
    ConfiguracionSistema = apps.get_model('configuracion', 'ConfiguracionSistema')
    EmpresaFacturacionElectronica = apps.get_model('configuracion', 'EmpresaFacturacionElectronica')

    config = ConfiguracionSistema.objects.filter(pk=1).first()
    if config is None or not config.empresa_id_facturacion_electronica:
        return

    EmpresaFacturacionElectronica.objects.create(
        ruc=config.empresa_ruc,
        razon_social=config.empresa_nombre,
        direccion_matriz=config.empresa_direccion,
        codigo_establecimiento=config.sri_establecimiento,
        codigo_punto_emision=config.sri_punto_emision,
        ambiente=config.sri_ambiente,
        empresa_id_microservicio=config.empresa_id_facturacion_electronica,
        api_key=config.api_key_facturacion_electronica,
        activa=True,
    )


def revertir(apps, schema_editor):
    # No hay nada sensato que "deshacer": el registro migrado se queda
    # (es la misma conexión, no un dato duplicado inventado por esta
    # migración).
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('configuracion', '0006_empresafacturacionelectronica'),
    ]

    operations = [
        migrations.RunPython(migrar_conexion_existente, revertir),
    ]
