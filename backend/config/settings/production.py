from django.core.exceptions import ImproperlyConfigured

from .base import *  # noqa: F403
from .base import ALLOWED_HOSTS, ITAM_ENV, SECRET_KEY, env

if env("ITAM_DEBUG"):
    raise ImproperlyConfigured("ITAM_DEBUG must not be enabled in production")
if not SECRET_KEY or len(SECRET_KEY) < 50:
    raise ImproperlyConfigured("DJANGO_SECRET_KEY must be set to at least 50 characters")
if SECRET_KEY.startswith(("test-", "ci-", "django-insecure")):
    raise ImproperlyConfigured("Refusing to start production with a test/default secret key")
if not ALLOWED_HOSTS or "*" in ALLOWED_HOSTS:
    raise ImproperlyConfigured("ITAM_ALLOWED_HOSTS must list explicit hostnames in production")
if not env("POSTGRES_PASSWORD"):
    raise ImproperlyConfigured("POSTGRES_PASSWORD is required in production")

# "https" (default) or "http". Plain HTTP exists only for a first internal install before
# a certificate is available (scripts/install.sh); scripts/enable_https.sh switches over.
PUBLIC_SCHEME = env.str("ITAM_PUBLIC_SCHEME", default="https").strip().lower()
if PUBLIC_SCHEME not in ("http", "https"):
    raise ImproperlyConfigured("ITAM_PUBLIC_SCHEME must be 'http' or 'https'")
if PUBLIC_SCHEME == "http" and ITAM_ENV == "production":
    raise ImproperlyConfigured("ITAM_ENV=production requires ITAM_PUBLIC_SCHEME=https")
TLS = PUBLIC_SCHEME == "https"

DEBUG = False

SESSION_COOKIE_SECURE = TLS
CSRF_COOKIE_SECURE = TLS
SECURE_SSL_REDIRECT = TLS
SECURE_HSTS_SECONDS = 31536000 if TLS else 0
SECURE_HSTS_INCLUDE_SUBDOMAINS = TLS
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_CONTENT_TYPE_NOSNIFF = True
# Internal-only FQDN: HSTS preload-list submission does not apply.
SILENCED_SYSTEM_CHECKS = ["security.W021"]
if not TLS:
    # Deliberate plain-HTTP install: HSTS, HTTPS redirect and secure cookies are off.
    SILENCED_SYSTEM_CHECKS += ["security.W004", "security.W008", "security.W012", "security.W016"]
X_FRAME_OPTIONS = "DENY"
