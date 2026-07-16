from django.db import migrations


def _generar_barcode(pk):
    """Misma lógica que Product._generar_barcode() (billing/models.py) —
    se duplica acá porque una migración de datos no debe depender del
    código de la app actual (que puede cambiar después de esta migración)."""
    base = f'200{pk:09d}'
    pesos = sum(int(d) * (3 if i % 2 else 1) for i, d in enumerate(base))
    digito_verificador = (10 - (pesos % 10)) % 10
    return f'{base}{digito_verificador}'


def backfill_barcodes(apps, schema_editor):
    Product = apps.get_model('billing', 'Product')
    for product in Product.objects.filter(barcode__isnull=True):
        product.barcode = _generar_barcode(product.pk)
        product.save(update_fields=['barcode'])


def noop(apps, schema_editor):
    """No revierte nada: quitarle el barcode generado a un producto que ya
    lo tiene no aporta nada útil al bajar la migración."""


class Migration(migrations.Migration):

    dependencies = [
        ('billing', '0009_invoice_forma_pago_paypal'),
    ]

    operations = [
        migrations.RunPython(backfill_barcodes, noop),
    ]
