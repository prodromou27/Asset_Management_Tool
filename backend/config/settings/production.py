from django.core.exceptions import ImproperlyConfigured

from .base import *  # noqa: F403
from .base import ALLOWED_HOSTS, SECRET_KEY, env

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

DEBUG = False

SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_SSL_REDIRECT = True
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_CONTENT_TYPE_NOSNIFF = True
# Internal-only FQDN: HSTS preload-list submission does not apply.
SILENCED_SYSTEM_CHECKS = ["security.W021"]
X_FRAME_OPTIONS = "DENY"
