"""
Modelos de persistencia (SQLModel = tabla SQLAlchemy + validación Pydantic
en una sola clase) — mismos campos y mismo espíritu que los modelos Django
originales (sales_project/facturacion_electronica/models.py), portados a
SQLModel/SQLAlchemy en vez del ORM de Django.
"""
import datetime
from typing import ClassVar, Optional

from sqlalchemy import UniqueConstraint
from sqlmodel import JSON, Column, Field, Session, SQLModel, select


class SecuencialSRI(SQLModel, table=True):
    """
    Contador estrictamente incremental por (establecimiento, punto_emision,
    tipo_comprobante) — el que exige el SRI para numerar comprobantes
    (001-001-000000001, 002, 003...). Nunca se resetea ni se salta un
    número: si un envío falla después de reservarlo, ese número queda
    "quemado" (así lo exige el SRI, no se reutiliza).
    """
    __tablename__ = 'secuencial_sri'
    __table_args__ = (
        UniqueConstraint(
            'establecimiento', 'punto_emision', 'tipo_comprobante',
            name='unique_secuencial_sri_por_serie',
        ),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    establecimiento: str = Field(max_length=3)
    punto_emision: str = Field(max_length=3)
    tipo_comprobante: str = Field(default='01', max_length=2)
    ultimo_secuencial: int = Field(default=0)

    @classmethod
    def siguiente(cls, session: Session, establecimiento: str, punto_emision: str, tipo_comprobante: str = '01') -> int:
        """Reserva y devuelve el próximo número de la serie. La sesión hace
        de límite de transacción (se commitea acá mismo, en una sola
        operación corta) — con SQLite, que serializa escrituras a nivel de
        toda la base, esto alcanza para la misma seguridad de concurrencia
        que ya tenía la versión Django original (que tampoco lograba locking
        real por fila en SQLite, ver su propio comentario)."""
        statement = select(cls).where(
            cls.establecimiento == establecimiento,
            cls.punto_emision == punto_emision,
            cls.tipo_comprobante == tipo_comprobante,
        )
        contador = session.exec(statement).first()
        if contador is None:
            contador = cls(
                establecimiento=establecimiento, punto_emision=punto_emision,
                tipo_comprobante=tipo_comprobante, ultimo_secuencial=0,
            )
        contador.ultimo_secuencial += 1
        session.add(contador)
        session.commit()
        session.refresh(contador)
        return contador.ultimo_secuencial


class ComprobanteElectronico(SQLModel, table=True):
    """
    Estado de un comprobante electrónico ante el SRI. A diferencia del
    modelo Django original (que tenía un OneToOneField a billing.Invoice),
    acá NO se conoce ni se depende de ningún modelo de ningún proyecto
    cliente — `referencia_externa` es un string OPACO que cada proyecto
    cliente elige (ej. "billing.invoice:123"), y `payload` guarda el pedido
    original completo para poder reconstruir el RIDE o reintentar sin que
    el cliente tenga que volver a mandar todo cada vez.
    """
    __tablename__ = 'comprobante_electronico'

    GENERADO: ClassVar[str] = 'generado'
    FIRMADO: ClassVar[str] = 'firmado'
    ENVIADO: ClassVar[str] = 'enviado'
    RECIBIDA: ClassVar[str] = 'recibida'
    DEVUELTA: ClassVar[str] = 'devuelta'
    EN_PROCESO: ClassVar[str] = 'en_proceso'
    AUTORIZADO: ClassVar[str] = 'autorizado'
    NO_AUTORIZADO: ClassVar[str] = 'no_autorizado'
    ERROR: ClassVar[str] = 'error'

    AMBIENTE_PRUEBAS: ClassVar[str] = '1'
    AMBIENTE_PRODUCCION: ClassVar[str] = '2'

    id: Optional[int] = Field(default=None, primary_key=True)
    referencia_externa: str = Field(index=True, unique=True, max_length=200)
    payload: dict = Field(sa_column=Column(JSON))

    tipo_comprobante: str = Field(default='01', max_length=2)
    ambiente: str = Field(default=AMBIENTE_PRUEBAS, max_length=1)
    establecimiento: str = Field(max_length=3)
    punto_emision: str = Field(max_length=3)
    secuencial: str = Field(max_length=9)
    clave_acceso: str = Field(unique=True, max_length=49)
    estado: str = Field(default=GENERADO, max_length=15)

    xml_generado: str = Field(default='')
    xml_firmado: str = Field(default='')
    xml_autorizado: str = Field(default='')

    numero_autorizacion: str = Field(default='', max_length=49)
    fecha_autorizacion: Optional[datetime.datetime] = Field(default=None)
    mensajes: list = Field(default_factory=list, sa_column=Column(JSON))

    creado_en: datetime.datetime = Field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc))
    actualizado_en: datetime.datetime = Field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc))

    def ambiente_display(self) -> str:
        return 'Pruebas' if self.ambiente == self.AMBIENTE_PRUEBAS else 'Producción'

    def estado_display(self) -> str:
        labels = {
            self.GENERADO: 'XML generado', self.FIRMADO: 'XML firmado', self.ENVIADO: 'Enviado al SRI',
            self.RECIBIDA: 'Recibida por el SRI', self.DEVUELTA: 'Devuelta por el SRI',
            self.EN_PROCESO: 'En procesamiento', self.AUTORIZADO: 'Autorizado',
            self.NO_AUTORIZADO: 'No autorizado', self.ERROR: 'Error',
        }
        return labels.get(self.estado, self.estado)

    def to_dict(self) -> dict:
        """Forma en que este comprobante se serializa en TODAS las
        respuestas de la API — un solo lugar para no repetir la forma del
        JSON en cada ruta."""
        return {
            'referencia_externa': self.referencia_externa,
            'clave_acceso': self.clave_acceso,
            'tipo_comprobante': self.tipo_comprobante,
            'establecimiento': self.establecimiento,
            'punto_emision': self.punto_emision,
            'secuencial': self.secuencial,
            'estado': self.estado,
            'ambiente': self.ambiente,
            'numero_autorizacion': self.numero_autorizacion,
            'fecha_autorizacion': self.fecha_autorizacion.isoformat() if self.fecha_autorizacion else None,
            'mensajes': self.mensajes,
            'xml_generado': self.xml_generado,
            'xml_firmado': self.xml_firmado,
            'xml_autorizado': self.xml_autorizado,
        }
