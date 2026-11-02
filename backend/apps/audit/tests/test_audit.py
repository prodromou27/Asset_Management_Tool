import pytest
from django.db import connection, transaction
from django.db.utils import DatabaseError

from apps.audit import services
from apps.audit.models import AuditEvent
from tests.conftest import requires_postgres

pytestmark = pytest.mark.django_db

EVENTS = "/api/v1/audit/events/"


def test_unauthenticated_cannot_read_audit(api_client):
    assert api_client.get(EVENTS).status_code == 401


def test_role_without_audit_permission_is_denied(client_for, operator_user):
    assert client_for(operator_user).get(EVENTS).status_code == 403


def test_auditor_lists_and_filters_events(client_for, auditor_user, admin_user):
    services.record(action="users.update", actor=admin_user, object_type="user", object_id="x")
    client = client_for(auditor_user)

    body = client.get(EVENTS).json()
    assert body["count"] == 2  # auditor login + the update
    assert {e["action"] for e in body["items"]} == {"auth.login", "users.update"}

    filtered = client.get(EVENTS + "?action=users.update&actor=ADMIN.ONE").json()
    assert [e["actor_label"] for e in filtered["items"]] == ["admin.one"]
    assert filtered["items"][0]["actor_id"] == str(admin_user.pk)


def test_invalid_time_filter_is_422(client_for, auditor_user):
    response = client_for(auditor_user).get(EVENTS + "?from=yesterday")

    assert response.status_code == 422
    assert "from" in response.json()["error"]["field_errors"]


def test_events_are_newest_first_with_request_id(client_for, auditor_user):
    client = client_for(auditor_user)
    client.get(EVENTS, HTTP_X_REQUEST_ID="req-123456789")
    services.record(action="later.event", actor_label="system")

    items = client.get(EVENTS).json()["items"]

    assert items[0]["action"] == "later.event"
    login_event = AuditEvent.objects.get(action="auth.login")
    assert len(login_event.request_id) >= 8


def test_sensitive_keys_are_redacted():
    event = services.record(
        action="settings.test",
        actor_label="system",
        before={"smtp_password": "hunter2", "host": "mail"},
        after={"api_token": "abc", "client_secret": "s", "host": "mail2"},
    )

    assert event.before == {"smtp_password": "[redacted]", "host": "mail"}
    assert event.after == {
        "api_token": "[redacted]",
        "client_secret": "[redacted]",
        "host": "mail2",
    }


def test_model_refuses_update_and_delete():
    event = services.record(action="x.y", actor_label="system")

    with pytest.raises(RuntimeError):
        event.save()
    with pytest.raises(RuntimeError):
        event.delete()


def test_audit_api_is_read_only(client_for, admin_user):
    client = client_for(admin_user)

    assert client.post(EVENTS, {}, format="json").status_code == 405
    assert client.delete(EVENTS).status_code == 405


@requires_postgres
def test_postgres_trigger_blocks_raw_update_and_delete():
    services.record(action="x.y", actor_label="system")

    for sql in ("UPDATE audit_auditevent SET action = 'tampered'", "DELETE FROM audit_auditevent"):
        with pytest.raises(DatabaseError), transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute(sql)

    assert AuditEvent.objects.get().action == "x.y"


class _Req:
    def __init__(self, meta):
        self.META = meta


@pytest.mark.parametrize(
    ("proxies", "xff", "expected"),
    [
        (0, "203.0.113.9", "10.0.0.5"),  # header ignored without a trusted proxy
        (1, "198.51.100.7, 203.0.113.9", "203.0.113.9"),  # spoofed first hop ignored
        (1, "", "10.0.0.5"),
    ],
)
def test_client_ip_honours_only_trusted_proxy_hops(settings, proxies, xff, expected):
    settings.REST_FRAMEWORK = {**settings.REST_FRAMEWORK, "NUM_PROXIES": proxies}
    request = _Req({"REMOTE_ADDR": "10.0.0.5", "HTTP_X_FORWARDED_FOR": xff})

    assert services.client_ip(request) == expected


def test_client_ip_rejects_malformed_values(settings):
    settings.REST_FRAMEWORK = {**settings.REST_FRAMEWORK, "NUM_PROXIES": 1}

    assert services.client_ip(_Req({"HTTP_X_FORWARDED_FOR": "not-an-ip"})) is None
