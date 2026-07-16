from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('billing', '0016_customer_tipo_identificacion_alter_customer_dni'),
    ]

    operations = [
        migrations.RenameField(
            model_name='invoice',
            old_name='tarjeta_ultimos_digitos',
            new_name='tarjeta_cvv',
        ),
        migrations.AlterField(
            model_name='invoice',
            name='tarjeta_cvv',
            field=models.CharField(blank=True, max_length=4, null=True, verbose_name='CVV/CVC'),
        ),
    ]
