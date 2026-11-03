"""Connector admin API: configuration, approval, connection test, manual sync, evidence."""

import json

import pytest

from apps.assets.tests.fixtures import grant
from apps.audit.models import AuditEvent
from apps.integrations.models import SyncRun
from apps.reconciliation import services
from apps.reconciliation.models import ReconciliationCandidate
from apps.reconciliation.tests.conftest import Req

from .conftest import TOKEN, make_librenms, run_sync

pytestmark = pytest.mark.django_db
INTEGRATIONS = "/api/v1/integrations/"


def patch(client, instance, body):
    current = client.get(f"{INTEGRATIONS}{instance.pk}/").json()
    return client.patch(
        f"{INTEGRATIONS}{instance.pk}/",
        body,
        format="json",
        HTTP_IF_MATCH=f'"{current["version"]}"',
    )


def test_configuration_is_validated_and_never_returns_the_token(client_for, admin_user, lnms):
    client = client_for(admin_user)

    for body, field in [
        ({"credential_ref": "env:DJANGO_SECRET_KEY"}, "credential_ref"),
        ({"credential_ref": "file:../../etc/shadow"}, "credential_ref"),
        ({"ca_bundle_ref": "env:ITAM_INTEGRATION_CA"}, "ca_bundle_ref"),
        ({"timeout_seconds": 1}, "timeout_seconds"),
        ({"requests_per_second": 500}, "requests_per_second"),
        ({"sync_interval_minutes": 1}, "sync_interval_minutes"),
        ({"source_timezone": "Mars/Base"}, "source_timezone"),
        ({"base_url": "http://librenms.corp.example"}, "base_url"),
    ]:
        response = patch(client, lnms, body)
        assert response.status_code == 422, body
        assert field in response.json()["error"]["field_errors"], body

    ok = patch(
        client,
        lnms,
        {"timeout_seconds": 20, "sync_interval_minutes": 60, "source_timezone": "Europe/Nicosia"},
    )
    assert ok.status_code == 200
    data = ok.json()
    assert (
        data["credential_status"] == "configured"
        and data["credential_ref"] == "env:ITAM_INTEGRATION_LNMS_TOKEN"
    )
    assert data["has_adapter"] is True and data["live_integrations_enabled"] is True
    assert TOKEN not in json.dumps(data)
    update = AuditEvent.objects.filter(action="integrations.update").latest("occurred_at")
    assert TOKEN not in json.dumps([update.before, update.after])


def test_live_access_approval_is_audited_and_revocable(client_for, admin_user, hq, live):
    instance = make_librenms(hq, live_access_approved=False)
    client = client_for(admin_user)
    url = f"{INTEGRATIONS}{instance.pk}/live-access/"

    assert client.post(url, {"approved": True, "reason": ""}, format="json").status_code == 422
    approved = client.post(
        url, {"approved": True, "reason": "CAB-2026-114 read-only account"}, format="json"
    )
    assert approved.status_code == 200
    body = approved.json()
    assert body["live_access_approved"] is True and body["live_access_approved_by"] == "admin.one"
    assert AuditEvent.objects.filter(action="integrations.live_access_approve").exists()

    revoked = client.post(url, {"approved": False, "reason": "Account rotated"}, format="json")
    assert (
        revoked.json()["live_access_approved"] is False and revoked.json()["next_sync_at"] is None
    )
    assert AuditEvent.objects.filter(action="integrations.live_access_revoke").exists()


def test_connection_test_reports_version_and_capabilities(client_for, admin_user, lnms, fake):
    response = client_for(admin_user).post(f"{INTEGRATIONS}{lnms.pk}/test/")

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True and body["version"] == "24.10.0"
    assert body["capabilities"]["fdb"] is True and body["capabilities"]["links"] is True
    assert fake.paths() == ["/system", "", "/devices"]
    lnms.refresh_from_db()
    assert lnms.last_test_ok is True and lnms.source_software_version == "24.10.0"
    assert AuditEvent.objects.filter(
        action="integrations.test_connection", outcome="success"
    ).exists()


def test_connection_test_failure_is_recorded_without_secrets(client_for, admin_user, lnms, fake):
    fake.overrides["/system"] = (401, {"status": "error", "message": "Unauthenticated."})

    body = client_for(admin_user).post(f"{INTEGRATIONS}{lnms.pk}/test/").json()

    assert body["ok"] is False and "rejected the API token" in body["message"]
    assert TOKEN not in json.dumps(body)
    lnms.refresh_from_db()
    assert lnms.last_test_ok is False


def test_connection_test_respects_the_deployment_gate(client_for, admin_user, lnms, fake, settings):
    settings.ITAM_ALLOW_LIVE_INTEGRATIONS = False

    body = client_for(admin_user).post(f"{INTEGRATIONS}{lnms.pk}/test/").json()

    assert body["ok"] is False and "disabled for this deployment" in body["message"]
    assert fake.requests == []


def test_sync_now_queues_a_run_and_refuses_a_second(client_for, admin_user, lnms):
    client = client_for(admin_user)
    url = f"{INTEGRATIONS}{lnms.pk}/sync/"

    first = client.post(url, {"mode": "full"}, format="json")
    assert first.status_code == 202 and first.json()["status"] == "queued"
    assert first.json()["triggered_by"] == "user:admin.one"
    assert AuditEvent.objects.filter(action="integrations.sync_requested").exists()

    second = client.post(url, {"mode": "full"}, format="json")
    assert second.status_code == 409 and second.json()["error"]["code"] == "SYNC_IN_PROGRESS"


def test_sync_now_refused_without_approval(client_for, admin_user, hq, live):
    instance = make_librenms(hq, live_access_approved=False)
    response = client_for(admin_user).post(f"{INTEGRATIONS}{instance.pk}/sync/", {}, format="json")
    assert (
        response.status_code == 422
        and response.json()["error"]["code"] == "LIVE_ACCESS_NOT_APPROVED"
    )
    assert not SyncRun.objects.exists()


def test_connector_actions_require_integrations_manage(client_for, hq_manager, lnms):
    client = client_for(hq_manager)
    for action in ("test", "sync", "live-access"):
        assert (
            client.post(f"{INTEGRATIONS}{lnms.pk}/{action}/", {}, format="json").status_code == 403
        )


def test_run_history_shows_progress_and_warnings(client_for, admin_user, lnms, fake):
    run_sync(lnms)

    detail = client_for(admin_user).get(f"{INTEGRATIONS}{lnms.pk}/").json()
    assert detail["last_run"]["status"] == "succeeded" and detail["last_run"]["devices_total"] == 10
    assert detail["open_candidates"] == 10 and detail["source_software_version"] == ""
    runs = client_for(admin_user).get(f"{INTEGRATIONS}{lnms.pk}/runs/").json()["items"]
    assert runs[0]["api_requests"] == 33 and runs[0]["warnings"] == 2
    assert runs[0]["evidence_rows"] == 5 and runs[0]["phase"] == "done"


# --- Network evidence on assets -------------------------------------------------------------------


def _asset(instance, external_id, user, category):
    c = ReconciliationCandidate.objects.get(instance=instance, external_id=external_id)
    services.approve_create(Req(user), c, {"category": category}, "Approve", c.version)
    return c.instance.links.get(external_id=external_id).asset


def test_network_evidence_is_scoped_and_never_a_confirmed_cable(
    client_for, admin_user, make_user, lnms, fake, switch, branch
):
    run_sync(lnms)
    core = _asset(lnms, "101", admin_user, switch)
    access = _asset(lnms, "103", admin_user, switch)
    rows = client_for(admin_user).get(f"/api/v1/assets/{core.pk}/network-evidence/").json()

    assert {r["kind"] for r in rows} == {"fdb", "lldp", "cdp"}
    assert all(r["is_physical_link_confirmed"] is False for r in rows)
    lldp = next(r for r in rows if r["kind"] == "lldp")
    assert lldp["direction"] == "local" and lldp["remote_asset"]["id"] == str(access.pk)

    seen_on_core = (
        client_for(admin_user).get(f"/api/v1/assets/{access.pk}/network-evidence/").json()
    )
    assert any(r["direction"] == "remote" and r["kind"] == "lldp" for r in seen_on_core)

    outsider = grant(make_user("br.manager", roles=["itam_manager"]), branch)
    assert (
        client_for(outsider).get(f"/api/v1/assets/{core.pk}/network-evidence/").status_code == 404
    )
