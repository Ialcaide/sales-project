"""
Validación del payload que manda un proyecto cliente — con FastAPI esto ya
no hace falta escribirlo a mano (como en la versión Django, ver el
serializers.py de esa versión): Pydantic valida la forma, los tipos, y los
campos obligatorios solo con la anotación de cada clase.
"""
import datetime
from typing import List, Optional

from pydantic import BaseModel, Field, model_validator


class EmisorSchema(BaseModel):
    ruc: str
    razon_social: str
    nombre_comercial: str = ''
    direccion_matriz: str = ''
    obligado_contabilidad: bool = False
    establecimiento: str
    punto_emision: str


class CompradorSchema(BaseModel):
    es_consumidor_final: bool = False
    tipo_identificacion: Optional[str] = None
    identificacion: Optional[str] = None
    razon_social: Optional[str] = None
    direccion: str = ''
    email: str = ''
    telefono: str = ''

    @model_validator(mode='after')
    def _validar_datos_si_no_es_consumidor_final(self):
        if not self.es_consumidor_final:
            faltantes = [
                campo for campo in ('tipo_identificacion', 'identificacion', 'razon_social')
                if not getattr(self, campo)
            ]
            if faltantes:
                raise ValueError(f'Faltan datos del comprador: {", ".join(faltantes)}.')
        return self


class LineaSchema(BaseModel):
    codigo: str
    descripcion: str
    cantidad: str
    precio_unitario: str
    codigo_barras: str = ''


class FormaPagoSchema(BaseModel):
    codigo_sri: str
    es_credito: bool = False
    monto_a_pagar: Optional[str] = None
    plazo_dias: Optional[int] = None


class ComprobantePayload(BaseModel):
    """Cuerpo de POST /comprobantes/. `fecha_emision` como `date` ya valida
    el formato YYYY-MM-DD solo (Pydantic rechaza cualquier otra cosa)."""
    referencia_externa: str
    fecha_emision: datetime.date
    emisor: EmisorSchema
    comprador: CompradorSchema
    lineas: List[LineaSchema] = Field(min_length=1)
    iva_porcentaje: str
    subtotal: str
    iva_valor: str
    total: str
    forma_pago: FormaPagoSchema

    def to_stored_dict(self) -> dict:
        """Dict normalizado listo para guardar/procesar — agrega
        fecha_emision_ddmmyyyy, que xml_builder.py/ride.py necesitan (y
        fecha_emision queda como string ISO, no como date, para que el JSON
        guardado en ComprobanteElectronico.payload sea siempre serializable)."""
        data = self.model_dump(mode='json')
        data['fecha_emision_ddmmyyyy'] = self.fecha_emision.strftime('%d/%m/%Y')
        return data
