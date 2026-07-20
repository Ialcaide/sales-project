from django.test import TestCase
from django.core.exceptions import ValidationError
from django.db import transaction
from decimal import Decimal
from datetime import date
from dateutil.relativedelta import relativedelta
from .models import Empleado, TipoPrestamo, Prestamo, PrestamoDetalle

class PrestamoModelTests(TestCase):
    def setUp(self):
        # Empleado con antigüedad suficiente (ingreso en 2020)
        # Sueldo = 1200.00, porcentaje_credito = 300 (por defecto) -> limite_credito = 3600.00
        self.empleado = Empleado.objects.create(
            nombres="Juan Pérez", 
            sueldo=Decimal("1200.00"),
            fecha_ingreso=date(2020, 1, 1)
        )
        self.tipo_sencillo = TipoPrestamo.objects.create(
            descripcion="Sencillo", 
            tasa_interes=10, # 10%
            monto_maximo=Decimal("5000.00")
        )

    def test_calculo_valores_e_interes(self):
        """El interés y el total a pagar deben calcularse correctamente y el saldo inicial ser igual al total."""
        prestamo = Prestamo.objects.create(
            empleado=self.empleado,
            tipo_prestamo=self.tipo_sencillo,
            fecha_prestamo=date(2026, 1, 15),
            monto=Decimal("1000.00"),
            numero_cuotas=5
        )
        self.assertEqual(prestamo.interes, Decimal("100.00"))
        self.assertEqual(prestamo.monto_pagar, Decimal("1100.00"))
        self.assertEqual(prestamo.saldo, Decimal("1100.00"))

    def test_prorrateo_centavos_cuotas(self):
        """Las cuotas deben prorratearse correctamente, y la última debe absorber cualquier residuo de centavos."""
        tipo_sin_interes = TipoPrestamo.objects.create(
            descripcion="Sin Interés", 
            tasa_interes=0,
            monto_maximo=Decimal("5000.00")
        )
        prestamo = Prestamo.objects.create(
            empleado=self.empleado,
            tipo_prestamo=tipo_sin_interes,
            fecha_prestamo=date(2026, 1, 15),
            monto=Decimal("1000.00"),
            numero_cuotas=3
        )
        detalles = list(prestamo.detalles.all())
        self.assertEqual(len(detalles), 3)
        self.assertEqual(detalles[0].valor_cuota, Decimal("333.33"))
        self.assertEqual(detalles[1].valor_cuota, Decimal("333.33"))
        self.assertEqual(detalles[2].valor_cuota, Decimal("333.34"))

    def test_desplazamiento_inteligente_primera_cuota(self):
        """La primera cuota debe vencer al menos 15 días después de la fecha del préstamo."""
        prestamo = Prestamo.objects.create(
            empleado=self.empleado,
            tipo_prestamo=self.tipo_sencillo,
            fecha_prestamo=date(2026, 1, 31),
            monto=Decimal("500.00"),
            numero_cuotas=3
        )
        detalles = list(prestamo.detalles.all())
        self.assertEqual(detalles[0].fecha_vencimiento, date(2026, 2, 28))
        self.assertEqual(detalles[1].fecha_vencimiento, date(2026, 3, 31))

    def test_limite_monto_maximo_tipo_prestamo(self):
        """El monto solicitado no puede superar el monto_maximo de su TipoPrestamo."""
        self.tipo_sencillo.monto_maximo = Decimal("2000.00")
        self.tipo_sencillo.save()
        prestamo = Prestamo(
            empleado=self.empleado,
            tipo_prestamo=self.tipo_sencillo,
            fecha_prestamo=date(2026, 1, 15),
            monto=Decimal("2500.00"),
            numero_cuotas=12
        )
        with self.assertRaises(ValidationError) as context:
            prestamo.full_clean()
        self.assertIn('monto', context.exception.message_dict)

    def test_capacidad_endeudamiento_minimo_vital(self):
        """La cuota proyectada no puede superar el 30% del sueldo del empleado."""
        # Sueldo = 1200.00 -> 30% = 360.00
        # Préstamo de 1000 con 10% interes = 1100.00 en 2 cuotas -> Cuota = 550.00 (Excede 360.00)
        prestamo = Prestamo(
            empleado=self.empleado,
            tipo_prestamo=self.tipo_sencillo,
            fecha_prestamo=date(2026, 1, 15),
            monto=Decimal("1000.00"),
            numero_cuotas=2
        )
        with self.assertRaises(ValidationError) as context:
            prestamo.full_clean()
        self.assertIn('numero_cuotas', context.exception.message_dict)

    def test_prestamos_activos_concurrentes(self):
        """Un empleado puede tener múltiples préstamos activos siempre que no superen su cupo disponible."""
        # Límite: sueldo 1200 * 300% = 3600.00
        # Primer préstamo de 1000 con 10% interes -> total 1100. Saldo actual = 1100.
        Prestamo.objects.create(
            empleado=self.empleado,
            tipo_prestamo=self.tipo_sencillo,
            fecha_prestamo=date(2026, 1, 15),
            monto=Decimal("1000.00"),
            numero_cuotas=12
        )
        # Intentar crear un segundo de 500 -> total 550. Cupo disponible = 3600 - 1100 = 2500.
        # Debe permitirse ya que 500 <= 2500.
        segundo = Prestamo(
            empleado=self.empleado,
            tipo_prestamo=self.tipo_sencillo,
            fecha_prestamo=date(2026, 1, 15),
            monto=Decimal("500.00"),
            numero_cuotas=12
        )
        segundo.full_clean() # No debe levantar ValidationError
        
        # Intentar crear un tercero de 3000 -> excede el saldo restante
        tercero = Prestamo(
            empleado=self.empleado,
            tipo_prestamo=self.tipo_sencillo,
            fecha_prestamo=date(2026, 1, 15),
            monto=Decimal("3000.00"),
            numero_cuotas=12
        )
        with self.assertRaises(ValidationError) as context:
            tercero.full_clean()
        self.assertIn('monto', context.exception.message_dict)

    def test_antiguedad_laboral_minima(self):
        """El empleado debe tener al menos 6 meses de antigüedad."""
        nuevo_empleado = Empleado.objects.create(
            nombres="Carlos Fuentes",
            sueldo=Decimal("1500.00"),
            fecha_ingreso=date(2026, 1, 1)
        )
        # Préstamo en febrero (1 mes de antigüedad)
        prestamo = Prestamo(
            empleado=nuevo_empleado,
            tipo_prestamo=self.tipo_sencillo,
            fecha_prestamo=date(2026, 2, 1),
            monto=Decimal("100.00"),
            numero_cuotas=12
        )
        with self.assertRaises(ValidationError) as context:
            prestamo.full_clean()
        self.assertIn('empleado', context.exception.message_dict)

    def test_limite_fin_contrato(self):
        """Las cuotas no pueden superar los meses restantes de contrato del empleado."""
        temporal = Empleado.objects.create(
            nombres="Ana Silva",
            sueldo=Decimal("2000.00"),
            fecha_ingreso=date(2020, 1, 1),
            fecha_fin_contrato=date(2026, 6, 30)
        )
        # Préstamo el 2026-03-01 -> le restan 3 meses de contrato (marzo, abril, mayo).
        # Intentar 5 cuotas
        prestamo = Prestamo(
            empleado=temporal,
            tipo_prestamo=self.tipo_sencillo,
            fecha_prestamo=date(2026, 3, 1),
            monto=Decimal("100.00"),
            numero_cuotas=5
        )
        with self.assertRaises(ValidationError) as context:
            prestamo.full_clean()
        self.assertIn('numero_cuotas', context.exception.message_dict)

    def test_estado_terminal_inmutable(self):
        """Un préstamo en estado PAG o ANU no puede ser modificado."""
        prestamo = Prestamo.objects.create(
            empleado=self.empleado,
            tipo_prestamo=self.tipo_sencillo,
            fecha_prestamo=date(2026, 1, 15),
            monto=Decimal("100.00"),
            numero_cuotas=12
        )
        # Cambiamos a pagado
        prestamo.estado = 'PAG'
        prestamo.save()

        # Intentamos modificar cualquier cosa
        prestamo.monto = Decimal("200.00")
        with self.assertRaises(ValidationError):
            prestamo.save()

    def test_limite_credito_empleado(self):
        """El límite de crédito del empleado se calcula y se respeta correctamente."""
        self.empleado.sueldo = Decimal("1000.00")
        self.empleado.porcentaje_credito = 150 # 150% = 1500.00
        self.empleado.save()
        self.assertEqual(self.empleado.limite_credito, Decimal("1500.00"))
        
        prestamo = Prestamo(
            empleado=self.empleado,
            tipo_prestamo=self.tipo_sencillo,
            fecha_prestamo=date(2026, 1, 15),
            monto=Decimal("1600.00"),
            numero_cuotas=12
        )
        with self.assertRaises(ValidationError) as context:
            prestamo.full_clean()
        self.assertIn('monto', context.exception.message_dict)

    def test_capacidad_pago_absoluta(self):
        """La cuota mensual no puede superar el salario del empleado."""
        prestamo = Prestamo(
            empleado=self.empleado,
            tipo_prestamo=self.tipo_sencillo,
            fecha_prestamo=date(2026, 1, 15),
            monto=Decimal("3000.00"),
            numero_cuotas=2
        )
        with self.assertRaises(ValidationError) as context:
            prestamo.full_clean()
        self.assertIn('numero_cuotas', context.exception.message_dict)

