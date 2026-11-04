"""Software inventory: connector reads, storage rules, scope, manual entries, lifecycle
per version and exports (Task 016a, ASM-54). Fixtures are fictitious; no network."""

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.assets.models import Asset
from apps.audit.models import AuditEvent
from apps.integrations.models import SyncRun
from apps.integrations.tests.conftest import run_sync
from apps.lifecycle.models import LifecycleAlias
from apps.reconciliation.models import SourceLink
from apps.software import services
from apps.software.models import SoftwareInstallation, SoftwareProduct, SoftwareVersion

pytestmark = pytest.mark.django_db
SW = "/dcapi/inventory/computers/{}/softwareInfo"


def link(instance, external_id, asset, status="active"):
    now = timezone.now()
    return SourceLink.objects.create(
        instance=instance,
        external_id=external_id,
        asset=asset,
        status=status,
        method="approved_candidate",
        first_seen_at=now,
        last_seen_at=now,
    )


def names(instance, external_id, removed=False):
    rows = SoftwareInstallation.objects.filter(
        instance=instance, external_id=external_id, removed_at__isnull=not removed
    )
    return sorted(f"{r.version.product.name} {r.version.version}".strip() for r in rows)


@pytest.fixture
def ec_dcapi(ec, ec_fake):
    ec_fake.families = {"dcapi"}
    ec.collect_software = True
    ec.save(update_fields=["collect_software"])
    return ec


# --- Endpoint Central ------------------------------------------------------------------------


def test_endpoint_central_reads_software_once_per_refresh(ec_dcapi, ec_fake):
    run = run_sync(ec_dcapi)

    assert run.status == SyncRun.Status.SUCCEEDED
    assert names(ec_dcapi, "301") == [
        "7-Zip 24.08 (x64) 24.08",
        "Example Browser 130.0.6723.92",  # listed twice, stored once
        "Example Office Suite 16.0.17928.20156",
    ]
    assert names(ec_dcapi, "302") == ["Example Office Suite 16.0.17928.20156", "Legacy Viewer 5.1"]
    assert any("software route not available" in w["warning"] for w in run.warning_samples)
    office = SoftwareInstallation.objects.get(
        instance=ec_dcapi, external_id="301", version__product__name="Example Office Suite"
    )
    assert (office.raw_publisher, office.source_ref) == ("Example Software Corp", "9001")
    assert str(office.installed_on) == "2026-09-21"
    assert SoftwareProduct.objects.filter(name="Example Office Suite").count() == 1
    for device in ("301", "302", "303"):
        assert ec_fake.paths().count(SW.format(device)) == 1

    ec_fake.requests.clear()
    run_sync(ec_dcapi)  # no newer scan: stored software is kept, not re-read
    assert ec_fake.paths().count(SW.format("301")) == 0
    assert ec_fake.paths().count(SW.format("303")) == 1  # nothing stored yet for 303
    assert len(names(ec_dcapi, "301")) == 3


def test_software_no_longer_reported_is_marked_removed(ec_dcapi, ec_fake):
    run_sync(ec_dcapi)
    doc = ec_fake.dc["details"]["301"]["softwareInfo"]
    doc["data"] = [r for r in doc["data"] if r["softwareId"] != 9002]
    ec_fake.dc["computers"][0]["lastSuccessfulScan"] += 3600_000  # newer scan

    run_sync(ec_dcapi)

    assert names(ec_dcapi, "301", removed=True) == ["7-Zip 24.08 (x64) 24.08"]
    removed = SoftwareInstallation.objects.get(
        instance=ec_dcapi, external_id="301", removed_at__isnull=False
    )
    assert removed.removed_reason == "No longer reported by the source"
    assert len(names(ec_dcapi, "301")) == 2


def test_failed_software_read_removes_nothing(ec_dcapi, ec_fake):
    run_sync(ec_dcapi)
    ec_fake.dc["computers"][0]["lastSuccessfulScan"] += 3600_000
    ec_fake.overrides[SW.format("301")] = (500, {"status": "error"})

    run = run_sync(ec_dcapi)

    assert run.status == SyncRun.Status.SUCCEEDED
    assert any("Installed software not read" in w["warning"] for w in run.warning_samples)
    assert len(names(ec_dcapi, "301")) == 3 and not names(ec_dcapi, "301", removed=True)


def test_software_needs_dcapi_and_the_switch(ec, ec_fake):
    run_sync(ec)  # api 1.4, switch off
    assert not any("software" in p.lower() for p in ec_fake.paths())

    ec.collect_software = True
    ec.save(update_fields=["collect_software"])
    run = run_sync(ec)
    assert any("needs the dcapi" in w["warning"] for w in run.warning_samples)
    assert not SoftwareInstallation.objects.exists()


# --- Intune ---------------------------------------------------------------------------------


@pytest.fixture
def intune_sw(intune):
    intune.collect_software = True
    intune.save(update_fields=["collect_software"])
    return intune


def test_intune_reads_detected_apps_per_app(intune_sw, graph):
    first, second = graph.devices[0]["id"], graph.devices[1]["id"]

    run = run_sync(intune_sw)

    assert run.status == SyncRun.Status.SUCCEEDED
    assert names(intune_sw, first) == [
        "Example Browser 130.0.6723.92",
        "Example Office Suite 16.0.17928.20156",
    ]
    assert names(intune_sw, second) == ["Example Office Suite 16.0.17928.20156"]
    assert not SoftwareInstallation.objects.filter(external_id__startswith="ffffffff").exists()
    paths = graph.app_paths()
    assert paths.count("/v1.0/deviceManagement/detectedApps") == 2  # two pages
    assert not any("app-0003-unused" in p for p in paths)  # deviceCount 0: not read
    assert len(paths) == 2 + 3


def test_intune_without_switch_makes_no_app_requests(intune, graph):
    run_sync(intune)
    assert graph.app_requests == []


def test_intune_complete_read_marks_removed_and_partial_read_does_not(intune_sw, graph):
    first = graph.devices[0]["id"]
    run_sync(intune_sw)
    graph.app_devices["app-0002-example-browser"] = []

    run_sync(intune_sw)
    assert names(intune_sw, first, removed=True) == ["Example Browser 130.0.6723.92"]

    graph.app_devices["app-0002-example-browser"] = [first]
    run_sync(intune_sw)
    assert names(intune_sw, first, removed=True) == []  # reported again: restored

    graph.app_devices["app-0001-example-office"] = []
    graph.overrides["app:app-0002-example-browser"] = (
        503,
        {"error": {"code": "ServiceUnavailable"}},
    )
    run = run_sync(intune_sw)
    assert any("Devices of Example Browser" in w["warning"] for w in run.warning_samples)
    assert "Example Office Suite 16.0.17928.20156" in names(intune_sw, first)  # nothing removed


# --- API, scope and manual entries -----------------------------------------------------------


@pytest.fixture
def linked(ec_dcapi, hq, branch, switch, make_asset):
    run_sync(ec_dcapi)
    hq_asset = make_asset("lt-0042", site=hq, category=switch)
    branch_asset = make_asset("dt-0107", site=branch, category=switch)
    link(ec_dcapi, "301", hq_asset)
    link(ec_dcapi, "302", branch_asset)
    return {"hq": hq_asset, "branch": branch_asset}


def test_products_and_installations_are_site_scoped(linked, hq_reader, admin_user, client_for):
    reader = client_for(hq_reader)
    products = {p["name"]: p for p in reader.get("/api/v1/software/products/").json()["items"]}
    assert products["Example Office Suite"]["installations"] == 1  # the branch copy is hidden
    assert "Legacy Viewer" not in products  # only installed in the branch

    admin = {
        p["name"]: p
        for p in client_for(admin_user).get("/api/v1/software/products/").json()["items"]
    }
    assert admin["Example Office Suite"]["installations"] == 2

    rows = reader.get("/api/v1/software/installations/", {"q": "office"}).json()["items"]
    assert [(r["asset"]["name"], r["source"]) for r in rows] == [("lt-0042", "Endpoint Central")]
    assert reader.get(f"/api/v1/assets/{linked['branch'].pk}/software/").status_code == 404

    detail = reader.get(
        f"/api/v1/software/products/{products['Example Office Suite']['id']}/"
    ).json()
    assert [(v["version"], v["installations"]) for v in detail["versions"]] == [
        ("16.0.17928.20156", 1)
    ]


def test_unlinking_moves_software_off_the_asset(linked, client_for, admin_user):
    client = client_for(admin_user)
    url = f"/api/v1/assets/{linked['hq'].pk}/software/"
    assert len(client.get(url).json()) == 3
    SourceLink.objects.filter(asset=linked["hq"]).update(status="unlinked")
    assert client.get(url).json() == []
    assert SoftwareInstallation.objects.filter(external_id="301").count() == 3  # nothing deleted


def test_manual_entries(linked, hq_operator, hq_reader, client_for):
    operator = client_for(hq_operator)
    url = f"/api/v1/assets/{linked['hq'].pk}/software/"
    body = {"name": "Example CAD", "publisher": "Example Design", "version": "2025.1"}
    created = operator.post(url, body, format="json")
    assert created.status_code == 201 and created.json()["source"] == "Manual"
    assert operator.post(url, body, format="json").status_code == 409
    assert client_for(hq_reader).post(url, body, format="json").status_code == 403

    discovered = next(r for r in operator.get(url).json() if r["source"] != "Manual")
    response = operator.post(
        f"/api/v1/software/installations/{discovered['id']}/remove/",
        {"reason": "Not here"},
        format="json",
    )
    assert response.status_code == 404  # discovered rows are not removable by hand

    response = operator.post(
        f"/api/v1/software/installations/{created.json()['id']}/remove/",
        {"reason": "Licence returned"},
        format="json",
    )
    assert response.status_code == 200 and response.json()["removed_at"]
    actions = set(
        AuditEvent.objects.filter(object_id=str(linked["hq"].pk)).values_list("action", flat=True)
    )
    assert {"software.manual.add", "software.manual.remove"} <= actions


def test_store_rules_without_a_connector(ec, hq):
    now = timezone.now()
    items = {
        "D1": [{"name": "Tool", "version": "1"}, {"name": "  "}, {"name": "tool", "version": "1"}]
    }
    counts = services.store_installations(ec, items, complete={"D1"}, now=now)
    assert counts == {"added": 1, "seen": 0, "removed": 0, "restored": 0}
    counts = services.store_installations(
        ec, {"D1": []}, complete=set(), now=now + timedelta(hours=1)
    )
    assert counts["removed"] == 0  # incomplete: kept
    counts = services.store_installations(
        ec, {"D1": []}, complete={"D1"}, now=now + timedelta(hours=2)
    )
    assert counts["removed"] == 1


# --- Lifecycle per version --------------------------------------------------------------------


def test_software_lifecycle_review_and_assessment(
    linked, client_for, admin_user, django_capture_on_commit_callbacks
):
    client = client_for(admin_user)

    def run(fn, *args, **kwargs):
        with django_capture_on_commit_callbacks(execute=True):
            return fn(*args, **kwargs)

    before = Asset.objects.get(pk=linked["hq"].pk).support_status
    product = run(
        client.post,
        "/api/v1/lifecycle/products/",
        {
            "kind": "software",
            "vendor": "Example Software Corp",
            "name": "Example Office Suite",
            "release": "16.0",
        },
        format="json",
    ).json()
    version = SoftwareVersion.objects.get(product__name="Example Office Suite")
    assert (version.lifecycle_state, version.lifecycle_status) == ("candidate", "unverified")

    response = client.post(
        f"/api/v1/software/versions/{version.pk}/lifecycle/approve/",
        {"product": product["id"], "remember_alias": True, "note": "Build of 16.0"},
        format="json",
        HTTP_IF_MATCH=f'"{version.lifecycle_version}"',
    )
    assert response.status_code == 200, response.json()
    assert (response.json()["lifecycle_state"], response.json()["lifecycle_method"]) == (
        "matched",
        "manual",
    )
    assert LifecycleAlias.objects.filter(
        product_id=product["id"], release="16.0.17928.20156"
    ).exists()
    stale = client.post(
        f"/api/v1/software/versions/{version.pk}/lifecycle/approve/",
        {"product": product["id"]},
        format="json",
        HTTP_IF_MATCH=f'"{version.lifecycle_version}"',
    )
    assert stale.status_code == 409

    source = client.post(
        "/api/v1/lifecycle/sources/",
        {
            "publisher": "Example Software Corp",
            "title": "Lifecycle page (fictitious)",
            "source_type": "vendor",
            "collected_on": "2026-10-01",
        },
        format="json",
    ).json()
    detail = run(
        client.post,
        f"/api/v1/lifecycle/products/{product['id']}/milestones/",
        {"milestone_type": "end_of_support", "date": "2025-10-14", "source": source["id"]},
        format="json",
    ).json()
    milestone = detail["milestones"][0]
    run(
        client.post,
        f"/api/v1/lifecycle/milestones/{milestone['id']}/review/",
        {"decision": "verified"},
        format="json",
        HTTP_IF_MATCH=f'"{milestone["version"]}"',
    )
    version.refresh_from_db()
    assert version.lifecycle_status == "eos"
    listed = {p["name"]: p for p in client.get("/api/v1/software/products/").json()["items"]}
    assert listed["Example Office Suite"]["eos_versions"] == 1
    rows = client.get("/api/v1/software/installations/", {"lifecycle_status": "eos"}).json()[
        "items"
    ]
    assert {r["asset"]["name"] for r in rows} == {"lt-0042", "dt-0107"}
    assert Asset.objects.get(pk=linked["hq"].pk).support_status == before  # software stays separate
    assert AuditEvent.objects.filter(action="software.lifecycle.approve").exists()


def test_rejecting_a_software_suggestion(
    linked, client_for, admin_user, django_capture_on_commit_callbacks
):
    client = client_for(admin_user)
    with django_capture_on_commit_callbacks(execute=True):
        client.post(
            "/api/v1/lifecycle/products/",
            {
                "kind": "software",
                "vendor": "Example Software Corp",
                "name": "Example Office Suite",
                "release": "16.0",
            },
            format="json",
        )
    version = SoftwareVersion.objects.get(product__name="Example Office Suite")
    response = client.post(
        f"/api/v1/software/versions/{version.pk}/lifecycle/reject/",
        {"note": "Different edition"},
        format="json",
        HTTP_IF_MATCH=f'"{version.lifecycle_version}"',
    )
    assert response.status_code == 200
    assert (response.json()["lifecycle_state"], response.json()["lifecycle_status"]) == (
        "no_match",
        "unknown",
    )


def test_lifecycle_approval_needs_permission(linked, hq_operator, client_for):
    version = SoftwareVersion.objects.first()
    response = client_for(hq_operator).post(
        f"/api/v1/software/versions/{version.pk}/lifecycle/reject/",
        {"note": "nope nope"},
        format="json",
    )
    assert response.status_code == 403


# --- Export -----------------------------------------------------------------------------------


def test_installed_software_in_asset_export(
    linked, client_for, admin_user, django_capture_on_commit_callbacks
):
    import json

    client = client_for(admin_user)
    with django_capture_on_commit_callbacks(execute=True):
        job = client.post(
            "/api/v1/exports/",
            {"family": "assets", "format": "json", "scope": "all", "related": ["software"]},
            format="json",
        ).json()
    document = json.loads(client.get(f"/api/v1/exports/{job['id']}/download/").content)
    item = next(i for i in document["items"] if i["name"] == "lt-0042")
    assert sorted(s["product"] for s in item["software"]) == [
        "7-Zip 24.08 (x64)",
        "Example Browser",
        "Example Office Suite",
    ]
    assert {s["source"] for s in item["software"]} == {"Endpoint Central"}
