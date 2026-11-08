import io
from datetime import timedelta
from types import SimpleNamespace

import pyotp
import pytest
from django.conf import settings
from django.core.management import call_command
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts import local_mfa
from apps.accounts.models import User
from apps.audit.models import AuditEvent
from apps.imports.crypto import decrypt
from conftest import PASSWORD, login

pytestmark = pytest.mark.django_db
NOW = 1_800_000_000
ME = "/api/v1/auth/me/"
BASE = "/api/v1/auth/mfa/"


@pytest.fixture(autouse=True)
def otp_clock(monkeypatch):
    monkeypatch.setattr(local_mfa, "time", SimpleNamespace(time=lambda: NOW))


def enroll(client):
    setup = client.post(BASE + "setup/", {"password": PASSWORD}, format="json")
    assert setup.status_code == 200
    assert setup["Cache-Control"] == "no-store"
    secret = setup.json()["secret"]
    result = client.post(
        BASE + "confirm/",
        {"password": PASSWORD, "otp_code": pyotp.TOTP(secret).at(NOW - 30)},
        format="json",
    )
    assert result.status_code == 200, result.json()
    assert result["Cache-Control"] == "no-store"
    return secret, result.json()["recovery_codes"]


def sign_in(username, code="", password=PASSWORD):
    client = APIClient()
    response = client.post(
        "/api/v1/auth/local/login/",
        {"username": username, "password": password, "otp_code": code},
        format="json",
    )
    return client, response


def test_optional_password_only_local_with_entra_enabled(client_for, operator_user, settings):
    settings.ITAM_ENTRA_ENABLED = True
    client = client_for(operator_user)
    assert client.get(ME).json()["mfa_enabled"] is False
    assert client.get(ME).json()["auth_method"] == "local"
    settings.ITAM_ENV = "production"
    settings.ITAM_ENTRA_ENABLED = False
    from apps.accounts.checks import entra_deployment_policy

    assert not entra_deployment_policy(None)


def test_enrollment_encrypts_secret_and_revokes_other_sessions(client_for, operator_user):
    owner = client_for(operator_user)
    other = client_for(operator_user)
    secret, codes = enroll(owner)
    operator_user.refresh_from_db()
    assert secret.encode() not in bytes(operator_user.mfa_secret)
    assert decrypt(operator_user.mfa_secret, local_mfa.PURPOSE).decode() == secret
    assert len(codes) == 10
    assert not any(code in str(operator_user.mfa_recovery_hashes) for code in codes)
    assert owner.get(ME).json()["auth_method"] == "local_mfa"
    assert other.get(ME).status_code == 401
    assert codes[0] not in str(list(AuditEvent.objects.values()))
    assert secret not in str(list(AuditEvent.objects.values()))


@pytest.mark.parametrize("code", ["", "bad-code", "1234567"])
def test_no_session_before_required_factor(client_for, operator_user, code):
    enroll(client_for(operator_user))
    client, response = sign_in(operator_user.username, code)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "LOGIN_FAILED"
    assert client.get(ME).status_code == 401
    operator_user.refresh_from_db()
    assert operator_user.failed_login_count == 1


def test_totp_and_recovery_are_one_use(client_for, operator_user):
    secret, codes = enroll(client_for(operator_user))
    code = pyotp.TOTP(secret).at(NOW)
    client, response = sign_in(operator_user.username, code)
    assert response.status_code == 200
    assert client.get(ME).json()["auth_method"] == "local_mfa"
    assert sign_in(operator_user.username, code)[1].status_code == 401
    assert sign_in(operator_user.username, codes[0])[1].status_code == 200
    assert sign_in(operator_user.username, codes[0])[1].status_code == 401
    assert sign_in(operator_user.username, codes[1], "wrong-password")[1].status_code == 401
    assert sign_in(operator_user.username, codes[1])[1].status_code == 200


def test_old_codes_and_lockout_fail_closed(client_for, operator_user):
    from apps.accounts.models import SecuritySettings

    policy = SecuritySettings.load()
    policy.lockout_threshold = 3
    policy.save()
    secret, _ = enroll(client_for(operator_user))
    assert sign_in(operator_user.username, pyotp.TOTP(secret).at(NOW - 300))[1].status_code == 401
    assert sign_in(operator_user.username, "bad-code")[1].status_code == 401
    assert sign_in(operator_user.username, "bad-code")[1].status_code == 401
    operator_user.refresh_from_db()
    assert operator_user.is_locked
    assert sign_in(operator_user.username, pyotp.TOTP(secret).at(NOW))[1].status_code == 401


def test_setup_is_pending_expiring_and_requires_password(client_for, operator_user):
    client = client_for(operator_user)
    assert client.post(BASE + "setup/", {"password": "wrong"}, format="json").status_code == 401
    setup = client.post(BASE + "setup/", {"password": PASSWORD}, format="json").json()
    assert login(APIClient(), operator_user.username).status_code == 200
    User.objects.filter(pk=operator_user.pk).update(
        mfa_pending_until=timezone.now() - timedelta(seconds=1)
    )
    result = client.post(
        BASE + "confirm/",
        {"password": PASSWORD, "otp_code": pyotp.TOTP(setup["secret"]).at(NOW)},
        format="json",
    )
    assert result.status_code == 401
    operator_user.refresh_from_db()
    assert not operator_user.mfa_enabled
    assert AuditEvent.objects.filter(
        action="auth.mfa_verification_failed", outcome="failure"
    ).exists()


def test_upgrade_preserves_existing_linked_accounts_as_local_disabled(make_user):
    from importlib import import_module

    from django.apps import apps

    linked = make_user(
        "existing.sso",
        entra_tenant_id="11111111-1111-4111-8111-111111111111",
        entra_object_id="22222222-2222-4222-8222-222222222222",
    )
    local = make_user("existing.local")
    migration = import_module("apps.accounts.migrations.0018_optional_local_mfa")
    migration.preserve_sso_only_accounts(apps, None)
    linked.refresh_from_db()
    local.refresh_from_db()
    assert not linked.local_login_enabled
    assert local.local_login_enabled and local.check_password(PASSWORD)


def test_disable_requires_fresh_password_and_factor_and_revokes_sessions(client_for, operator_user):
    owner = client_for(operator_user)
    _, codes = enroll(owner)
    other, _ = sign_in(operator_user.username, codes[0])
    assert owner.post(BASE + "disable/", {"password": PASSWORD}, format="json").status_code == 401
    assert (
        owner.post(
            BASE + "disable/", {"password": PASSWORD, "otp_code": codes[1]}, format="json"
        ).status_code
        == 200
    )
    assert owner.get(ME).json()["mfa_enabled"] is False
    assert other.get(ME).status_code == 401
    assert login(APIClient(), operator_user.username).status_code == 200


def test_lost_encryption_key_fails_closed_but_recovery_works(client_for, operator_user, settings):
    secret, codes = enroll(client_for(operator_user))
    # Use a valid independent Fernet key, as an operator might configure during a mistaken rotation.
    from cryptography.fernet import Fernet

    settings.ITAM_IMPORT_ENCRYPTION_KEY = Fernet.generate_key().decode()
    assert sign_in(operator_user.username, pyotp.TOTP(secret).at(NOW))[1].status_code == 401
    assert sign_in(operator_user.username, codes[0])[1].status_code == 200


def test_only_protected_cli_can_reset_lost_factor(client_for, operator_user):
    client = client_for(operator_user)
    enroll(client)
    output = io.StringIO()
    call_command(
        "reset_local_mfa",
        username=operator_user.username,
        reason="INC-local-recovery",
        stdout=output,
    )
    assert client.get(ME).status_code == 401
    assert login(APIClient(), operator_user.username).status_code == 200
    assert AuditEvent.objects.filter(action="auth.mfa_operator_reset", source="cli").exists()


def test_mfa_management_requires_authenticated_csrf_session(operator_user):
    assert APIClient().post(BASE + "setup/", {"password": PASSWORD}).status_code == 401
    client = APIClient(enforce_csrf_checks=True)
    client.get("/api/v1/auth/csrf/")
    token = client.cookies[settings.CSRF_COOKIE_NAME].value
    assert (
        client.post(
            "/api/v1/auth/local/login/",
            {
                "username": operator_user.username,
                "password": PASSWORD,
            },
            HTTP_X_CSRFTOKEN=token,
        ).status_code
        == 200
    )
    assert client.post(BASE + "setup/", {"password": PASSWORD}).status_code == 403
