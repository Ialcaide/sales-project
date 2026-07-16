"""
Motor y sesión de base de datos — reemplaza lo que Django resolvía solo
(DATABASES + el ORM). SQLite alcanza para este servicio (solo guarda
comprobantes electrónicos y el contador de secuenciales); si hace falta
escalar, cambiar DATABASE_URL a Postgres es el mismo patrón de siempre.
"""
from sqlmodel import Session, SQLModel, create_engine

import config

_connect_args = {'check_same_thread': False} if config.DATABASE_URL.startswith('sqlite') else {}
engine = create_engine(config.DATABASE_URL, connect_args=_connect_args)


def init_db():
    """Crea las tablas si no existen — se llama una vez al arrancar la app
    (ver main.py). No hay un sistema de migraciones tipo Django acá a
    propósito: este servicio es chico y no tiene un historial de esquema
    que cuidar todavía; si en el futuro hace falta, Alembic es la pieza que
    se agregaría, sin cambiar nada de este archivo."""
    SQLModel.metadata.create_all(engine)


def get_session():
    """Dependency de FastAPI: una sesión por request, cerrada sola al
    terminar (ver Depends(get_session) en main.py)."""
    with Session(engine) as session:
        yield session
