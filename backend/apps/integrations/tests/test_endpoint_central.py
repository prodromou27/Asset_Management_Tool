"""Endpoint Central (on-premises) synchronisation against sanitized fixtures (Task 007).

Responses are served by httpx.MockTransport (conftest.FakeEndpointCentral); nothing
contacts a network.
"""

import json
from datetime import timedelta

import httpx
import pytest
from django.utils import timezone

from apps.assets.models import Asset, FieldLock
from apps.audit.models import AuditEvent
from apps.integrations import sync
from apps.integrations.adapters.endpoint_central import adapter as ec_adapter
from apps.integrations.adapters.endpoint_central.mapping import (
    computer_to_record,
    device_type,
    parse_time,
    pick,
)
from apps.integrations.models import IntegrationInstance, SyncRun
from apps.network.models import NeighborEvidence
from apps.observations.models import Observation
from apps.reconciliation import services
from apps.reconciliation.models import FieldConflict, ReconciliationCandidate, SourceLink
from apps.reconciliation.tests.conftest import Req

from .conftest import EC_TOKEN, run_sync

pytestmark = pytest.mark.django_db
LIST_14 = "/api/1.4/inventory/scancomputers"
DETAIL_14 = "/api/1.4/inventory/compdetailssummary"
LIST_DC = "/dcapi/inventory/viewData/scanComputers"


def normalized(instance, external_id):
    return ReconciliationCandidate.objects.get(
        instance=instance, external_id=external_id
    ).observation.normalized


def create_asset_from(instance, external_id, user, category):
    c = ReconciliationCandidate.objects.get(instance=instance, external_id=external_id)
    services.approve_create(Req(user), c, {"category": category}, "Approve EC computer", c.version)
    return SourceLink.objects.get(instance=instance, external_id=external_id).asset


# --- Generation detection and mapping ------------------------------------------------------


def test_initial_sync_detects_api_1_4_and_maps_computers(ec, ec_fake):
    run = run_sync(ec)

    assert run.status == SyncRun.Status.SUCCEEDED and run.records_received == 10
    assert run.candidates_opened == 10 and Asset.objects.count() == 0
    assert ec_fake.paths()[:2] == [LIST_DC, LIST_14]  # current generation probed first
    ec.refresh_from_db()
    assert ec.capabilities["route_api_1_4"] is True and ec.capabilities["route_dcapi"] is False
    assert ec.capabilities["software"] is False

    laptop = normalized(ec, "301")
    assert (laptop["manufacturer"], laptop["model"], laptop["serial_number"]) == (
        "Dell",
        "Latitude 7440",
        "7XK2Q93",
    )
    assert laptop["hardware_uuid"] == "4c4c4544-0058-4b10-8032-b7c04f513933"
    assert laptop["category_code"] == "workstations-laptop"
    assert laptop["hostnames"] == ["lt-0042.corp.example", "lt-0042"]
    assert laptop["mac_addresses"] == ["02:00:00:00:10:42", "02:00:00:00:10:43"]
    assert [r["address"] for r in laptop["ip_addresses"]] == ["192.0.2.42"]

    expected = {
        "302": ("HP", "workstations-desktop"),  # "Small Form Factor" chassis
        "303": ("Dell", "servers-physical-server"),  # Windows Server
        "304": ("VMware", "servers-virtual-machine"),
        "307": ("Apple Inc.", "workstations-laptop"),
        "310": ("Supermicro", None),  # unknown chassis: no guessed category
    }
    for external_id, (maker, category) in expected.items():
        n = normalized(ec, external_id)
        assert (n["manufacturer"], n["category_code"]) == (maker, category), external_id
    assert [r["address"] for r in normalized(ec, "303")["ip_addresses"]] == [
        "192.0.2.201",
        "203.0.113.201",
    ]
    assert normalized(ec, "307")["os_version"] == "14.5 (build 23F79)"


def test_placeholder_hardware_values_stay_unknown(ec, ec_fake):
    run = run_sync(ec)

    n = normalized(ec, "305")
    assert (n["manufacturer"], n["model"], n["serial_number"]) == (None, None, None)
    assert any(
        "placeholder" in w["warning"] for w in run.warning_samples if w["external_id"] == "305"
    )


def test_schema_drift_is_tolerated(ec, ec_fake):
    run_sync(ec)

    n = normalized(ec, "309")  # other key names, nested under "data", unknown extras
    assert (n["manufacturer"], n["model"], n["serial_number"]) == (
        "Dell",
        "OptiPlex 7010",
        "DT0000309",
    )
    assert n["category_code"] == "workstations-desktop"
    assert n["mac_addresses"] == ["02:00:00:00:12:22"]
    assert [r["address"] for r in n["ip_addresses"]] == ["192.0.2.222"]  # fe80:: dropped


def test_missing_scan_time_falls_back_to_agent_contact(ec, ec_fake):
    run = run_sync(ec)

    obs = Observation.objects.get(instance=ec, external_id="308")
    assert obs.observed_at.isoformat() == "2026-11-02T08:01:00+00:00"
    assert any(
        w["external_id"] == "308" and "agent contact" in w["warning"] for w in run.warning_samples
    )


def test_dcapi_generation_is_preferred_when_available(ec, ec_fake):
    ec_fake.families = {"dcapi", "api_1_4"}

    run = run_sync(ec)

    assert run.status == SyncRun.Status.SUCCEEDED and run.records_received == 3
    assert not any(p.startswith("/api/1.4") for p in ec_fake.paths())
    assert ec_fake.paths().count("/dcapi/inventory/computers/301/hardware") == 1
    n = normalized(ec, "301")
    assert (n["manufacturer"], n["serial_number"], n["category_code"]) == (
        "Dell",
        "7XK2Q93",
        "workstations-laptop",
    )
    assert n["mac_addresses"] == ["02:00:00:00:10:42", "02:00:00:00:10:43"]
    ec.refresh_from_db()
    assert ec.capabilities["route_dcapi"] is True


def test_no_recognised_generation_fails_with_guidance(ec, ec_fake):
    ec_fake.families = set()

    run = run_sync(ec)

    assert (
        run.status == SyncRun.Status.FAILED and "No supported Endpoint Central" in run.error_message
    )
    assert Observation.objects.count() == 0


def test_only_get_with_raw_authorization_header_and_no_software_reads(ec, ec_fake):
    run_sync(ec)

    assert {r.method for r in ec_fake.requests} == {"GET"}
    assert all(r.headers["Authorization"] == EC_TOKEN for r in ec_fake.requests)
    assert not any("software" in p.lower() for p in ec_fake.paths())
    assert not NeighborEvidence.objects.exists()  # no evidence pass for this source
    stored = json.dumps(list(Observation.objects.values_list("payload", flat=True)))
    assert EC_TOKEN not in stored and "free_memory" not in stored and "dhcp_lease" not in stored


# --- Pagination and partial responses -------------------------------------------------------


def test_pagination_reads_every_page(ec, ec_fake, monkeypatch):
    monkeypatch.setattr(ec_adapter, "PAGE_SIZE", 4)

    run = run_sync(ec)

    pages = [r.url.params.get("page") for r in ec_fake.requests if r.url.path == LIST_14][1:]
    assert pages == ["1", "2", "3"] and run.records_received == 10
    assert run.checkpoint == "page 3"


def test_failed_later_page_keeps_results_and_marks_nothing_stale(
    ec, ec_fake, monkeypatch, admin_user, laptop
):
    monkeypatch.setattr(ec_adapter, "PAGE_SIZE", 4)
    run_sync(ec)
    asset = create_asset_from(ec, "310", admin_user, laptop)  # listed on page 3
    ec_fake.overrides[f"{LIST_14}#2"] = (500, {"status": "error"})

    run = run_sync(ec)

    assert run.status == SyncRun.Status.SUCCEEDED and run.records_received == 4
    assert any("stopped at page 2" in w["warning"] for w in run.warning_samples)
    assert run.links_marked_stale == 0
    assert SourceLink.objects.get(asset=asset).status == SourceLink.Status.ACTIVE


def test_short_listing_versus_reported_total_is_incomplete(ec, ec_fake, admin_user, laptop):
    run_sync(ec)
    create_asset_from(ec, "310", admin_user, laptop)
    ec_fake.remove(310)
    ec_fake.total_override = 10  # source still claims ten computers

    run = run_sync(ec)

    assert run.links_marked_stale == 0
    assert any("Listed 9 of 10" in w["warning"] for w in run.warning_samples)


def test_computer_removed_from_complete_listing_becomes_stale(ec, ec_fake, admin_user, laptop):
    run_sync(ec)
    asset = create_asset_from(ec, "310", admin_user, laptop)
    ec_fake.remove(310)

    run = run_sync(ec)

    assert run.links_marked_stale == 1
    asset.refresh_from_db()
    assert asset.observation_status == "stale" and asset.archived_at is None


def test_detail_failure_is_a_warning_and_uses_the_list_row(ec, ec_fake):
    ec_fake.overrides[DETAIL_14] = [
        (200, {"status": "error", "error_description": "Internal failure"})
    ]

    run = run_sync(ec)

    assert run.status == SyncRun.Status.SUCCEEDED and run.records_received == 10
    n = normalized(ec, "301")
    assert n["hostnames"] == ["lt-0042.corp.example", "lt-0042"]
    assert n["mac_addresses"] == ["02:00:00:00:10:42"]  # from the list row
    assert n["serial_number"] is None
    assert any("Details not read" in w["warning"] for w in run.warning_samples)


# --- Authentication, rate limits ------------------------------------------------------------


@pytest.mark.parametrize(
    "response",
    [
        (401, {"status": "error"}),
        (200, {"status": "error", "error_code": "10002", "error_description": "Invalid API key"}),
    ],
)
def test_auth_failures_fail_without_touching_links(ec, ec_fake, admin_user, laptop, response):
    run_sync(ec)
    create_asset_from(ec, "301", admin_user, laptop)
    ec.capabilities = {}
    ec.save()
    ec_fake.overrides[LIST_DC] = response

    run = run_sync(ec)

    assert run.status == SyncRun.Status.FAILED and run.error_message.startswith(
        "SOURCE_AUTH_FAILED"
    )
    assert EC_TOKEN not in run.error_message
    assert SourceLink.objects.get(external_id="301").status == SourceLink.Status.ACTIVE
    ec.refresh_from_db()
    assert ec.status == IntegrationInstance.Status.DEGRADED


def test_rate_limit_is_retried(ec, ec_fake):
    ec_fake.overrides[f"{LIST_14}#1"] = [
        (429, {"status": "error"}, {"Retry-After": "11"}),
        (200, {"status": "success", "message_response": {"scancomputers": [], "total": 0}}),
    ]
    ec.capabilities = {"route_api_1_4": True, "route_dcapi": False}
    ec.save()

    run = run_sync(ec)

    assert run.status == SyncRun.Status.SUCCEEDED and 11.0 in ec_fake.sleeps


# --- Idempotency and change detection -----------------------------------------------------------


def test_repeated_sync_reads_only_the_list(ec, ec_fake):
    run_sync(ec)
    ec_fake.requests.clear()

    second = run_sync(ec)

    assert second.observations_created == 0 and second.observations_unchanged == 10
    assert second.devices_enriched == 0 and ec_fake.paths() == [LIST_14]


def test_newer_scan_rereads_details_and_updates_linked_asset(ec, ec_fake, admin_user, laptop):
    run_sync(ec)
    asset = create_asset_from(ec, "301", admin_user, laptop)
    ec_fake.computer(301)["last_successful_scan"] += 3_600_000
    ec_fake.details(301)["network_adapter_summary"][0]["ip_address"] = "192.0.2.142"
    ec_fake.requests.clear()

    run = run_sync(ec)

    assert run.devices_enriched == 1
    assert [r.url.params.get("resid") for r in ec_fake.requests if r.url.path == DETAIL_14] == [
        "301"
    ]
    asset.refresh_from_db()
    assert "192.0.2.142" in list(asset.ip_addresses.values_list("address", flat=True))


def test_details_refreshed_after_max_age(ec, ec_fake, monkeypatch):
    run_sync(ec)
    later = timezone.now() + timedelta(hours=30)
    monkeypatch.setattr(ec_adapter.timezone, "now", lambda: later)
    run = run_sync(ec)
    assert run.devices_enriched == 10


# --- Identity rules ------------------------------------------------------------------------


def test_same_hostname_on_two_computers_is_never_merged(ec, ec_fake, admin_user, laptop):
    run_sync(ec)
    asset = create_asset_from(ec, "301", admin_user, laptop)
    ec.auto_link_strong_matches = True
    ec.save()
    ec_fake.computer(306)["last_successful_scan"] += 1000
    ec_fake.details(306)["computer_os_summary"]["os_version"] = "10.0.26100"

    run_sync(ec)

    assert SourceLink.objects.filter(asset=asset).count() == 1
    assert not SourceLink.objects.filter(external_id="306").exists()


def test_existing_asset_with_same_serial_auto_links_only_when_enabled(
    ec, ec_fake, make_asset, hq, laptop
):
    existing = make_asset(
        "LT-0042", site=hq, category=laptop, manufacturer="Dell Inc.", serial_number="7XK2Q93"
    )
    run_sync(ec)
    assert not SourceLink.objects.filter(asset=existing).exists()
    assert ReconciliationCandidate.objects.get(external_id="301").rule == "strong"

    ec.auto_link_strong_matches = True
    ec.save()
    ec_fake.computer(301)["last_successful_scan"] += 1000
    ec_fake.details(301)["computer_os_summary"]["os_version"] = "10.0.26100"
    run_sync(ec)

    link = SourceLink.objects.get(instance=ec, external_id="301")
    assert link.asset == existing and Asset.objects.count() == 1
    assert AuditEvent.objects.filter(action="reconciliation.auto_link").exists()


def test_locked_os_version_is_not_overwritten(ec, ec_fake, admin_user, laptop):
    run_sync(ec)
    asset = create_asset_from(ec, "301", admin_user, laptop)
    services.lock_field(Req(admin_user), asset, "os_version", "Pinned for change CHG-7")
    ec_fake.computer(301)["last_successful_scan"] += 1000
    ec_fake.details(301)["computer_os_summary"].update(
        os_version="10.0.26100", build_number="26100"
    )

    run_sync(ec)

    asset.refresh_from_db()
    assert asset.os_version == "10.0.22631"
    assert FieldLock.objects.filter(asset=asset, field="os_version").exists()
    assert FieldConflict.objects.get(asset=asset, field="os_version").observed_value == "10.0.26100"


# --- Connection test and configuration API --------------------------------------------------------


def test_connection_test_reports_generation_and_version(client_for, admin_user, ec, ec_fake):
    body = client_for(admin_user).post(f"/api/v1/integrations/{ec.pk}/test/").json()

    assert body["ok"] is True and body["version"] == "11.3.2416.1"
    assert body["capabilities"]["route_api_1_4"] is True
    assert ec_fake.paths() == [LIST_DC, LIST_14, "/api/1.4/desktop/serverproperties"]


def test_auth_header_must_suit_the_source(client_for, admin_user, hq, live):
    client = client_for(admin_user)
    created = client.post(
        "/api/v1/integrations/",
        {
            "source": "endpoint_central",
            "name": "EC",
            "default_site": str(hq.pk),
            "base_url": "https://ec.corp.example:8383",
        },
        format="json",
    )
    assert created.status_code == 201 and created.json()["auth_scheme"] == "authorization"
    assert created.json()["connector"] == {
        "auth_schemes": ["authorization", "bearer"],
        "supports_evidence": False,
    }
    bad = client.patch(
        f"/api/v1/integrations/{created.json()['id']}/",
        {"auth_scheme": "x_auth_token"},
        format="json",
        HTTP_IF_MATCH=f'"{created.json()["version"]}"',
    )
    assert bad.status_code == 422 and "auth_scheme" in bad.json()["error"]["field_errors"]


def test_endpoint_central_is_beta(client_for, admin_user):
    sources = {
        s["code"]: s["availability"]
        for s in client_for(admin_user).get("/api/v1/discovery/sources/").json()
    }
    assert sources["endpoint_central"] == "beta"


def test_scheduler_includes_endpoint_central(ec, monkeypatch):
    monkeypatch.setattr("apps.integrations.tasks.run_sync_task.delay", lambda run_id: None)
    assert sync.dispatch_due() == 1 and SyncRun.objects.get().instance == ec


def test_transport_errors_are_retried_then_fail(ec, ec_fake):
    ec_fake.overrides[LIST_DC] = httpx.ConnectError("refused")

    run = run_sync(ec)

    assert run.status == SyncRun.Status.FAILED and "SOURCE_UNAVAILABLE" in run.error_message
    assert ec_fake.paths().count(LIST_DC) == 2  # 1 + max_retries (1)


# --- Mapping helpers --------------------------------------------------------------------------


def test_parse_time_variants():
    assert parse_time(1793606400000, "UTC") == "2026-11-02T08:00:00+00:00"  # epoch ms
    assert parse_time("1793606400", "UTC") == "2026-11-02T08:00:00+00:00"  # epoch s
    assert parse_time("2026-11-02 10:00:00", "Europe/Nicosia") == "2026-11-02T08:00:00+00:00"
    assert parse_time("2026-11-02T08:00:00Z", "UTC") == "2026-11-02T08:00:00+00:00"
    assert parse_time(0, "UTC") is None and parse_time("-1", "UTC") is None
    assert parse_time("garbage", "UTC") is None


def test_pick_prefers_priority_order_and_skips_empty_values():
    docs = [{"a": {"model": "--", "device_model": "X1"}}, {"system_model": "Y2"}]
    assert pick(docs, ("device_model", "system_model", "model")) == ("device_model", "X1")
    assert pick([{"Serial-Number": " S1 "}], ("serial_number",)) == ("Serial-Number", "S1")


def test_device_type_rules():
    assert device_type("Notebook", "Windows 11", "Dell", "Latitude") == "laptop"
    assert device_type("Rack Mount Chassis", "Ubuntu", "Dell", "PowerEdge") is None
    assert device_type(None, "Windows Server 2022", "HP", "ProLiant") == "server"
    assert device_type("Desktop", "Windows 11", "VMware, Inc.", "VMware7,1") == "virtual_machine"


def test_record_without_any_time_uses_fetch_time():
    record, warnings = computer_to_record(
        {"resource_id": 9, "resource_name": "x1"},
        [],
        tz_name="UTC",
        fetched_at="2026-11-03T00:00:00+00:00",
        enriched_at=None,
    )
    assert record["observed_at"] == "2026-11-03T00:00:00+00:00" and warnings
    assert record["external_id"] == "9" and record["hostnames"] == ["x1"]
