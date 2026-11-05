from datetime import timedelta
from unittest.mock import Mock

import pytest
from django.utils import timezone

from apps.assets.tests.fixtures import grant
from apps.exports import services as exports
from apps.exports.models import ExportJob
from apps.groups.models import AssetGroup, AssetGroupMembership
from apps.integrations.models import IntegrationInstance
from apps.lifecycle.models import LifecycleAssessment
from apps.notifications import services as mail
from apps.notifications.models import OutboxMessage, SmtpProfile
from apps.organizations.models import UserSiteGrant
from apps.reconciliation.models import SourceLink
from apps.reports import digests
from apps.reports.models import DigestDispatch, DigestSchedule

pytestmark = pytest.mark.django_db


@pytest.fixture
def scoped(make_user, hq):
    user = make_user(
        "report.reader", roles=["infrastructure_engineer"], email="reader@example.invalid"
    )
    grant(user, hq)
    return user


@pytest.fixture
def inventory(hq, branch, switch, make_asset, admin_user):
    local = make_asset("Visible switch", site=hq, category=switch)
    unknown = make_asset("Unknown laptop", site=hq, category=switch)
    secret = make_asset("Hidden branch asset", site=branch, category=switch)
    group = AssetGroup.objects.create(name="Replacement scope", kind="static", owner=admin_user)
    for asset in (local, secret):
        AssetGroupMembership.objects.create(
            group=group, asset=asset, source="explicit", added_at=timezone.now()
        )
    LifecycleAssessment.objects.create(
        asset=local,
        dimension="hardware",
        status="eos",
        effective_status="eos",
        evidence_quality="manual",
        assessed_on=timezone.now().date(),
        assessed_at=timezone.now(),
        milestone_date=timezone.now().date(),
        milestone_type="end_of_support",
    )
    return local, unknown, secret, group


def test_reports_clamp_rows_aggregates_groups_and_unknowns(client_for, scoped, inventory, branch):
    client = client_for(scoped)
    for kind in ("inventory", "lifecycle", "coverage", "groups"):
        response = client.get(f"/api/v1/reports/{kind}/")
        assert response.status_code == 200, response.json()
        assert "Hidden branch asset" not in response.content.decode()
        assert response["Cache-Control"] == "no-store"
    lifecycle = client.get("/api/v1/reports/lifecycle/").json()
    assert {row["status"] for row in lifecycle["rows"]} == {"unknown", "eos"}
    totals = client.get("/api/v1/reports/inventory/").json()
    assert totals["count"] == 1 and totals["rows"][0]["total"] == 2
    group = client.get("/api/v1/reports/groups/").json()["rows"][0]
    assert group["members"] == 1 and group["eos"] == 1
    assert "owner" not in group
    assert client.get("/api/v1/reports/lifecycle/", {"site": str(branch.pk)}).json()["count"] == 0
    assert client.get("/api/v1/reports/inventory/", {"breakdown": "owner"}).status_code == 403
    assert (
        client.get("/api/v1/reports/groups/", {"q": "Replacement"}).json()["rows"][0]["members"]
        == 1
    )


def test_report_validation_and_permissions(
    api_client, client_for, admin_user, inventory, make_user
):
    assert api_client.get("/api/v1/reports/inventory/").status_code == 401
    denied = make_user("no.reports", roles=[])
    assert client_for(denied).get("/api/v1/reports/inventory/").status_code == 403
    client = client_for(admin_user)
    for query in (
        {"limit": 101},
        {"offset": -1},
        {"site": "bad"},
        {"arbitrary": "x"},
        {"dimension": "bad"},
    ):
        assert client.get("/api/v1/reports/lifecycle/", query).status_code == 422
    assert client.get("/api/v1/reports/inventory/", {"dimension": "os"}).status_code == 422


@pytest.mark.parametrize("file_format", ["csv", "xlsx", "json"])
def test_report_exports_reuse_encryption_and_revoke_completed_file(
    client_for, scoped, inventory, file_format
):
    client = client_for(scoped)
    response = client.post(
        "/api/v1/exports/",
        {"family": "report_lifecycle", "format": file_format, "scope": "filtered", "filters": {}},
        format="json",
    )
    assert response.status_code == 202
    pk = response.json()["id"]
    exports.run_export(pk)
    job = ExportJob.objects.get(pk=pk)
    assert job.status == "completed" and job.row_count == 2
    assert b"Visible switch" not in bytes(job.file_encrypted)
    download = client.get(f"/api/v1/exports/{pk}/download/")
    assert download.status_code == 200
    if file_format == "json":
        assert "Hidden branch asset" not in download.content.decode()
        assert "Visible switch" in download.content.decode()
    UserSiteGrant.objects.filter(user=scoped).delete()
    assert client.get(f"/api/v1/exports/{pk}/download/").status_code == 403


def test_schedules_are_private_versioned_and_self_only(client_for, admin_user, scoped):
    client = client_for(admin_user)
    body = {
        "report": "inventory",
        "filters": {},
        "enabled": False,
        "cadence": "daily",
        "hour_utc": 7,
        "weekday": 0,
    }
    assert (
        client.post(
            "/api/v1/reports/schedules/",
            {**body, "to_address": "other@example.invalid"},
            format="json",
        ).status_code
        == 422
    )
    result = client.post("/api/v1/reports/schedules/", body, format="json")
    assert result.status_code == 201
    pk = result.json()["id"]
    assert (
        client.patch(
            f"/api/v1/reports/schedules/{pk}/", {"enabled": True}, format="json"
        ).status_code
        == 428
    )
    assert (
        client.patch(
            f"/api/v1/reports/schedules/{pk}/",
            {"enabled": True},
            format="json",
            HTTP_IF_MATCH='"1"',
        ).status_code
        == 200
    )
    assert (
        client.patch(
            f"/api/v1/reports/schedules/{pk}/",
            {"enabled": False},
            format="json",
            HTTP_IF_MATCH='"1"',
        ).status_code
        == 409
    )
    scoped.roles.add(admin_user.roles.get(code="system_admin"))
    assert client_for(scoped).get(f"/api/v1/reports/schedules/{pk}/").status_code == 404


def test_digest_dedup_disabled_mail_and_delivery_revocation(admin_user, monkeypatch):
    monkeypatch.setattr(mail, "_kick", Mock())
    now = timezone.now().replace(hour=8)
    schedule = DigestSchedule.objects.create(
        owner=admin_user, report="inventory", enabled=True, hour_utc=7
    )
    DigestSchedule.objects.filter(pk=schedule.pk).update(created_at=now - timedelta(days=2))
    assert digests.dispatch(now) == 0
    SmtpProfile.objects.create(enabled=True)
    assert digests.dispatch(now) == 1
    assert digests.dispatch(now) == 0
    assert DigestDispatch.objects.count() == 1
    message = OutboxMessage.objects.get(event_type="report_digest")
    assert message.to_address == admin_user.email
    assert "schedule=" in message.body_text and "No inventory data" in message.body_text
    assert digests.can_deliver(message)
    admin_user.email = "changed@example.invalid"
    admin_user.save(update_fields=["email"])
    assert not digests.can_deliver(message)
    # The existing outbox must cancel rather than send to the former address.
    smtp = Mock()
    assert mail._send_one(smtp, SmtpProfile.objects.get(), message, now) == "cancelled"
    smtp.send_message.assert_not_called()


def test_weekly_digest_slot_and_schedule_change_cancel(admin_user, monkeypatch):
    from datetime import UTC, datetime

    monkeypatch.setattr(mail, "_kick", Mock())
    SmtpProfile.objects.create(enabled=True)
    schedule = DigestSchedule.objects.create(
        owner=admin_user, report="inventory", enabled=True, hour_utc=7, cadence="weekly", weekday=0
    )
    monday = datetime(2026, 11, 9, 8, tzinfo=UTC)
    DigestSchedule.objects.filter(pk=schedule.pk).update(created_at=monday - timedelta(days=8))
    assert digests.dispatch(monday) == 1
    assert digests.dispatch(monday + timedelta(days=6)) == 0
    assert digests.dispatch(monday + timedelta(days=7)) == 1
    message = OutboxMessage.objects.filter(event_type="report_digest").first()
    DigestSchedule.objects.filter(pk=schedule.pk).update(version=2)
    assert not digests.can_deliver(message)


def test_coverage_gap_uses_recorded_links_and_never_widens_scope(client_for, scoped, inventory, hq):
    local = inventory[0]
    instance = IntegrationInstance.objects.create(
        name="Fixture EC", source_id="endpoint_central", default_site=hq
    )
    SourceLink.objects.create(
        instance=instance,
        asset=local,
        external_id="fixture",
        method="approved_candidate",
        status="active",
        first_seen_at=timezone.now(),
        last_seen_at=timezone.now(),
    )
    client = client_for(scoped)
    result = client.get("/api/v1/reports/coverage/", {"coverage": "endpoint_central_gap"}).json()
    assert result["count"] == 1 and result["rows"][0]["name"] == "Unknown laptop"
    SourceLink.objects.filter(instance=instance).update(status="stale")
    rows = client.get("/api/v1/reports/coverage/").json()["rows"]
    assert any(row["endpoint_central"] == "Stale or disabled link" for row in rows)
