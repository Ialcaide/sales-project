from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('billing', '0004_product_last_cost'),
    ]

    operations = [
        migrations.AddField(
            model_name='invoice',
            name='tipo_pago',
            field=models.CharField(
                choices=[('contado', 'Contado'), ('credito', 'Crédito')],
                default='contado', max_length=10, verbose_name='Tipo de pago',
            ),
        ),
        migrations.AddField(
            model_name='invoice',
            name='saldo',
            field=models.DecimalField(
                decimal_places=2, default=0, max_digits=12, verbose_name='Saldo pendiente',
            ),
        ),
        migrations.AddField(
            model_name='invoice',
            name='estado',
            field=models.CharField(
                choices=[('pendiente', 'Pendiente'), ('pagada', 'Pagada')],
                default='pagada', max_length=10, verbose_name='Estado',
            ),
        ),
    ]
