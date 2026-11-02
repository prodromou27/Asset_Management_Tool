import pytest

from apps.accounts.models import SecuritySettings
from apps.audit.models import AuditEvent
from conftest import login

pytestmark = pytest.mark.django_db

URL = "/api/v1/settings/security/"


def test_unauthenticated_denied(api_client):
    assert api_client.get(URL).status_code == 401


def test_role_without_permission_cannot_view(client_for, operator_user):
    assert client_for(operator_user).get(URL).status_code == 403


def test_auditor_can_view_but_not_change(client_for, auditor_user):
    client = client_for(auditor_user)

    assert client.get(URL).status_code == 200
    response = client.patch(URL, {"lockout_threshold": 3}, format="json", HTTP_IF_MATCH='"1"')
    assert response.status_code == 403
    assert SecuritySettings.load().lockout_threshold == 5
    assert not AuditEvent.objects.filter(action="settings.security.update").exists()


def test_admin_reads_defaults(client_for, admin_user):
    response = client_for(admin_user).get(URL)

    assert response.status_code == 200
    assert response["ETag"] == '"1"'
    assert response.json() | {"modified_at": None} == {
        "session_idle_timeout_minutes": 30,
        "session_absolute_timeout_hours": 12,
        "lockout_threshold": 5,
        "lockout_duration_minutes": 15,
        "password_min_length": 12,
        "version": 1,
        "modified_at": None,
        "modified_by": None,
    }


def test_admin_updates_with_version_guard_and_audit(client_for, admin_user):
    client = client_for(admin_user)

    assert client.patch(URL, {"lockout_threshold": 3}, format="json").status_code == 428
    response = client.patch(URL, {"lockout_threshold": 3}, format="json", HTTP_IF_MATCH='"1"')

    assert response.status_code == 200
    assert response.json()["version"] == 2
    assert response.json()["modified_by"] == "admin.one"
    event = AuditEvent.objects.get(action="settings.security.update")
    assert event.before["lockout_threshold"] == 5
    assert event.after["lockout_threshold"] == 3
    stale = client.patch(URL, {"lockout_threshold": 4}, format="json", HTTP_IF_MATCH='"1"')
    assert stale.status_code == 409


@pytest.mark.parametrize(
    "payload",
    [
        {"password_min_length": 8},
        {"lockout_threshold": 1},
        {"session_idle_timeout_minutes": 0},
        {"session_absolute_timeout_hours": 1, "session_idle_timeout_minutes": 120},
    ],
    ids=["pw-below-12", "lockout-below-3", "idle-zero", "idle-over-absolute"],
)
def test_out_of_range_values_rejected(client_for, admin_user, payload):
    response = client_for(admin_user).patch(URL, payload, format="json", HTTP_IF_MATCH='"1"')

    assert response.status_code == 422
    assert SecuritySettings.load().version == 1


def test_configured_password_length_enforced(client_for, admin_user):
    SecuritySettings.objects.filter(pk=1).update(password_min_length=20)

    response = client_for(admin_user).post(
        "/api/v1/users/",
        {
            "username": "short.pw",
            "display_name": "Short",
            "roles": ["read_only"],
            "password": "Sixteen-Chars-01",
        },
        format="json",
    )

    assert response.status_code == 422
    assert "20 characters" in response.json()["error"]["field_errors"]["password"][0]


def test_configured_lockout_threshold_used(api_client, operator_user):
    SecuritySettings.objects.filter(pk=1).update(lockout_threshold=3)
    for _ in range(3):
        login(api_client, "operator.one", "wrong-password-123")

    operator_user.refresh_from_db()
    assert operator_user.is_locked
