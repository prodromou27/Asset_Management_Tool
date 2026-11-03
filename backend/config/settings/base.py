"""Base Django settings shared by all environments."""

from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent.parent

env = environ.Env(
    ITAM_ENV=(str, "development"),
    ITAM_DEBUG=(bool, False),
    ITAM_ALLOWED_HOSTS=(list, ["localhost", "127.0.0.1"]),
    ITAM_TIMEZONE=(str, "Asia/Nicosia"),
    ITAM_LOG_LEVEL=(str, "INFO"),
    DJANGO_SECRET_KEY=(str, ""),
    POSTGRES_DB=(str, "itam"),
    POSTGRES_USER=(str, "itam"),
    POSTGRES_PASSWORD=(str, ""),
    POSTGRES_HOST=(str, "postgres"),
    POSTGRES_PORT=(int, 5432),
    REDIS_URL=(str, "redis://redis:6379/0"),
    CORS_ALLOWED_ORIGINS=(list, []),
    CSRF_TRUSTED_ORIGINS=(list, []),
    ITAM_TRUSTED_PROXY_COUNT=(int, 0),
    ITAM_SECRETS_DIR=(str, "/run/secrets"),
    ITAM_ALLOW_LIVE_INTEGRATIONS=(bool, False),
)

env_file = BASE_DIR / ".env"
if env_file.exists():
    environ.Env.read_env(str(env_file))

ITAM_ENV = env("ITAM_ENV")
DEBUG = env("ITAM_DEBUG")
SECRET_KEY = env("DJANGO_SECRET_KEY")
ALLOWED_HOSTS = env("ITAM_ALLOWED_HOSTS")

INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.staticfiles",
    "rest_framework",
    "corsheaders",
    "drf_spectacular",
    "apps.health",
    "apps.audit",
    "apps.accounts",
    "apps.organizations",
    "apps.assets",
    "apps.integrations",
    "apps.observations",
    "apps.reconciliation",
    "apps.network",
]

AUTH_USER_MODEL = "accounts.User"

MIDDLEWARE = [
    "config.request_context.RequestIdMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "apps.accounts.middleware.SessionTimeoutMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
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
ASGI_APPLICATION = "config.asgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": env("POSTGRES_DB"),
        "USER": env("POSTGRES_USER"),
        "PASSWORD": env("POSTGRES_PASSWORD"),
        "HOST": env("POSTGRES_HOST"),
        "PORT": env("POSTGRES_PORT"),
    }
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "apps.accounts.validators.ConfiguredMinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.Argon2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
]

# Session cookie lifetime is the upper bound; SecuritySettings enforces the
# admin-configured idle/absolute timeouts per request.
SESSION_COOKIE_AGE = 72 * 3600
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_NAME = "itam_session"
CSRF_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_HTTPONLY = False  # SPA reads it to send X-CSRFToken
CSRF_COOKIE_NAME = "itam_csrftoken"

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": env("REDIS_URL"),
        "KEY_PREFIX": "itam",
    }
}

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "config.authentication.SessionAuthentication401",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "apps.accounts.permissions.IsAuthenticatedWithCurrentPassword",
    ],
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "DEFAULT_PAGINATION_CLASS": "config.api.ItemsCursorPagination",
    "EXCEPTION_HANDLER": "config.api.api_exception_handler",
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_THROTTLE_RATES": {
        "login": "10/min",
        "password_change": "5/min",
    },
    "UNAUTHENTICATED_USER": "django.contrib.auth.models.AnonymousUser",
    # Number of trusted reverse proxies appending to X-Forwarded-For. 0 = ignore the
    # header (it is client-controlled); production behind nginx-proxy sets 1.
    "NUM_PROXIES": env("ITAM_TRUSTED_PROXY_COUNT"),
}

SPECTACULAR_SETTINGS = {
    "TITLE": "ITAM API",
    "DESCRIPTION": "Custom IT Asset Management and EOL/EOS platform API.",
    "VERSION": "v1",
    "SERVE_INCLUDE_SCHEMA": False,
    "SCHEMA_PATH_PREFIX": "/api/v1",
    "COMPONENT_SPLIT_REQUEST": True,
    "ENUM_NAME_OVERRIDES": {
        "AuditSourceEnum": "apps.audit.models.AuditEvent.Source",
        "EvidenceSourceEnum": "apps.assets.models.Source",
        "LocationKindEnum": "apps.organizations.models.Location.Kind",
        "AuthProviderKindEnum": ["local", "oidc"],
        "SyncRunStatusEnum": "apps.integrations.models.SyncRun.Status",
    },
}

CORS_ALLOWED_ORIGINS = env("CORS_ALLOWED_ORIGINS")
CSRF_TRUSTED_ORIGINS = env("CSRF_TRUSTED_ORIGINS")

CELERY_BROKER_URL = env("REDIS_URL")
CELERY_RESULT_BACKEND = env("REDIS_URL")
CELERY_TASK_ALWAYS_EAGER = False
CELERY_TIMEZONE = "UTC"
CELERY_BEAT_SCHEDULE = {
    "refresh-source-freshness": {
        "task": "reconciliation.refresh_source_freshness",
        "schedule": 3600.0,
    },
    "dispatch-due-syncs": {
        "task": "integrations.dispatch_due_syncs",
        "schedule": 300.0,
    },
}

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": env("ITAM_LOG_LEVEL")},
    # httpx logs every request URL at INFO; connector summaries are logged by the app.
    "loggers": {"httpx": {"level": "WARNING"}, "httpcore": {"level": "WARNING"}},
}

DISPLAY_TIMEZONE = env("ITAM_TIMEZONE")

# Integration credentials are injected as files or ITAM_INTEGRATION_* variables.
ITAM_SECRETS_DIR = env("ITAM_SECRETS_DIR")
# Deployment-level kill switch: no connector contacts a live source unless true,
# in addition to the per-instance approval recorded by an administrator.
ITAM_ALLOW_LIVE_INTEGRATIONS = env("ITAM_ALLOW_LIVE_INTEGRATIONS")
