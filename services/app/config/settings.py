"""Django settings for the Wood League Chess application.

Title: settings.py — Django configuration for Wood League Chess
Description:
    Configures database, installed apps, middleware, templates, static files,
    authentication, and third-party service keys (Anthropic, Chess.com).

Changelog:
    2026-05-06: Auto-configure ALLOWED_HOSTS with Railway health check domain
                to fix DisallowedHost errors during health checks
"""
from pathlib import Path

from decouple import Csv, config

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = config("SECRET_KEY", default="django-insecure-change-me-in-production")
DEBUG = config("DEBUG", default=True, cast=bool)

# ALLOWED_HOSTS - Handle Railway health checks
_allowed_hosts = config("ALLOWED_HOSTS", default="localhost,127.0.0.1", cast=Csv())
ALLOWED_HOSTS = list(_allowed_hosts)

# Add Railway health check host if missing
if "healthcheck.railway.app" not in ALLOWED_HOSTS:
    ALLOWED_HOSTS.append("healthcheck.railway.app")

# CSRF protection for reverse proxy (Railway)
_csrf_origins = config("CSRF_TRUSTED_ORIGINS", default="")
CSRF_TRUSTED_ORIGINS = [origin for origin in _csrf_origins.split(",") if origin.strip()]

# Also add the domain to ALLOWED_HOSTS if it's in CSRF_TRUSTED_ORIGINS
for origin in CSRF_TRUSTED_ORIGINS:
    # Extract domain from origin URL (e.g., https://example.com -> example.com)
    domain = origin.replace("https://", "").replace("http://", "").rstrip("/")
    if domain not in ALLOWED_HOSTS:
        ALLOWED_HOSTS.append(domain)

AUTH_USER_MODEL = "accounts.User"

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django_tailwind_cli",
    "django_htmx",
    "accounts",
    "players",
    "games",
    "analysis",
    "openings",
    "dashboard",
    "search",
    "ingest",
    "rest_framework",
    "rest_framework_api_key",
    "api",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "django_htmx.middleware.HtmxMiddleware",
    "accounts.middleware.LoginRequiredMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

_database_url = config("DATABASE_URL", default="")
if _database_url:
    try:
        import dj_database_url
    except ImportError as exc:
        raise RuntimeError(
            "DATABASE_URL is set, but dj-database-url is not installed."
        ) from exc
    DATABASES = {"default": dj_database_url.parse(_database_url, conn_max_age=600)}
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": config("DB_NAME", default="wood_league"),
            "USER": config("DB_USER", default="postgres"),
            "PASSWORD": config("DB_PASSWORD", default=""),
            "HOST": config("DB_HOST", default="localhost"),
            "PORT": config("DB_PORT", default="5432"),
        }
    }

AUTHENTICATION_BACKENDS = [
    "accounts.backends.LegacyPbkdf2Backend",
    "django.contrib.auth.backends.ModelBackend",
]

PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
    "accounts.backends.LegacyPbkdf2Hasher",
]

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LOGIN_URL = "/auth/login/"
LOGIN_REDIRECT_URL = "/"
LOGOUT_REDIRECT_URL = "/auth/login/"

AUTH_ENABLED = config("AUTH_ENABLED", default=True, cast=bool)

REST_FRAMEWORK = {
    # No session auth on the API — key auth is permission-based
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'api.authentication.WorkerAPIKeyAuthentication',
    ],
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework_api_key.permissions.HasAPIKey',
    ],
    'DEFAULT_THROTTLE_CLASSES': [
        'rest_framework.throttling.ScopedRateThrottle',
    ],
    'DEFAULT_THROTTLE_RATES': {
        'checkout': '60/min',
        'complete': '120/min',
        'heartbeat': '600/min',
    },
    'DEFAULT_RENDERER_CLASSES': ['rest_framework.renderers.JSONRenderer'],
}

# Workers send: X-Api-Key: <key>
API_KEY_CUSTOM_HEADER = 'HTTP_X_API_KEY'

# Tunable fault-tolerance constants (override in .env)
import os
STALE_JOB_TIMEOUT_MINUTES = int(os.environ.get('STALE_JOB_TIMEOUT_MINUTES', 15))
MAX_JOB_RETRIES = int(os.environ.get('MAX_JOB_RETRIES', 3))

TAILWIND_CLI_SRC_CSS = "static/css/main.css"
TAILWIND_CLI_OUTPUT_CSS = "css/tailwind.css"
TAILWIND_CLI_AUTOMATIC_DOWNLOAD = True

ANTHROPIC_API_KEY = config("ANTHROPIC_API_KEY", default="")
ANTHROPIC_MODEL = config("ANTHROPIC_MODEL", default="claude-haiku-4-5-20251001")

CHESS_COM_USERNAMES = config("CHESS_COM_USERNAMES", default="")
CHESS_COM_USER_AGENT = config(
    "CHESS_COM_USER_AGENT", default="wood-league-chess/2.0 (+club analytics)"
)
INGEST_MONTH_LIMIT = config("INGEST_MONTH_LIMIT", default=24, cast=int)
DEFAULT_HISTORY_DAYS = config("DEFAULT_HISTORY_DAYS", default=90, cast=int)

# Engine analysis settings
ANALYSIS_DEPTH = config("ANALYSIS_DEPTH", default=20, cast=int)
LC0_NODES = config("LC0_NODES", default=25000, cast=int)
