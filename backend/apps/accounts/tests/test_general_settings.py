import pytest

from apps.accounts.models import GeneralSettings
from apps.audit.models import AuditEvent

pytestmark = pytest.mark.django_db
URL = "/api/v1/settings/general/"


def test_general_settings_permissions_and_display_subset(
    api_client, client_for, operator_user, auditor_user
):
    assert api_client.get(URL).status_code == 401
    operator = client_for(operator_user)
    assert operator.get(URL).status_code == 403
    display = operator.get("/api/v1/auth/me/").json()["display_preferences"]
    assert display["timezone"] == "Asia/Nicosia"
    assert "modified_by" not in display and "version" not in display
    auditor = client_for(auditor_user)
    assert auditor.get(URL).status_code == 200
    assert (
        auditor.patch(
            URL, {"organization_name": "Denied"}, format="json", HTTP_IF_MATCH='"1"'
        ).status_code
        == 403
    )


def test_general_settings_version_guard_audit_and_effective_display(client_for, admin_user):
    client = client_for(admin_user)
    assert client.get(URL)["ETag"] == '"1"'
    payload = {"organization_name": "Fixture Organization", "timezone": "UTC", "date_format": "iso"}
    assert client.patch(URL, payload, format="json").status_code == 428
    result = client.patch(URL, payload, format="json", HTTP_IF_MATCH='"1"')
    assert result.status_code == 200 and result["ETag"] == '"2"'
    event = AuditEvent.objects.get(action="settings.general.update")
    assert event.before["timezone"] == "Asia/Nicosia" and event.after["timezone"] == "UTC"
    assert (
        client.get("/api/v1/auth/me/").json()["display_preferences"]["organization_name"]
        == payload["organization_name"]
    )
    assert client.patch(URL, payload, format="json", HTTP_IF_MATCH='"1"').status_code == 409
    assert client.patch(URL, payload, format="json", HTTP_IF_MATCH='"2"').json()["version"] == 2
    assert AuditEvent.objects.filter(action="settings.general.update").count() == 1


@pytest.mark.parametrize(
    "payload",
    [
        {"timezone": "Invalid/Zone"},
        {"timezone": "../UTC"},
        {"organization_name": "   "},
        {"support_contact": "not-an-email"},
        {"language": "el"},
        {"date_format": "unknown"},
        {"retention_days": 1},
        {"version": 999},
        {"organization_name": "x" * 101},
    ],
)
def test_invalid_or_deployment_controlled_settings_rejected(client_for, admin_user, payload):
    response = client_for(admin_user).patch(URL, payload, format="json", HTTP_IF_MATCH='"1"')
    assert response.status_code == 422
    assert GeneralSettings.load().version == 1
    assert not AuditEvent.objects.filter(action="settings.general.update").exists()
