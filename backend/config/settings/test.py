import os

from django.core.exceptions import ImproperlyConfigured

from .base import *  # noqa: F403

DEBUG = False
SECRET_KEY = SECRET_KEY or "test-only-secret-key-not-for-production"  # noqa: F405
CELERY_TASK_ALWAYS_EAGER = True  # noqa: F405
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

# Local sandboxes without Docker/PostgreSQL can opt into SQLite purely to run
# this test suite. CI and all real environments use PostgreSQL (see base.py);
# ITAM_TEST_DB_SQLITE is never set outside of that fallback.
if os.environ.get("ITAM_TEST_DB_SQLITE") == "1":
    if os.environ.get("CI"):
        raise ImproperlyConfigured("ITAM_TEST_DB_SQLITE is not allowed in CI; use PostgreSQL")
    DATABASES["default"] = {  # noqa: F405
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "test.sqlite3",  # noqa: F405
    }
# Otherwise PostgreSQL from POSTGRES_* env; pytest-django creates its own test_<name> DB.

CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
