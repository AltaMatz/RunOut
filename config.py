"""
Configurazione centralizzata dell'applicazione.
Carica le variabili d'ambiente e le espone come costanti.
"""

import os
from dotenv import load_dotenv

load_dotenv()

# ============================================================
# MODALITÀ APPLICAZIONE
# ============================================================
APP_ENV = os.getenv('APP_ENV', 'development').lower()  # 'development' or 'production'
DEBUG = APP_ENV == 'development'

# ============================================================
# FLASK CORE
# ============================================================
FLASK_SECRET_KEY = os.getenv('FLASK_SECRET_KEY', 'dev-only-change-me-this-must-be-long-and-random')
SESSION_LIFETIME_SECONDS = int(os.getenv('SESSION_LIFETIME_SECONDS', '28800'))  # 8 ore

# ============================================================
# SSO CONFIGURATION
# ============================================================
SSO_MODE = os.getenv('SSO_MODE', 'dev').lower()  # 'dev' or 'production'
DEV_USER_EMAIL = os.getenv('DEV_USER_EMAIL', 'vivo.ciro.studente@itispaleocapa.it')
DEV_DOCENTE_EMAIL = os.getenv('DEV_DOCENTE_EMAIL', 'luca.todaro@itispaleocapa.it')

# JWT Configuration (valori deve venire dal portale SSO)
SSO_JWT_SECRET = os.getenv('SSO_JWT_SECRET', 'test-secret-change-in-production')
SSO_JWT_ISSUER = os.getenv('SSO_JWT_ISSUER', 'sso-portal')
SSO_JWT_AUDIENCE = os.getenv('SSO_JWT_AUDIENCE', 'mia-app')
SSO_PORTAL_URL = os.getenv('SSO_PORTAL_URL', 'http://localhost:5000')

# ============================================================
# RATE LIMITING
# ============================================================
MAX_SESSIONS_PER_USER = int(os.getenv('MAX_SESSIONS_PER_USER', '3'))
MAX_SESSIONS_GLOBAL = int(os.getenv('MAX_SESSIONS_GLOBAL', '100'))

# ============================================================
# WHITELIST
# ============================================================
WHITELIST_FILE = 'data/whitelist.json'
WHITELIST_STUDENTI_FILE = 'data/whitelist_studenti.json'

# ============================================================
# API CONFIGURATION
# ============================================================
API_TOKEN = os.getenv('API_TOKEN')  # Token per API esterne

# ============================================================
# APPLICATION PORT
# ============================================================
PORT = int(os.getenv('PORT', '3020'))

# ============================================================
# SSO CONFIG DICT (per retrocompatibilità)
# ============================================================
SSO_CONFIG = {
    'portal_url': SSO_PORTAL_URL,
    'jwt_secret': SSO_JWT_SECRET,
    'jwt_issuer': SSO_JWT_ISSUER,
    'jwt_audience': SSO_JWT_AUDIENCE,
}
