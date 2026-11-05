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
    ITAM_IMPORT_ENCRYPTION_KEY=(str, ""),
    ITAM_IMPORT_RETENTION_DAYS=(int, 90),
    ITAM_EXPORT_RETENTION_HOURS=(int, 24),
    ITAM_EXPORT_MAX_ROWS=(int, 100_000),
    ITAM_LIFECYCLE_WARNING_DAYS=(list, [180, 90]),
    ITAM_LIFECYCLE_COUNT_EXTENDED_SUPPORT=(bool, False),
    ITAM_LIFECYCLE_MAX_EXCEPTION_DAYS=(int, 365),
    ITAM_CERT_WARNING_DAYS=(list, [90, 60, 30, 14, 7]),
    ITAM_TLS_CHECK_INTERVAL_HOURS=(int, 24),
    ITAM_TLS_CHECK_TIMEOUT_SECONDS=(int, 5),
    ITAM_NOTIFICATION_EXPIRY_HOURS=(int, 72),
    SMTP_HOST=(str, ""),
    SMTP_PORT=(int, 587),
    SMTP_SECURITY=(str, "starttls"),
    SMTP_FROM=(str, ""),
    ITAM_NOTIFICATION_BODY_RETENTION_DAYS=(int, 14),
    ITAM_BACKUP_ALLOW_RUN=(bool, False),
    ITAM_BACKUP_TARGET_LABEL=(str, "Not configured"),
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
    "apps.security",
    "apps.licensing",
    "apps.quality",
    "apps.groups",
    "apps.imports",
    "apps.exports",
    "apps.lifecycle",
    "apps.software",
    "apps.domains",
    "apps.notifications",
    "apps.backups",
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
        "CategoryReviewKindEnum": "apps.reconciliation.models.CategoryReview.Kind",
        "FindingKindEnum": "apps.quality.models.DataQualityFinding.Kind",
        "AssetGroupKindEnum": "apps.groups.models.AssetGroup.Kind",
        "RuleFieldKindEnum": ["text", "enum", "ref", "date"],
        "ImportJobStatusEnum": "apps.imports.models.ImportJob.Status",
        "ImportModeEnum": "apps.imports.models.ImportJob.Mode",
        "ExportJobStatusEnum": "apps.exports.models.ExportJob.Status",
        "ExportFormatEnum": "apps.exports.models.ExportJob.Format",
        "ExportScopeEnum": "apps.exports.models.ExportJob.Scope",
        "LifecycleStatusEnum": "apps.lifecycle.models.Status",
        "LifecycleDimensionEnum": "apps.lifecycle.models.Dimension",
        "MilestoneTypeEnum": "apps.lifecycle.models.MilestoneType",
        "LifecycleProductKindEnum": "apps.lifecycle.models.LifecycleProduct.Kind",
        "SupportStatementEnum": "apps.lifecycle.models.LifecycleProduct.SupportStatement",
        "LifecycleAliasKindEnum": "apps.lifecycle.models.LifecycleAlias.Kind",
        "LifecycleSourceTypeEnum": "apps.lifecycle.models.LifecycleSource.SourceType",
        "MilestoneVerificationEnum": "apps.lifecycle.models.LifecycleMilestone.Verification",
        "CertificateSourceEnum": "apps.domains.models.Certificate.Source",
        "TlsCheckStatusEnum": "apps.domains.models.TlsEndpoint.CheckStatus",
        "SmtpSecurityEnum": "apps.notifications.models.SmtpProfile.Security",
        "OutboxStatusEnum": "apps.notifications.models.OutboxMessage.Status",
        "LifecycleMatchStateEnum": "apps.lifecycle.models.AssetLifecycleMatch.State",
        "LifecycleMatchMethodEnum": "apps.lifecycle.models.AssetLifecycleMatch.Method",
        "SupportLevelEnum": "apps.lifecycle.models.LifecycleAssessment.SupportLevel",
        "EvidenceQualityEnum": "apps.lifecycle.models.LifecycleAssessment.EvidenceQuality",
        "SyncRunModeEnum": "apps.integrations.models.SyncRun.Mode",
    },
}

CORS_ALLOWED_ORIGINS = env("CORS_ALLOWED_ORIGINS")
CSRF_TRUSTED_ORIGINS = env("CSRF_TRUSTED_ORIGINS")

CELERY_BROKER_URL = env("REDIS_URL")
CELERY_RESULT_BACKEND = env("REDIS_URL")
CELERY_TASK_ALWAYS_EAGER = False
CELERY_TIMEZONE = "UTC"
CELERY_BEAT_SCHEDULE = {
    "dispatch-backups": {"task": "backups.dispatch", "schedule": 300.0},
    "refresh-source-freshness": {
        "task": "reconciliation.refresh_source_freshness",
        "schedule": 3600.0,
    },
    "dispatch-due-syncs": {
        "task": "integrations.dispatch_due_syncs",
        "schedule": 300.0,
    },
    "refresh-quality-findings": {
        "task": "quality.refresh_findings",
        "schedule": 3600.0,
    },
    "evaluate-dynamic-groups": {
        "task": "groups.evaluate_all",
        "schedule": 3600.0,
    },
    "purge-import-originals": {
        "task": "imports.purge_originals",
        "schedule": 86400.0,
    },
    "purge-exports": {
        "task": "exports.purge",
        "schedule": 3600.0,
    },
    "reassess-lifecycle": {
        "task": "lifecycle.reassess_all",
        "schedule": 3600.0,
    },
    "deliver-mail": {
        "task": "notifications.deliver_due",
        "schedule": 60.0,
    },
    "evaluate-notification-rules": {
        "task": "notifications.evaluate_rules",
        "schedule": 3600.0,
    },
    "purge-mail-bodies": {
        "task": "notifications.purge",
        "schedule": 86400.0,
    },
    "check-tls-endpoints": {
        "task": "domains.check_endpoints",
        "schedule": 900.0,  # picks endpoints whose last check is older than the interval
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
# Imports (Task 013): Fernet key for retained originals (derived from SECRET_KEY if empty)
# and how long originals are kept.
ITAM_IMPORT_ENCRYPTION_KEY = env("ITAM_IMPORT_ENCRYPTION_KEY")
ITAM_IMPORT_RETENTION_DAYS = env("ITAM_IMPORT_RETENTION_DAYS")
# Exports (Task 014): hours a finished export can be downloaded, and the record limit.
ITAM_EXPORT_RETENTION_HOURS = env("ITAM_EXPORT_RETENTION_HOURS")
ITAM_EXPORT_MAX_ROWS = env("ITAM_EXPORT_MAX_ROWS")
# Lifecycle (Task 015): warning thresholds in days before a support milestone, whether
# vendor extended support counts as supported (it usually needs a separate agreement), and
# the longest allowed exception.
ITAM_LIFECYCLE_WARNING_DAYS = [int(d) for d in env("ITAM_LIFECYCLE_WARNING_DAYS")]
ITAM_LIFECYCLE_COUNT_EXTENDED_SUPPORT = env("ITAM_LIFECYCLE_COUNT_EXTENDED_SUPPORT")
ITAM_LIFECYCLE_MAX_EXCEPTION_DAYS = env("ITAM_LIFECYCLE_MAX_EXCEPTION_DAYS")

# Domains and TLS certificates (Task 017, docs/10 thresholds).
ITAM_CERT_WARNING_DAYS = [int(d) for d in env("ITAM_CERT_WARNING_DAYS")]
ITAM_TLS_CHECK_INTERVAL_HOURS = env("ITAM_TLS_CHECK_INTERVAL_HOURS")
ITAM_TLS_CHECK_TIMEOUT_SECONDS = env("ITAM_TLS_CHECK_TIMEOUT_SECONDS")
# Loopback targets are refused outside tests (SSRF, docs/14).
ITAM_TLS_ALLOW_LOOPBACK = False

# Mail outbox (Task 018a): queued messages expire when mail stays disabled or unreachable;
# bodies of finished messages are cleared after the retention period.
ITAM_NOTIFICATION_EXPIRY_HOURS = env("ITAM_NOTIFICATION_EXPIRY_HOURS")
ITAM_NOTIFICATION_BODY_RETENTION_DAYS = env("ITAM_NOTIFICATION_BODY_RETENTION_DAYS")
# Initial values for the SMTP profile when it is first created (docs/12 "Email" row). The
# profile itself is edited in Administration and starts disabled.
ITAM_SMTP_DEFAULTS = {
    "host": env("SMTP_HOST"),
    "port": env("SMTP_PORT"),
    "security": env("SMTP_SECURITY"),
    "from_address": env("SMTP_FROM"),
}
# Deployment-level kill switch: no connector contacts a live source unless true,
# in addition to the per-instance approval recorded by an administrator.
ITAM_ALLOW_LIVE_INTEGRATIONS = env("ITAM_ALLOW_LIVE_INTEGRATIONS")
ITAM_BACKUP_ALLOW_RUN = env("ITAM_BACKUP_ALLOW_RUN")
ITAM_BACKUP_TARGET_LABEL = env("ITAM_BACKUP_TARGET_LABEL")
CELERY_TASK_ROUTES = {"backups.execute": {"queue": "backups"}}
