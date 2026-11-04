"""Production settings must refuse unsafe configuration at import time."""

import importlib
import sys

import pytest
from django.core.exceptions import ImproperlyConfigured

SAFE_ENV = {
    "ITAM_ENV": "staging",
    "ITAM_PUBLIC_SCHEME": "https",
    "ITAM_DEBUG": "false",
    "DJANGO_SECRET_KEY": "x" * 64,
    "ITAM_ALLOWED_HOSTS": "itam.example.internal",
    "POSTGRES_PASSWORD": "not-a-real-password",
}


def load_production_settings(monkeypatch, **overrides):
    for key, value in {**SAFE_ENV, **overrides}.items():
        monkeypatch.setenv(key, value)
    for module in ("config.settings.production", "config.settings.base"):
        sys.modules.pop(module, None)
    try:
        return importlib.import_module("config.settings.production")
    finally:
        for module in ("config.settings.production", "config.settings.base"):
            sys.modules.pop(module, None)


def test_safe_configuration_loads_with_debug_off_and_secure_cookies(monkeypatch):
    settings = load_production_settings(monkeypatch)

    assert settings.DEBUG is False
    assert settings.SESSION_COOKIE_SECURE is True
    assert settings.CSRF_COOKIE_SECURE is True
    assert settings.DATABASES["default"]["ENGINE"] == "django.db.backends.postgresql"
    assert settings.SECURE_SSL_REDIRECT is True
    assert settings.SECURE_HSTS_SECONDS == 31536000


def test_plain_http_install_turns_off_tls_only_settings(monkeypatch):
    settings = load_production_settings(monkeypatch, ITAM_ENV="staging", ITAM_PUBLIC_SCHEME="http")

    assert settings.DEBUG is False
    assert settings.SECURE_SSL_REDIRECT is False
    assert settings.SESSION_COOKIE_SECURE is False
    assert settings.CSRF_COOKIE_SECURE is False
    assert settings.SECURE_HSTS_SECONDS == 0


@pytest.mark.parametrize(
    "overrides",
    [
        {"ITAM_DEBUG": "true"},
        {"DJANGO_SECRET_KEY": ""},
        {"DJANGO_SECRET_KEY": "too-short"},
        {"DJANGO_SECRET_KEY": "test-" + "x" * 60},
        {"ITAM_ALLOWED_HOSTS": "*"},
        {"POSTGRES_PASSWORD": ""},
        {"ITAM_PUBLIC_SCHEME": "ftp"},
        {"ITAM_PUBLIC_SCHEME": "http", "ITAM_ENV": "production"},
    ],
)
def test_unsafe_configuration_is_refused(monkeypatch, overrides):
    with pytest.raises(ImproperlyConfigured):
        load_production_settings(monkeypatch, **overrides)
