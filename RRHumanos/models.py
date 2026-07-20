from django.db import models
from decimal import Decimal, ROUND_HALF_UP
from datetime import date
from django.core.validators import MinValueValidator, MaxValueValidator
from django.core.exceptions import ValidationError
from django.contrib.auth.models import User
from dateutil.relativedelta import relativedelta

class TipoSobretiempo(models.Model):
    codigo = models.CharField(max_length=10)
    descripcion = models.CharField(max_length=100)
    factor = models.DecimalField(max_digits=4, decimal_places=2)

    def __str__(self):
        return self.descripcion


class Empleado(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, null=True, blank=True, related_name='empleado', verbose_name="Usuario Asociado")
    nombres = models.CharField(max_length=100)
    sueldo = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(Decimal('0.01'))]
    )
    fecha_ingreso = models.DateField(default=date(2020, 1, 1))
    fecha_fin_contrato = models.DateField(null=True, blank=True)
    porcentaje_credito = models.PositiveIntegerField(
        default=300,
        help_text="Porcentaje del salario asignado como límite de crédito. Ej. 300% equivale a 3 veces su sueldo."
    )
    limite_credito = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal('0.00'),
        editable=False,
        verbose_name="Límite de Crédito"
    )

    def __str__(self):
        return self.nombres

    def save(self, *args, **kwargs):
        # Calcular límite de crédito automáticamente
        self.limite_credito = (self.sueldo * Decimal(self.porcentaje_credito) / Decimal('100')).quantize(Decimal('0.01'))
        super().save(*args, **kwargs)


class Sobretiempo(models.Model):
    empleado = models.ForeignKey(Empleado, on_delete=models.CASCADE)
    fecha_registro = models.DateField()
    total_horas = models.PositiveIntegerField(default=240)
    sueldo_mensual = models.DecimalField(max_digits=10, decimal_places=2)
    total_calculado = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        editable=False,
        default=0
    )


class SobretiempoDetalle(models.Model):
    sobretiempo = models.ForeignKey(
        Sobretiempo,
        related_name="detalles",
        on_delete=models.CASCADE
    )
    tipo_sobretiempo = models.ForeignKey(
        TipoSobretiempo,
        on_delete=models.CASCADE
    )
    numero_horas = models.DecimalField(max_digits=6, decimal_places=2)
    valor_calculado = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        editable=False
    )


class TipoPrestamo(models.Model):
    descripcion = models.CharField(max_length=100)
    tasa_interes = models.PositiveIntegerField(default=0)
    monto_maximo = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('1000.00'))

    def __str__(self):
        return f"{self.descripcion} ({self.tasa_interes}%)"

    class Meta:
        verbose_name = "Tipo de Préstamo"
        verbose_name_plural = "Tipos de Préstamo"


class Prestamo(models.Model):
    ESTADOS = [
        ('PEND', 'Pendiente'),
        ('PAG', 'Pagado'),
        ('ANU', 'Anulado'),
    ]

    empleado = models.ForeignKey(Empleado, on_delete=models.CASCADE)
    tipo_prestamo = models.ForeignKey(TipoPrestamo, on_delete=models.CASCADE)
    fecha_prestamo = models.DateField()
    monto = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(Decimal('0.01'))])
    interes = models.DecimalField(max_digits=10, decimal_places=2, editable=False)
    monto_pagar = models.DecimalField(max_digits=10, decimal_places=2, editable=False)
    numero_cuotas = models.PositiveIntegerField(default=1, validators=[MinValueValidator(1), MaxValueValidator(60)])
    saldo = models.DecimalField(max_digits=10, decimal_places=2, editable=False)
    estado = models.CharField(max_length=4, choices=ESTADOS, default='PEND')

    def __str__(self):
        return f"Préstamo #{self.id or 'Nuevo'} - {self.empleado.nombres} (${self.monto})"

    def clean(self):
        super().clean()
        
        # Validar estado terminal
        if self.pk is not None:
            original = Prestamo.objects.get(pk=self.pk)
            if original.estado in ('PAG', 'ANU'):
                raise ValidationError('Este préstamo se encuentra en un estado terminal (Pagado o Anulado) y no puede ser modificado.')

        if self.monto is not None and self.monto <= 0:
            raise ValidationError({'monto': 'El monto solicitado debe ser mayor a 0.'})
        
        if self.numero_cuotas is not None:
            if self.numero_cuotas < 1:
                raise ValidationError({'numero_cuotas': 'El número de cuotas no puede ser menor a 1.'})
            if self.numero_cuotas > 60:
                raise ValidationError({'numero_cuotas': 'El número de cuotas no puede superar las 60 cuotas.'})

        # 1. Límite por Tipo de Préstamo
        if self.tipo_prestamo and self.monto is not None:
            if self.monto > self.tipo_prestamo.monto_maximo:
                raise ValidationError({
                    'monto': f'El monto solicitado (${self.monto:.2f}) supera el monto máximo permitido para este tipo de préstamo (${self.tipo_prestamo.monto_maximo:.2f}).'
                })

        # Límite por Crédito Disponible Real (Validación de Cupo)
        if self.empleado and self.monto is not None:
            deuda_qs = Prestamo.objects.filter(empleado=self.empleado, estado='PEND')
            if self.pk:
                deuda_qs = deuda_qs.exclude(pk=self.pk)
            deuda_actual = deuda_qs.aggregate(total=models.Sum('saldo'))['total'] or Decimal('0.00')
            credito_disponible = self.empleado.limite_credito - deuda_actual
            if self.monto > credito_disponible:
                raise ValidationError({
                    'monto': f'El monto solicitado (${self.monto:.2f}) supera el crédito disponible del empleado (${credito_disponible:.2f}). Límite de Crédito: ${self.empleado.limite_credito:.2f}, Deuda Actual: ${deuda_actual:.2f}.'
                })

        # Calcular totales para las siguientes validaciones
        if self.monto is not None and self.tipo_prestamo:
            tasa = Decimal(self.tipo_prestamo.tasa_interes)
            self.interes = (self.monto * (tasa / Decimal('100'))).quantize(Decimal('0.01'))
            self.monto_pagar = self.monto + self.interes
        else:
            self.interes = Decimal('0.00')
            self.monto_pagar = Decimal('0.00')

        # 2. Capacidad de Endeudamiento / Capacidad de Pago Absoluta
        if self.empleado and self.monto_pagar and self.numero_cuotas:
            cuota_proyectada = (self.monto_pagar / Decimal(self.numero_cuotas)).quantize(Decimal('0.01'))
            limite_cuota = (self.empleado.sueldo * Decimal('0.40')).quantize(Decimal('0.01'))
            if cuota_proyectada > self.empleado.sueldo:
                raise ValidationError({
                    'numero_cuotas': f'La cuota mensual estimada (${cuota_proyectada:.2f}) no puede superar el salario del empleado (${self.empleado.sueldo:.2f}).'
                })
            elif cuota_proyectada > limite_cuota:
                raise ValidationError({
                    'numero_cuotas': f'La cuota mensual estimada (${cuota_proyectada:.2f}) supera la capacidad de endeudamiento máxima del 40% del salario (${limite_cuota:.2f}).'
                })

        # 4. Antigüedad Laboral Mínima (6 meses)
        if self.empleado and self.fecha_prestamo:
            diferencia = relativedelta(self.fecha_prestamo, self.empleado.fecha_ingreso)
            total_meses = diferencia.years * 12 + diferencia.months
            if total_meses < 6:
                raise ValidationError({
                    'empleado': f'El empleado debe tener al menos 6 meses de antigüedad (actualmente tiene {total_meses} meses).'
                })

        # 5. Límite por Fin de Contrato
        if self.empleado and self.empleado.fecha_fin_contrato and self.fecha_prestamo and self.numero_cuotas:
            if self.fecha_prestamo > self.empleado.fecha_fin_contrato:
                raise ValidationError({
                    'fecha_prestamo': 'La fecha del préstamo no puede ser posterior a la fecha de fin de contrato.'
                })
            dif_contrato = relativedelta(self.empleado.fecha_fin_contrato, self.fecha_prestamo)
            meses_restantes = dif_contrato.years * 12 + dif_contrato.months
            if meses_restantes < self.numero_cuotas:
                raise ValidationError({
                    'numero_cuotas': f'El número de cuotas ({self.numero_cuotas}) supera los meses restantes de contrato del empleado ({meses_restantes} meses).'
                })

    def save(self, *args, **kwargs):
        # Asegurar validaciones del clean
        self.full_clean()

        is_new = self.pk is None
        tasa = Decimal(self.tipo_prestamo.tasa_interes)
        self.interes = (self.monto * (tasa / Decimal('100'))).quantize(Decimal('0.01'))
        self.monto_pagar = self.monto + self.interes

        if is_new:
            self.saldo = self.monto_pagar

        from django.db import transaction
        with transaction.atomic():
            super().save(*args, **kwargs)

            if is_new:
                # Determinar desplazamiento de primera cuota
                offset = 1
                primer_mes = self.fecha_prestamo + relativedelta(months=offset)
                if (primer_mes - self.fecha_prestamo).days < 15:
                    offset = 2

                # Generar detalles (cuotas)
                cuotas = []
                valor_cuota_normal = (self.monto_pagar / Decimal(self.numero_cuotas)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
                
                suma_cuotas_normales = valor_cuota_normal * (self.numero_cuotas - 1)
                valor_ultima_cuota = self.monto_pagar - suma_cuotas_normales

                for i in range(1, self.numero_cuotas + 1):
                    cuota_valor = valor_ultima_cuota if i == self.numero_cuotas else valor_cuota_normal
                    fecha_vencimiento = self.fecha_prestamo + relativedelta(months=offset + i - 1)
                    cuotas.append(
                        PrestamoDetalle(
                            prestamo=self,
                            numero_cuota=i,
                            fecha_vencimiento=fecha_vencimiento,
                            valor_cuota=cuota_valor,
                            saldo_cuota=cuota_valor
                        )
                    )
                PrestamoDetalle.objects.bulk_create(cuotas)


class PrestamoDetalle(models.Model):
    prestamo = models.ForeignKey(Prestamo, related_name="detalles", on_delete=models.CASCADE)
    numero_cuota = models.PositiveIntegerField()
    fecha_vencimiento = models.DateField()
    valor_cuota = models.DecimalField(max_digits=10, decimal_places=2)
    saldo_cuota = models.DecimalField(max_digits=10, decimal_places=2)

    def __str__(self):
        return f"Cuota #{self.numero_cuota} de Préstamo #{self.prestamo.id} (${self.valor_cuota})"

    class Meta:
        verbose_name = "Detalle de Préstamo"
        verbose_name_plural = "Detalles de Préstamo"
        ordering = ['numero_cuota']
