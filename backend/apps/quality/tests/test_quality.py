"""Data-quality queues (Task 011, docs/01): detection, auto-resolution, triage API."""

import pytest
from django.utils import timezone

from apps.assets.models import Asset, AssetCategory
from apps.assets.tests.fixtures import grant
from apps.audit.models import AuditEvent
from apps.quality import services
from apps.quality.models import DataQualityFinding as Finding
from apps.reconciliation.models import SourceLink
from apps.reconciliation.tests.conftest import make_instance

pytestmark = pytest.mark.django_db
URL = "/api/v1/quality/"


def kinds(asset) -> dict[str, str]:
    return dict(Finding.objects.filter(asset=asset, status="open").values_list("kind", "severity"))


@pytest.fixture
def complete(make_asset, hq, switch, admin_user):
    """An asset with nothing to report."""

    def _make(name, **extra):
        values = {
            "manufacturer": "Cisco",
            "model": "C9300-48T",
            "business_status": "in_stock",
        }
        values.update(extra)
        return make_asset(name, site=hq, category=switch, **values)

    return _make


def test_detects_each_kind(complete, admin_user, hq, make_asset):
    a = complete("sw-a", serial_number="FOC1")
    b = complete("sw-b", serial_number="foc1", manufacturer="Cisco Systems, Inc.")
    c = complete("sw-c", interfaces=[{"name": "Gi0/0", "mac_address": "02:00:00:00:00:aa"}])
    d = complete("sw-d", interfaces=[{"name": "Gi0/0", "mac_address": "02:00:00:00:00:aa"}])
    unknown = complete("sw-e", model="")
    vm = make_asset(
        "vm-1", site=hq, category=AssetCategory.objects.get(code="servers-virtual-machine")
    )
    deployed = complete("sw-f", business_status="deployed")
    assigned = complete("sw-g", business_status="assigned")
    owned = complete("sw-h", business_status="assigned", owner=admin_user)
    clean = complete("sw-i")

    counts = services.refresh()

    assert counts["opened"] == 7  # 2 serial + 2 MAC duplicates, 1 model, 2 owner
    assert kinds(a) == {"duplicate_candidate": "high"} and kinds(b) == kinds(a)
    evidence = Finding.objects.get(asset=a).evidence
    assert evidence["match"] == "manufacturer_serial" and evidence["value"] == "Cisco FOC1"
    assert evidence["assets"] == [{"id": str(b.pk), "name": "sw-b"}]
    assert kinds(c) == {"duplicate_candidate": "medium"} and kinds(d) == kinds(c)
    assert kinds(unknown) == {"model_unknown": "medium"}
    assert "model_unknown" not in kinds(vm)  # VMs are exempt
    assert kinds(deployed) == {"owner_missing": "low"}
    assert kinds(assigned) == {"owner_missing": "medium"}
    assert kinds(owned) == {} and kinds(clean) == {}


def test_source_stale_only_when_no_link_is_active(complete, hq):
    asset = complete("sw-s")
    nms = make_instance("NMS", "fixture", hq)
    now = timezone.now()
    link = SourceLink.objects.create(
        instance=nms,
        external_id="1",
        asset=asset,
        status=SourceLink.Status.STALE,
        first_seen_at=now,
        last_seen_at=now,
        method=SourceLink.Method.APPROVED_CANDIDATE,
    )
    services.refresh()
    finding = Finding.objects.get(asset=asset, kind="source_stale")
    assert finding.evidence["links"][0]["source"] == "NMS"

    link.status = SourceLink.Status.ACTIVE
    link.save()
    counts = services.refresh()

    finding.refresh_from_db()
    assert counts["resolved"] == 1 and finding.status == "resolved"
    assert finding.resolution_reason == "The condition no longer holds."


def test_fixing_the_asset_resolves_and_a_new_occurrence_reopens(complete):
    asset = complete("sw-m", model="")
    services.refresh()
    Asset.objects.filter(pk=asset.pk).update(model="C9200")
    services.refresh()
    assert Finding.objects.get(asset=asset).status == "resolved"

    Asset.objects.filter(pk=asset.pk).update(model="")
    services.refresh()
    assert Finding.objects.filter(asset=asset, status="open").count() == 1
    assert Finding.objects.filter(asset=asset).count() == 2  # history kept


def test_dismissed_finding_stays_dismissed_while_the_condition_holds(
    complete, admin_user, client_for
):
    asset = complete("lab-sw", business_status="deployed")
    services.refresh()
    finding = Finding.objects.get(asset=asset)
    client = client_for(admin_user)

    response = client.post(
        f"{URL}findings/{finding.pk}/dismiss/",
        {"reason": "Lab equipment, no owner by policy"},
        format="json",
        HTTP_IF_MATCH=f'"{finding.version}"',
    )
    assert response.status_code == 200 and response.json()["status"] == "dismissed"
    assert AuditEvent.objects.filter(action="quality.dismiss").exists()

    services.refresh()
    assert Finding.objects.get(asset=asset).status == "dismissed"
    assert client.get(f"{URL}findings/").json()["count"] == 0
    assert client.get(f"{URL}findings/", {"status": "dismissed"}).json()["count"] == 1

    reopened = client.post(
        f"{URL}findings/{finding.pk}/reopen/",
        {"reason": "Policy changed"},
        format="json",
        HTTP_IF_MATCH=f'"{response.json()["version"]}"',
    )
    assert reopened.json()["status"] == "open"


def test_assign_filters_and_summary(complete, admin_user, client_for):
    complete("sw-1", model="")
    complete("sw-2", serial_number="X1")
    complete("sw-3", serial_number="X1")
    services.refresh()
    client = client_for(admin_user)
    finding = Finding.objects.get(kind="model_unknown")

    no_version = client.post(
        f"{URL}findings/{finding.pk}/assign/", {"assignee": str(admin_user.pk)}, format="json"
    )
    assert no_version.status_code == 428
    assigned = client.post(
        f"{URL}findings/{finding.pk}/assign/",
        {"assignee": str(admin_user.pk)},
        format="json",
        HTTP_IF_MATCH=f'"{finding.version}"',
    ).json()
    assert assigned["assignee"]["username"] == admin_user.username

    assert client.get(f"{URL}findings/", {"assignee": "me"}).json()["count"] == 1
    assert client.get(f"{URL}findings/", {"kind": "duplicate_candidate"}).json()["count"] == 2
    assert client.get(f"{URL}findings/", {"severity": "high"}).json()["count"] == 2
    summary = {row["kind"]: row for row in client.get(f"{URL}summary/").json()}
    assert summary["duplicate_candidate"] == {"kind": "duplicate_candidate", "open": 2, "high": 2}
    assert summary["model_unknown"]["open"] == 1 and summary["owner_missing"]["open"] == 0


def test_site_scope_and_permissions(
    complete, client_for, make_user, hq, branch, switch, make_asset
):
    complete("hq-sw", model="")
    make_asset("br-sw", site=branch, category=switch, manufacturer="Cisco")
    services.refresh()
    analyst = grant(make_user("analyst.q", roles=["security_analyst"]), hq)
    reader = grant(make_user("reader.q", roles=["read_only"]), hq)

    rows = client_for(analyst).get(f"{URL}findings/").json()["items"]
    assert [r["asset"]["name"] for r in rows] == ["hq-sw"]
    assert client_for(reader).get(f"{URL}findings/").status_code == 403
    finding = Finding.objects.get(asset__name="hq-sw")
    denied = client_for(analyst).post(
        f"{URL}findings/{finding.pk}/dismiss/",
        {"reason": "Not allowed"},
        format="json",
        HTTP_IF_MATCH=f'"{finding.version}"',
    )
    assert denied.status_code == 403
    assert client_for(analyst).post(f"{URL}refresh/").status_code == 403


def test_refresh_endpoint_and_archived_assets(complete, admin_user, client_for):
    asset = complete("old-sw", model="")
    Asset.objects.filter(pk=asset.pk).update(archived_at=timezone.now())

    body = client_for(admin_user).post(f"{URL}refresh/").json()

    assert body == {"opened": 0, "refreshed": 0, "resolved": 0}  # archived assets ignored
