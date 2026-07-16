"""
Configuración de este servicio — reemplaza a config/settings.py de Django.
python-dotenv carga el .env local (no versionado) sin pisar variables de
entorno reales del sistema/servidor, mismo criterio que ya usaba el
proyecto principal (sales_project/config/settings.py), solo que ahí lo hacía
Django "a mano" y acá lo hace la librería estándar del ecosistema FastAPI.
"""
import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / '.env')

# SRI_CERTIFICADO_PATH/PASSWORD: certificado de firma electrónica (.p12) —
# vive SOLO acá; ningún proyecto cliente vuelve a necesitarlo.
SRI_CERTIFICADO_PATH = os.environ.get('SRI_CERTIFICADO_PATH', '')
SRI_CERTIFICADO_PASSWORD = os.environ.get('SRI_CERTIFICADO_PASSWORD', '')
SRI_AMBIENTE = os.environ.get('SRI_AMBIENTE', 'pruebas')  # 'pruebas' o 'produccion'

# API_KEY: secreto compartido que cualquier proyecto cliente debe mandar en
# el header X-API-Key para poder usar este servicio.
API_KEY = os.environ.get('API_KEY', '')

DATABASE_URL = os.environ.get('DATABASE_URL', f'sqlite:///{BASE_DIR / "db.sqlite3"}')

DEBUG = os.environ.get('DEBUG', 'False') == 'True'
