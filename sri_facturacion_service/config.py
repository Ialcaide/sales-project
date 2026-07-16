"""
Configuración de este servicio — reemplaza a config/settings.py de Django.

Usa Pydantic BaseSettings (pydantic-settings) para cargar y validar las
variables de entorno de forma segura, con tipado explícito y valores por
defecto declarados en un único lugar. El archivo .env local (no versionado)
es cargado automáticamente por BaseSettings (mismo criterio que ya usaba el
proyecto principal con Django, solo que ahí lo hacía la librería directamente
y acá lo hace Pydantic de forma estructurada).

Compatibilidad: los nombres exportados al final del módulo (SRI_CERTIFICADO_PATH,
SRI_CERTIFICADO_PASSWORD, etc.) son exactamente los mismos que antes, por lo
que ningún otro módulo del proyecto necesita ningún cambio.
"""
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent


class Settings(BaseSettings):
    """
    Variables de entorno del microservicio, validadas y tipadas con Pydantic.
    Todas se pueden sobreescribir con variables de entorno reales del sistema
    (útil en Docker/CI) — el .env solo aplica en desarrollo local.
    """

    model_config = SettingsConfigDict(
        # Carga el .env que vive junto a este archivo (no el del proyecto Django).
        env_file=BASE_DIR / '.env',
        # Si el .env no existe (ej. en CI con variables reales del sistema),
        # no falla — simplemente usa los defaults o las vars del entorno.
        env_file_encoding='utf-8',
        # Ignora variables de entorno extra que no estén declaradas acá.
        extra='ignore',
        # Case-insensitive: SRI_AMBIENTE y sri_ambiente son la misma variable.
        case_sensitive=False,
    )

    # --- Certificado de firma electrónica ---
    # SRI_CERTIFICADO_PATH: ruta relativa (desde BASE_DIR) o absoluta al .p12.
    # SRI_CERTIFICADO_PASSWORD: contraseña del .p12. Nunca se loguea.
    sri_certificado_path: str = Field(default='', alias='SRI_CERTIFICADO_PATH')
    sri_certificado_password: str = Field(default='', alias='SRI_CERTIFICADO_PASSWORD')

    # --- Ambiente del SRI ---
    # 'pruebas': WS de certificación (celcer.sri.gob.ec) — sin validez tributaria.
    # 'produccion': WS de producción (cel.sri.gob.ec) — facturas reales.
    sri_ambiente: Literal['pruebas', 'produccion'] = Field(
        default='pruebas', alias='SRI_AMBIENTE'
    )

    # --- API Key ---
    # Secreto compartido que los clientes deben mandar en X-API-Key.
    api_key: str = Field(default='', alias='API_KEY')

    # --- Base de datos ---
    # Por defecto SQLite local. Cambiar a Postgres solo requiere actualizar
    # esta variable en el .env, sin tocar nada del código (ver database.py).
    database_url: str = Field(
        default=f'sqlite:///{BASE_DIR / "db.sqlite3"}', alias='DATABASE_URL'
    )

    # --- Debug ---
    debug: bool = Field(default=False, alias='DEBUG')


# Instancia única del servicio — se carga una sola vez al importar este módulo.
settings = Settings()

# ---------------------------------------------------------------------------
# Exportaciones con los mismos nombres que usaba la versión anterior del módulo
# para que NINGÚN otro archivo del proyecto (client.py, services.py, firma.py,
# database.py, main.py) necesite ningún cambio.
# ---------------------------------------------------------------------------
SRI_CERTIFICADO_PATH: str = settings.sri_certificado_path
SRI_CERTIFICADO_PASSWORD: str = settings.sri_certificado_password
SRI_AMBIENTE: str = settings.sri_ambiente
API_KEY: str = settings.api_key
DATABASE_URL: str = settings.database_url
DEBUG: bool = settings.debug
