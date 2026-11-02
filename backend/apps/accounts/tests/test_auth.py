import time
from datetime import timedelta

import pytest
from django.conf import settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.middleware import SESSION_AUTH_AT, SESSION_LAST_SEEN
from apps.accounts.models import SecuritySettings, User
from apps.accounts.services import LOGIN_FAILED_MESSAGE
from apps.audit.models import AuditEvent
from conftest import PASSWORD, login

pytestmark = pytest.mark.django_db

ME = "/api/v1/auth/me/"


def test_login_success_returns_identity_and_permissions(api_client, admin_user):
    response = login(api_client, "ADMIN.ONE")  # username is case-insensitive

    assert response.status_code == 200
    body = response.json()
    assert body["username"] == "admin.one"
    assert "users.manage" in body["permissions"]
    assert body["must_change_password"] is False
    assert api_client.get(ME).status_code == 200
    event = AuditEvent.objects.get(action="auth.login")
    assert event.outcome == "success"
    assert event.actor == admin_user


@pytest.mark.parametrize(
    ("username", "password"),
    [("admin.one", "wrong-password-123"), ("nobody.here", PASSWORD)],
)
def test_failed_login_is_generic_and_audited(api_client, admin_user, username, password):
    response = login(api_client, username, password)

    assert response.status_code == 401
    assert response.json()["error"] == {
        "code": "LOGIN_FAILED",
        "message": LOGIN_FAILED_MESSAGE,
        "request_id": response["X-Request-ID"],
        "field_errors": {},
    }
    event = AuditEvent.objects.get(action="auth.login")
    assert event.outcome == "failure"
    assert event.actor is None
    assert password not in str(event.before) + str(event.after) + event.detail


def test_disabled_account_cannot_log_in_even_with_correct_password(api_client, make_user):
    make_user("gone.user", is_active=False)

    response = login(api_client, "gone.user")

    assert response.status_code == 401
    assert response.json()["error"]["message"] == LOGIN_FAILED_MESSAGE
    assert AuditEvent.objects.get(action="auth.login").detail == "account disabled"


def test_account_locks_after_threshold_and_unlocks_after_duration(api_client, operator_user):
    policy = SecuritySettings.load()
    for _ in range(policy.lockout_threshold):
        assert login(api_client, "operator.one", "wrong-password-123").status_code == 401

    operator_user.refresh_from_db()
    assert operator_user.is_locked
    assert AuditEvent.objects.filter(action="auth.account_locked").count() == 1
    assert login(api_client, "operator.one").status_code == 401  # correct password, still locked

    User.objects.filter(pk=operator_user.pk).update(
        locked_until=timezone.now() - timedelta(seconds=1)
    )
    assert login(api_client, "operator.one").status_code == 200


def test_login_is_rate_limited_per_client(api_client, operator_user):
    statuses = [login(api_client, "nobody", "x").status_code for _ in range(11)]

    assert statuses[:10] == [401] * 10
    assert statuses[10] == 429
    assert (
        api_client.post("/api/v1/auth/local/login/", {}, format="json").json()["error"]["code"]
        == "TOO_MANY_REQUESTS"
    )


def test_login_rotates_session_key(api_client, operator_user):
    api_client.get("/api/v1/auth/csrf/")
    session = api_client.session
    session["pre_login"] = True
    session.save()
    before = api_client.cookies[settings.SESSION_COOKIE_NAME].value

    login(api_client, "operator.one")

    assert api_client.cookies[settings.SESSION_COOKIE_NAME].value != before


def test_login_requires_csrf_token(operator_user):
    client = APIClient(enforce_csrf_checks=True)
    assert login(client, "operator.one").status_code == 403

    client.get("/api/v1/auth/csrf/")
    token = client.cookies[settings.CSRF_COOKIE_NAME].value
    response = client.post(
        "/api/v1/auth/local/login/",
        {"username": "operator.one", "password": PASSWORD},
        format="json",
        HTTP_X_CSRFTOKEN=token,
    )
    assert response.status_code == 200


def test_authenticated_unsafe_request_requires_csrf_token(operator_user):
    client = APIClient(enforce_csrf_checks=True)
    client.get("/api/v1/auth/csrf/")
    token = client.cookies[settings.CSRF_COOKIE_NAME].value
    client.post(
        "/api/v1/auth/local/login/",
        {"username": "operator.one", "password": PASSWORD},
        format="json",
        HTTP_X_CSRFTOKEN=token,
    )

    assert client.post("/api/v1/auth/logout/").status_code == 403
    new_token = client.cookies[settings.CSRF_COOKIE_NAME].value  # rotated at login
    assert client.post("/api/v1/auth/logout/", HTTP_X_CSRFTOKEN=new_token).status_code == 204


def test_unauthenticated_request_gets_401_envelope_and_request_id(api_client):
    response = api_client.get(ME, HTTP_X_REQUEST_ID="trace-abc-12345")

    assert response.status_code == 401
    assert response["X-Request-ID"] == "trace-abc-12345"
    assert response.json()["error"]["code"] == "NOT_AUTHENTICATED"
    assert response.json()["error"]["request_id"] == "trace-abc-12345"


def test_logout_ends_session_and_is_audited(client_for, operator_user):
    client = client_for(operator_user)

    assert client.post("/api/v1/auth/logout/").status_code == 204
    assert client.get(ME).status_code == 401
    assert AuditEvent.objects.filter(action="auth.logout", actor=operator_user).exists()


@pytest.mark.parametrize(
    ("key", "age_seconds"),
    [(SESSION_LAST_SEEN, 31 * 60), (SESSION_AUTH_AT, 13 * 3600)],
    ids=["idle", "absolute"],
)
def test_session_expires_after_configured_timeout(client_for, operator_user, key, age_seconds):
    client = client_for(operator_user)
    session = client.session
    session[key] = time.time() - age_seconds
    session.save()

    assert client.get(ME).status_code == 401
    assert AuditEvent.objects.filter(action="auth.session_expired").count() == 1


def test_session_without_login_timestamps_is_rejected(api_client, operator_user):
    api_client.force_login(operator_user)  # bypasses login_local, so no timestamps

    assert api_client.get(ME).status_code == 401


def test_temporary_password_blocks_api_until_changed(client_for, make_user):
    user = make_user("new.auditor", roles=["auditor"], must_change_password=True)
    client = client_for(user)

    me = client.get(ME)
    assert me.status_code == 200 and me.json()["must_change_password"] is True
    blocked = client.get("/api/v1/users/")
    assert blocked.status_code == 403
    assert blocked.json()["error"]["code"] == "PASSWORD_CHANGE_REQUIRED"

    response = client.post(
        "/api/v1/auth/password/change/",
        {"current_password": PASSWORD, "new_password": "Another-Strong-Pass-42"},
        format="json",
    )
    assert response.status_code == 204
    assert client.get("/api/v1/users/").status_code == 200  # session kept, auditor may view
    assert AuditEvent.objects.filter(action="auth.password_changed", actor=user).exists()


@pytest.mark.parametrize(
    ("current", "new", "field"),
    [
        ("wrong-current-pass", "Another-Strong-Pass-42", "current_password"),
        (PASSWORD, PASSWORD, "new_password"),
        (PASSWORD, "short", "new_password"),
        (PASSWORD, "password123456", "new_password"),
    ],
    ids=["wrong-current", "reuse", "too-short", "common"],
)
def test_password_change_validation(client_for, operator_user, current, new, field):
    client = client_for(operator_user)

    response = client.post(
        "/api/v1/auth/password/change/",
        {"current_password": current, "new_password": new},
        format="json",
    )

    assert response.status_code == 422
    assert field in response.json()["error"]["field_errors"]


def test_password_change_revokes_other_sessions(client_for, operator_user):
    first = client_for(operator_user)
    second = client_for(operator_user)

    first.post(
        "/api/v1/auth/password/change/",
        {"current_password": PASSWORD, "new_password": "Another-Strong-Pass-42"},
        format="json",
    )

    assert first.get(ME).status_code == 200
    assert second.get(ME).status_code == 401


def test_production_hasher_is_argon2():
    from config.settings import base

    assert base.PASSWORD_HASHERS[0] == "django.contrib.auth.hashers.Argon2PasswordHasher"


def test_providers_list_local_available_and_sso_planned(api_client):
    providers = {p["id"]: p["status"] for p in api_client.get("/api/v1/auth/providers/").json()}

    assert providers == {"local": "available", "entra": "planned"}
