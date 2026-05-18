"""Django settings for the Wood League Chess application.

Title: settings.py — Django configuration for Wood League Chess
Description:
    Configures database, installed apps, middleware, templates, static files,
    authentication, and third-party service keys (Anthropic, Chess.com).

Changelog:
    2026-05-06: Auto-configure ALLOWED_HOSTS with Railway health check domain
                to fix DisallowedHost errors during health checks
"""
import os
from pathlib import Path

from decouple import Csv, config

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = config("SECRET_KEY")
DEBUG = config("DEBUG", default=False, cast=bool)

# ALLOWED_HOSTS - Handle Railway health checks
_allowed_hosts = config("ALLOWED_HOSTS", default="localhost,127.0.0.1", cast=Csv())
ALLOWED_HOSTS = list(_allowed_hosts)

# Add Railway health check host if missing
if "healthcheck.railway.app" not in ALLOWED_HOSTS:
    ALLOWED_HOSTS.append("healthcheck.railway.app")

# Django's test client uses 'testserver' as the default Host header.
# Real HTTP requests never set this value, so it's safe in all environments.
if "testserver" not in ALLOWED_HOSTS:
    ALLOWED_HOSTS.append("testserver")

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
    "core",
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

# Worker log upload (issue #52). When ``WORKER_LOG_BUCKET`` is empty the
# upload endpoint is effectively disabled and returns 503; tests stub the
# bucket interactions out, so the values can be safely blank in dev/test.
WORKER_LOG_BUCKET = os.environ.get('RAILWAY_BUCKET_NAME', '')
WORKER_LOG_S3_ENDPOINT = os.environ.get('ENDPOINT', '')
WORKER_LOG_S3_REGION = os.environ.get('REGION', 'us-east-1')
WORKER_LOG_S3_ACCESS_KEY = os.environ.get('ACCESS_KEY_ID', '')
WORKER_LOG_S3_SECRET_KEY = os.environ.get('SECRET_ACCESS_KEY', '')
WORKER_LOG_PRESIGN_TTL_SECONDS = int(
    os.environ.get('WORKER_LOG_PRESIGN_TTL_SECONDS', '900')
)
WORKER_LOG_MAX_BYTES = int(os.environ.get('WORKER_LOG_MAX_BYTES', str(100 * 1024 * 1024)))
WORKER_LOG_RETENTION_DAYS = int(os.environ.get('WORKER_LOG_RETENTION_DAYS', '30'))
WORKER_LOG_RATE_LIMIT_SECONDS = int(os.environ.get('WORKER_LOG_RATE_LIMIT_SECONDS', '60'))

# Tunable fault-tolerance constants (override in .env)
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
LC0_NETWORK = os.environ.get("LC0_NETWORK", "")

# RunPod serverless dispatch settings
RUNPOD_API_KEY = os.environ.get("RUNPOD_API_KEY", "")
RUNPOD_STOCKFISH_ENDPOINT_ID = (
    os.environ.get("RUNPOD_STOCKFISH_ENDPOINT_ID", "")
    or os.environ.get("RUNPOD_ENDPOINT_ID", "")
)
RUNPOD_LC0_ENDPOINT_ID = os.environ.get("RUNPOD_LC0_ENDPOINT_ID", "")

# RunPod admin start-pod endpoint (issue #83). RUNPOD_WORKER_POD_ID is the
# specific pod id that the admin "Start worker pod" button targets via
# POST https://rest.runpod.io/v1/pods/{pod_id}/start. RUNPOD_ENABLED gates
# both the URL route and the dashboard surfacing — when False the endpoint
# returns 404 and the UI section is hidden.
RUNPOD_WORKER_POD_ID = os.environ.get("RUNPOD_WORKER_POD_ID", "")
RUNPOD_ENABLED = os.environ.get("RUNPOD_ENABLED", "").lower() in {"1", "true", "yes", "on"}

# vast.ai cron-provisioning (issue #155 Sub-project A). VAST_ENABLED gates
# the reconcile command exactly like RUNPOD_ENABLED gates the start-pod
# endpoint: when off, the command no-ops. VAST_API_KEY never leaves the
# app (never placed on a rented box).
VAST_ENABLED = os.environ.get("VAST_ENABLED", "").lower() in {"1", "true", "yes", "on"}
VAST_API_KEY = os.environ.get("VAST_API_KEY", "")
VAST_TEMPLATE_HASH = os.environ.get("VAST_TEMPLATE_HASH", "")
VAST_CAMPAIGN_ID = os.environ.get("VAST_CAMPAIGN_ID", "")
VAST_OFFER_GPU_NAME = os.environ.get("VAST_OFFER_GPU_NAME", "L40S")
VAST_OFFER_MAX_DPH = float(os.environ.get("VAST_OFFER_MAX_DPH", "1.50"))
VAST_MAX_JOBS = int(os.environ.get("VAST_MAX_JOBS", "100"))
VAST_HARD_DEADLINE_HOURS = float(os.environ.get("VAST_HARD_DEADLINE_HOURS", "6.0"))
VAST_WORKER_STALE_MINUTES = int(os.environ.get("VAST_WORKER_STALE_MINUTES", "15"))

ANALYSIS_THREADS = int(os.environ.get("ANALYSIS_THREADS", "8"))
ANALYSIS_HASH_MB = int(os.environ.get("ANALYSIS_HASH_MB", "2048"))

ADMINS = [("Chris", config("DJANGO_ADMIN_EMAIL", default=""))]

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {
        "console": {"class": "logging.StreamHandler"},
        "mail_admins": {"class": "django.utils.log.AdminEmailHandler"},
    },
    "root": {"handlers": ["console"], "level": "WARNING"},
    "loggers": {
        "django": {
            "handlers": ["console", "mail_admins"],
            "level": "ERROR",
            "propagate": False,
        },
    },
}

if not DEBUG:
    CSRF_COOKIE_SECURE = True
    SESSION_COOKIE_SECURE = True
    SECURE_SSL_REDIRECT = True
    # Trust Railway's edge proxy SSL termination. Without this, Django sees
    # the inbound HTTP from the proxy and SECURE_SSL_REDIRECT kicks in,
    # creating an infinite redirect loop with the edge.
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    # Exempt the Railway deploy healthcheck from HTTPS redirect — Railway
    # checks via internal HTTP and a 302 fails the deploy.
    SECURE_REDIRECT_EXEMPT = [r"^healthz/$"]
    SECURE_HSTS_SECONDS = 31536000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
