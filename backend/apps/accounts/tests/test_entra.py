import base64
import hashlib
import io
import json
import time
from datetime import timedelta
from urllib.parse import parse_qs, urlsplit
from uuid import UUID

import pytest
import requests
from django.core.management import call_command
from django.core.management.base import CommandError
from django.utils import timezone
from joserfc import jwt
from joserfc.jwk import OctKey, RSAKey
from rest_framework.test import APIClient

from apps.accounts import oidc
from apps.accounts.checks import entra_deployment_policy
from apps.accounts.models import OidcAttempt, User
from apps.audit.models import AuditEvent
from conftest import PASSWORD, login

pytestmark = pytest.mark.django_db
TENANT = "11111111-1111-4111-8111-111111111111"
CLIENT = "22222222-2222-4222-8222-222222222222"
OBJECT = "33333333-3333-4333-8333-333333333333"
START = "/api/v1/auth/entra/start/"
CALLBACK = "/api/v1/auth/entra/callback/"
ME = "/api/v1/auth/me/"


@pytest.fixture(scope="session")
def signing_key():
    return RSAKey.generate_key(2048, parameters={"kid": "fixture"})


@pytest.fixture
def entra(settings, monkeypatch, admin_user, make_user, signing_key):
    settings.ITAM_ENTRA_ENABLED = True
    settings.ITAM_ENTRA_ENFORCE = True
    settings.ITAM_ENTRA_TENANT_ID = TENANT
    settings.ITAM_ENTRA_CLIENT_ID = CLIENT
    settings.ITAM_ENTRA_REDIRECT_URI = "https://itam.example.test" + CALLBACK
    settings.ITAM_ENTRA_CLIENT_SECRET_REF = "env:ITAM_ENTRA_CLIENT_SECRET"
    settings.ITAM_ENTRA_AUTH_CONTEXT = "c1"
    settings.ITAM_ENTRA_MFA_POLICY_VERIFIED = True
    monkeypatch.setenv("ITAM_ENTRA_CLIENT_SECRET", "fixture-client-secret")
    admin_user.entra_tenant_id, admin_user.entra_object_id = UUID(TENANT), UUID(OBJECT)
    admin_user.save()
    make_user("admin.two", roles=["system_admin"])
    requests_seen = []
    flow = {"changes": {}, "key": signing_key}

    def send(session, request, **kwargs):
        requests_seen.append(request)
        assert kwargs["verify"] is True and kwargs["timeout"] == 10
        assert not kwargs.get("proxies")
        if request.url.endswith("/token"):
            body = request.body.decode() if isinstance(request.body, bytes) else request.body
            params = parse_qs(body)
            verifier = params["code_verifier"][0]
            challenge = (
                base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
                .rstrip(b"=")
                .decode()
            )
            assert challenge == flow["query"]["code_challenge"][0]
            assert params["redirect_uri"] == [settings.ITAM_ENTRA_REDIRECT_URI]
            assert params["client_id"] == [CLIENT]
            claims = {
                "iss": f"https://login.microsoftonline.com/{TENANT}/v2.0",
                "aud": CLIENT,
                "sub": "opaque-subject",
                "iat": int(time.time()),
                "exp": int(time.time()) + 3600,
                "nonce": flow["query"]["nonce"][0],
                "tid": TENANT,
                "oid": OBJECT,
                "acrs": ["c1"],
                "roles": ["untrusted-admin-claim"],
            }
            claims.update(flow["changes"])
            payload = {
                "access_token": "fixture-access-token",
                "token_type": "Bearer",
                "id_token": jwt.encode(
                    {"alg": flow.get("algorithm", "RS256"), "kid": "fixture"}, claims, flow["key"]
                ),
            }
        elif request.url.endswith("/keys"):
            payload = {"keys": [signing_key.as_dict(private=False)]}
        else:
            raise AssertionError("Unexpected provider endpoint")
        response = requests.Response()
        response.status_code = 200
        response._content = json.dumps(payload).encode()
        response.headers["Content-Type"] = "application/json"
        response.request, response.url = request, request.url
        return response

    monkeypatch.setattr(oidc.EntraSession, "send", send)
    flow.update(requests=requests_seen, admin=admin_user)
    return flow


def begin(client, flow, next_path="/"):
    response = client.post(START, {"next_path": next_path}, format="json")
    assert response.status_code == 200, response.json()
    flow["query"] = parse_qs(urlsplit(response.json()["authorization_url"]).query)
    return flow["query"]["state"][0]


def complete(client, flow, next_path="/"):
    state = begin(client, flow, next_path)
    return client.get(CALLBACK, {"state": state, "code": "fixture-code"})


def test_signed_oidc_pkce_context_and_session_rotation(api_client, entra):
    state = begin(api_client, entra, "/admin/users?status=active")
    before = api_client.session.session_key
    assert entra["query"]["code_challenge_method"] == ["S256"]
    assert json.loads(entra["query"]["claims"][0])["id_token"]["acrs"]["values"] == ["c1"]
    assert api_client.get(ME).status_code == 401
    response = api_client.get(CALLBACK, {"state": state, "code": "fixture-code"})
    assert response["Location"] == "/admin/users?status=active"
    assert response["Cache-Control"] == "no-store"
    assert response["Referrer-Policy"] == "no-referrer"
    assert api_client.session.session_key != before
    assert api_client.get(ME).json()["id"] == str(entra["admin"].pk)
    assert not OidcAttempt.objects.exists()
    assert "fixture-access-token" not in str(dict(api_client.session))
    assert "fixture-client-secret" not in str(dict(api_client.session))
    assert AuditEvent.objects.filter(action="auth.login", outcome="success").count() == 1


@pytest.mark.parametrize(
    "changes",
    [
        {"iss": "https://attacker.invalid"},
        {"aud": "wrong-client"},
        {"nonce": "wrong-nonce"},
        {"exp": int(time.time()) - 300},
        {"tid": CLIENT},
        {"oid": CLIENT},
        {"acrs": []},
        {"acrs": "c1"},
        {"acrs": ["c2"]},
        {"sub": ""},
    ],
)
def test_signed_but_invalid_identity_claims_fail_closed(api_client, entra, changes):
    entra["changes"] = changes
    response = complete(api_client, entra)
    assert response["Location"] == "/login?sso_error=1"
    assert api_client.get(ME).status_code == 401
    assert not OidcAttempt.objects.exists()
    assert not AuditEvent.objects.filter(action="auth.login", outcome="success").exists()
    event = AuditEvent.objects.get(action="auth.entra_failed")
    assert "fixture-code" not in event.detail


def test_bad_signature_rejected(api_client, entra):
    entra["key"] = RSAKey.generate_key(2048, parameters={"kid": "fixture"})
    assert complete(api_client, entra)["Location"] == "/login?sso_error=1"
    assert api_client.get(ME).status_code == 401


def test_symmetric_algorithm_cannot_replace_provider_signature(api_client, entra):
    entra.update(algorithm="HS256", key=OctKey.generate_key(256))
    assert complete(api_client, entra)["Location"] == "/login?sso_error=1"
    assert api_client.get(ME).status_code == 401


def test_provider_denial_consumes_attempt_without_echoing_error(api_client, entra):
    state = begin(api_client, entra)
    response = api_client.get(
        CALLBACK,
        {"state": state, "error": "access_denied", "error_description": "private-provider-detail"},
    )
    assert response["Location"] == "/login?sso_error=1"
    assert not entra["requests"]
    assert not OidcAttempt.objects.exists()
    assert (
        "private-provider-detail" not in AuditEvent.objects.get(action="auth.entra_failed").detail
    )


def test_state_bound_to_browser_and_single_use(api_client, entra):
    state = begin(api_client, entra)
    other = APIClient()
    assert other.get(CALLBACK, {"state": state, "code": "fixture-code"})["Location"].startswith(
        "/login"
    )
    assert not entra["requests"]
    assert api_client.get(CALLBACK, {"state": state, "code": "fixture-code"})["Location"] == "/"
    total = len(entra["requests"])
    assert api_client.get(CALLBACK, {"state": state, "code": "fixture-code"})[
        "Location"
    ].startswith("/login")
    assert len(entra["requests"]) == total


def test_expired_receipt_never_exchanges_code(api_client, entra):
    state = begin(api_client, entra)
    OidcAttempt.objects.update(expires_at=timezone.now() - timedelta(seconds=1))
    assert api_client.get(CALLBACK, {"state": state, "code": "fixture-code"})[
        "Location"
    ].startswith("/login")
    assert not entra["requests"]


def test_policy_change_invalidates_pending_flow(api_client, entra, settings):
    state = begin(api_client, entra)
    settings.ITAM_ENTRA_AUTH_CONTEXT = "c2"
    assert api_client.get(CALLBACK, {"state": state, "code": "fixture-code"})[
        "Location"
    ].startswith("/login")
    assert not entra["requests"]


def test_no_email_matching_or_token_role_grants(api_client, entra, make_user):
    ordinary = make_user(
        "reader.one", roles=["read_only"], entra_tenant_id=TENANT, entra_object_id=CLIENT
    )
    entra["changes"] = {"oid": CLIENT, "roles": ["system_admin"], "email": entra["admin"].email}
    assert complete(api_client, entra)["Location"] == "/"
    assert api_client.get(ME).json()["id"] == str(ordinary.pk)
    assert api_client.get("/api/v1/users/").status_code == 403


def test_disable_and_factor_expiry_revoke_session(api_client, entra):
    complete(api_client, entra)
    session = api_client.session
    session[oidc.EXPIRES] = time.time() - 1
    session.save()
    assert api_client.get(ME).status_code == 401
    complete(api_client, entra)
    User.objects.filter(pk=entra["admin"].pk).update(is_active=False)
    assert api_client.get(ME).status_code == 401


def test_local_passwords_and_preexisting_sessions_blocked(client_for, entra, settings):
    settings.ITAM_ENTRA_ENABLED = False
    previous = client_for(entra["admin"])
    settings.ITAM_ENTRA_ENABLED = True
    assert previous.get(ME).status_code == 401
    assert login(APIClient(), entra["admin"].username).status_code == 401


def test_explicit_staging_mode_preserves_local_pilot_and_fails_deploy_check(entra, settings):
    settings.ITAM_ENTRA_ENFORCE = False
    assert login(APIClient(), entra["admin"].username).status_code == 200
    assert "accounts.E001" in {error.id for error in entra_deployment_policy(None)}


@pytest.mark.parametrize(
    "next_path", ["//evil.invalid", "https://evil.invalid", "/\\evil", "/\r\nX:evil"]
)
def test_external_or_control_redirect_rejected(api_client, entra, next_path):
    assert api_client.post(START, {"next_path": next_path}, format="json").status_code == 422
    assert not OidcAttempt.objects.exists()


def test_start_requires_csrf(entra):
    client = APIClient(enforce_csrf_checks=True)
    assert client.post(START, {}, format="json").status_code == 403
    client.get("/api/v1/auth/csrf/")
    assert (
        client.post(
            START, {}, format="json", HTTP_X_CSRFTOKEN=client.cookies["itam_csrftoken"].value
        ).status_code
        == 200
    )


def test_mfa_policy_not_assumed_from_context_name(api_client, entra, settings):
    settings.ITAM_ENTRA_MFA_POLICY_VERIFIED = False
    assert api_client.post(START, {}, format="json").status_code == 503
    assert not entra["requests"]


def test_emergency_cli_window_one_use_and_bounded_session(entra, monkeypatch):
    fresh = "Fresh-Emergency-Password-42"
    monkeypatch.setattr("sys.stdin", io.StringIO(fresh + "\n"))
    output = io.StringIO()
    call_command(
        "emergency_access",
        username="admin.one",
        reason="INC-001",
        password_stdin=True,
        stdout=output,
    )
    assert fresh not in output.getvalue()
    user = User.objects.get(pk=entra["admin"].pk)
    assert user.emergency_access_until <= timezone.now() + timedelta(minutes=15)
    client = APIClient()
    assert login(client, user.username, fresh).status_code == 200
    assert login(APIClient(), user.username, fresh).status_code == 401
    user.refresh_from_db()
    assert user.emergency_access_until is None
    session = client.session
    session[oidc.EXPIRES] = time.time() - 1
    session.save()
    assert client.get(ME).status_code == 401
    assert AuditEvent.objects.filter(action="auth.emergency_opened", source="cli").exists()
    assert AuditEvent.objects.filter(action="auth.emergency_login").count() == 1


def test_emergency_rejects_non_admin_and_password_arguments(entra, make_user, monkeypatch):
    ordinary = make_user("ordinary.one")
    monkeypatch.setattr("sys.stdin", io.StringIO(PASSWORD + "\n"))
    with pytest.raises(CommandError):
        call_command(
            "emergency_access", username=ordinary.username, reason="INC-001", password_stdin=True
        )
    with pytest.raises((CommandError, SystemExit)):
        call_command(
            "emergency_access", "--username=admin.one", "--reason=INC-001", "--password=nope"
        )


def test_binding_authorized_versioned_unique_and_revokes_sessions(
    entra, settings, client_for, make_user
):
    settings.ITAM_ENTRA_ENABLED = False  # Configuration stage, before enforcement.
    admin = client_for(entra["admin"])
    target = make_user("mapped.one", roles=["read_only"])
    previous = client_for(target)
    url = f"/api/v1/users/{target.pk}/entra/"
    body = {"tenant_id": TENANT, "object_id": CLIENT}
    assert admin.patch(url, body, format="json").status_code == 428
    response = admin.patch(url, body, format="json", HTTP_IF_MATCH='"1"')
    assert response.status_code == 200
    assert response.json()["entra_object_id"] == CLIENT
    assert previous.get(ME).status_code == 401
    duplicate = make_user("mapped.two")
    assert (
        admin.patch(
            f"/api/v1/users/{duplicate.pk}/entra/", body, format="json", HTTP_IF_MATCH='"1"'
        ).status_code
        == 409
    )
    ordinary = client_for(target)
    assert (
        ordinary.patch(
            url, {"tenant_id": None, "object_id": None}, format="json", HTTP_IF_MATCH='"2"'
        ).status_code
        == 403
    )


def test_sso_temporary_local_password_does_not_block_idp_identity(api_client, entra):
    User.objects.filter(pk=entra["admin"].pk).update(must_change_password=True)
    complete(api_client, entra)
    assert api_client.get(ME).json()["must_change_password"] is False
    assert api_client.get("/api/v1/users/").status_code == 200
    assert api_client.post("/api/v1/auth/password/change/", {}, format="json").status_code == 422


def test_enforcement_keeps_two_admins(api_client, entra):
    complete(api_client, entra)
    other = User.objects.get(username="admin.two")
    assert (
        api_client.post(
            f"/api/v1/users/{other.pk}/disable/", {"reason": "Test incident"}, format="json"
        ).status_code
        == 409
    )


def test_binding_preserves_a_linked_admin_and_prevents_self_replacement(api_client, entra):
    complete(api_client, entra)
    user = entra["admin"]
    url = f"/api/v1/users/{user.pk}/entra/"
    response = api_client.patch(
        url, {"object_id": CLIENT}, format="json", HTTP_IF_MATCH=f'"{user.version}"'
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "SELF_IDENTITY_CHANGE"
    # A separate emergency administrator still cannot remove the sole SSO-admin path.
    from apps.accounts.entra_admin import open_emergency_access

    open_emergency_access("admin.two", PASSWORD, "INC-002", "fixture-operator")
    emergency = APIClient()
    assert login(emergency, "admin.two").status_code == 200
    response = emergency.patch(
        url,
        {"tenant_id": None, "object_id": None},
        format="json",
        HTTP_IF_MATCH=f'"{user.version}"',
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "LAST_SSO_ADMIN"


def test_rebinding_cancels_emergency_window_and_partial_patch_retains_tenant(
    entra, settings, client_for, make_user
):
    from apps.accounts.entra_admin import open_emergency_access

    target = make_user("admin.three", roles=["system_admin"])
    open_emergency_access(target.username, PASSWORD, "INC-003", "fixture-operator")
    settings.ITAM_ENTRA_ENABLED = False
    client = client_for(entra["admin"])
    target.refresh_from_db()
    url = f"/api/v1/users/{target.pk}/entra/"
    response = client.patch(
        url,
        {"tenant_id": TENANT, "object_id": CLIENT},
        format="json",
        HTTP_IF_MATCH=f'"{target.version}"',
    )
    assert response.status_code == 200
    target.refresh_from_db()
    assert target.emergency_access_until is None
    response = client.patch(
        url,
        {"object_id": "44444444-4444-4444-8444-444444444444"},
        format="json",
        HTTP_IF_MATCH=f'"{target.version}"',
    )
    assert response.status_code == 200
    assert response.json()["entra_tenant_id"] == TENANT


def test_emergency_cli_rejects_password_that_cannot_be_submitted(entra, monkeypatch):
    monkeypatch.setattr("sys.stdin", io.StringIO("a" * 129 + "\n"))
    with pytest.raises(CommandError):
        call_command(
            "emergency_access", username="admin.one", reason="INC-004", password_stdin=True
        )
    entra["admin"].refresh_from_db()
    assert entra["admin"].emergency_access_until is None
