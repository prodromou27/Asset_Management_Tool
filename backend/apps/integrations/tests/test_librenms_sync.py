"""LibreNMS synchronisation against sanitized fixtures (Task 006).

Every response is served by httpx.MockTransport (conftest.FakeLibreNMS); the
connector never reaches a network in tests.
"""

import json
from datetime import timedelta

import httpx
import pytest
from django.utils import timezone

from apps.assets.models import Asset, FieldLock
from apps.integrations import sync
from apps.integrations.models import IntegrationInstance, SyncRun
from apps.network.models import NeighborEvidence
from apps.observations.models import Observation
from apps.reconciliation import services
from apps.reconciliation.models import FieldConflict, ReconciliationCandidate, SourceLink
from apps.reconciliation.tests.conftest import Req

from .conftest import TOKEN, make_librenms, run_sync

pytestmark = pytest.mark.django_db


def candidate(instance, external_id):
    return ReconciliationCandidate.objects.get(instance=instance, external_id=external_id)


def create_asset_from(instance, external_id, user, category):
    c = candidate(instance, external_id)
    services.approve_create(
        Req(user), c, {"category": category}, "Approve LibreNMS device", c.version
    )
    return SourceLink.objects.get(instance=instance, external_id=external_id).asset


# --- Full sync and vendor mapping ------------------------------------------------------------


def test_initial_sync_maps_every_vendor_into_candidates_never_assets(lnms, fake):
    run = run_sync(lnms)

    assert run.status == SyncRun.Status.SUCCEEDED and run.phase == "done"
    assert run.devices_total == 10 and run.devices_processed == 10 and run.devices_enriched == 10
    assert run.records_received == 10 and run.candidates_opened == 10
    assert Asset.objects.count() == 0  # unmatched devices go to the reconciliation queue
    expected = {
        "101": ("Cisco", "C9300-48T", "FOC0000A101", "IOS XE"),
        "102": ("Fortinet", "FGT_100F", "FGT0000000000102", "FortiOS"),
        "103": ("Aruba", "JL659A", "SG0000A103", "ArubaOS-CX"),
        "104": ("Huawei", "S5735-L48T4X-A1", "2102000104", "Huawei VRP"),
        "105": ("Check Point", "Check Point 6600", None, "Check Point Gaia"),
        "106": ("Dell EMC", "S5248F-ON", "CN0000000106", "Dell SmartFabric OS10"),
        "107": (None, None, None, "generic"),
    }
    for external_id, (vendor, model, serial, os_name) in expected.items():
        n = candidate(lnms, external_id).observation.normalized
        assert (n["manufacturer"], n["model"], n["serial_number"], n["os_name"]) == (
            vendor,
            model,
            serial,
            os_name,
        ), external_id
    assert candidate(lnms, "102").observation.normalized["category_code"] == "security-firewall"
    assert candidate(lnms, "105").observation.normalized["category_code"] == "security-firewall"
    # IP-literal hostnames are not names; the IP is kept as an address.
    unknown = candidate(lnms, "107").observation.normalized
    assert unknown["hostnames"] == [] and [r["address"] for r in unknown["ip_addresses"]] == [
        "192.0.2.107"
    ]
    # VRF context and the original source values are preserved.
    cisco = candidate(lnms, "101").observation
    assert {(r["address"], r["vrf"]) for r in cisco.normalized["ip_addresses"]} == {
        ("192.0.2.11", ""),
        ("203.0.113.11", "MGMT"),
    }
    assert cisco.payload["raw"]["device"]["sysDescr"].startswith("Cisco IOS")
    assert cisco.observed_at.isoformat() == "2026-11-02T08:00:00+00:00"
    assert cisco.instance == lnms and cisco.sync_run == run

    lnms.refresh_from_db()
    assert lnms.status == IntegrationInstance.Status.AVAILABLE and lnms.last_success_at
    assert lnms.consecutive_failures == 0 and lnms.capabilities["fdb"] is True


def test_only_get_requests_with_bearer_auth_and_no_secrets_stored(lnms, fake):
    run_sync(lnms)

    assert fake.requests and {r.method for r in fake.requests} == {"GET"}
    assert all(r.headers["Authorization"] == f"Bearer {TOKEN}" for r in fake.requests)
    assert all(r.url.path.startswith("/api/v0") for r in fake.requests)
    stored = json.dumps(list(Observation.objects.values_list("payload", flat=True)))
    assert "fake-community-not-real" not in stored and "fake-authpass" not in stored
    assert TOKEN not in stored


def test_x_auth_token_scheme_is_selectable(hq, live, fake):
    instance = make_librenms(hq, auth_scheme=IntegrationInstance.AuthScheme.X_AUTH_TOKEN)
    run_sync(instance)

    assert all(r.headers["X-Auth-Token"] == TOKEN for r in fake.requests)
    assert not any("Authorization" in r.headers for r in fake.requests)


def test_conflicting_serials_and_disabled_devices_become_warnings(lnms, fake):
    run = run_sync(lnms)

    by_device = {s["external_id"]: s["warning"] for s in run.warning_samples}
    assert "differ" in by_device["109"]  # device serial used, chassis serial disagrees
    assert "disabled" in by_device["110"]
    assert candidate(lnms, "109").observation.normalized["serial_number"] == "FDO0000A109"
    assert "placeholder" in candidate(lnms, "107").observation.normalized["warnings"][0]


def test_source_timezone_converts_naive_librenms_times(hq, live, fake):
    instance = make_librenms(hq, source_timezone="Europe/Nicosia")
    run_sync(instance)

    observed = candidate(instance, "101").observation.observed_at
    assert observed.isoformat() == "2026-11-02T06:00:00+00:00"  # EET is UTC+2 in November


# --- Idempotency and enrichment cache ------------------------------------------------------------


def test_repeated_sync_is_idempotent_and_skips_enrichment(lnms, fake):
    run_sync(lnms)
    fake.requests.clear()

    second = run_sync(lnms)

    assert second.status == SyncRun.Status.SUCCEEDED
    assert second.observations_created == 0 and second.observations_unchanged == 10
    assert second.candidates_opened == 0 and second.devices_enriched == 0
    assert fake.paths() == ["/devices"]  # one request; evidence not due yet
    assert Observation.objects.count() == 10 and ReconciliationCandidate.objects.count() == 10


def test_rediscovered_device_is_reenriched_and_ip_change_updates_asset(
    lnms, fake, admin_user, switch
):
    run_sync(lnms)
    asset = create_asset_from(lnms, "103", admin_user, switch)
    assert list(asset.ip_addresses.values_list("address", flat=True)) == ["192.0.2.13"]

    fake.device(103).update(last_discovered="2026-11-03 02:00:00", ip="192.0.2.213")
    fake.responses["/devices/103/ip"]["addresses"][0]["ipv4_address"] = "192.0.2.213"
    fake.requests.clear()
    run = run_sync(lnms)

    assert run.devices_enriched == 1
    assert "/devices/103/ip" in fake.paths() and "/devices/101/ip" not in fake.paths()
    asset.refresh_from_db()
    assert Asset.objects.count() == 1
    assert list(asset.ip_addresses.values_list("address", flat=True)) == ["192.0.2.213"]
    assert asset.history.filter(change_type="discovered").exists()


def test_old_enrichment_is_refreshed_after_max_age(lnms, fake):
    run_sync(lnms)
    lnms.enrichment_max_age_hours = 1
    lnms.save()
    with pytest.MonkeyPatch.context() as mp:
        later = timezone.now() + timedelta(hours=2)
        mp.setattr("apps.integrations.adapters.librenms.adapter.timezone.now", lambda: later)
        run = run_sync(lnms)
    assert run.devices_enriched == 10


# --- Failures, retries and partial responses ------------------------------------------------------


def test_auth_failure_fails_run_without_marking_anything_stale(lnms, fake, admin_user, switch):
    run_sync(lnms)
    create_asset_from(lnms, "101", admin_user, switch)
    fake.overrides["/devices"] = (401, {"status": "error", "message": "Unauthenticated."})

    run = run_sync(lnms)

    assert run.status == SyncRun.Status.FAILED and run.error_message.startswith(
        "SOURCE_AUTH_FAILED"
    )
    assert TOKEN not in run.error_message
    assert fake.paths().count("/devices") == 2  # auth errors are not retried
    assert SourceLink.objects.get(external_id="101").status == SourceLink.Status.ACTIVE
    lnms.refresh_from_db()
    assert lnms.status == IntegrationInstance.Status.DEGRADED and lnms.consecutive_failures == 1
    assert TOKEN not in lnms.last_error


def test_timeouts_are_retried_with_backoff_then_fail(lnms, fake):
    fake.overrides["/devices"] = httpx.ReadTimeout("timed out")

    run = run_sync(lnms)

    assert run.status == SyncRun.Status.FAILED and "SOURCE_UNAVAILABLE" in run.error_message
    assert fake.paths().count("/devices") == 3  # 1 + max_retries (2)
    backoffs = [s for s in fake.sleeps if s >= 1]
    assert len(backoffs) == 2 and backoffs[1] > backoffs[0]


def test_rate_limit_honours_retry_after(lnms, fake):
    devices = fake.responses["/devices"]
    fake.overrides["/devices"] = [
        (429, {"status": "error", "message": "Too many"}, {"Retry-After": "7"}),
        (200, devices),
    ]

    run = run_sync(lnms)

    assert run.status == SyncRun.Status.SUCCEEDED
    assert 7.0 in fake.sleeps


def test_failed_enrichment_is_a_warning_and_reuses_previous_data(lnms, fake):
    run_sync(lnms)
    fake.device(104)["last_discovered"] = "2026-11-03 02:00:00"
    fake.overrides["/devices/104/ip"] = (500, {"status": "error", "message": "boom"})

    run = run_sync(lnms)

    assert run.status == SyncRun.Status.SUCCEEDED and run.records_received == 10
    warning = next(s for s in run.warning_samples if s["external_id"] == "104")
    assert "Previous enrichment reused" in warning["warning"]
    latest = Observation.objects.filter(instance=lnms, external_id="104").latest("received_at")
    assert latest.normalized["ip_addresses"][0]["address"] == "192.0.2.14"


def test_optional_routes_missing_degrade_gracefully(lnms, fake):
    for key in [
        k for k in fake.responses[""] if k in ("list_fdb", "list_links", "get_inventory_for_device")
    ]:
        del fake.responses[""][key]

    run = run_sync(lnms)

    assert run.status == SyncRun.Status.SUCCEEDED
    assert not any(p.startswith("/inventory") or p.startswith("/resources") for p in fake.paths())
    assert any("Not collected" in s["warning"] for s in run.warning_samples)
    lnms.refresh_from_db()
    assert lnms.capabilities["inventory"] is False and lnms.capabilities["device_ip"] is True


# --- Stale devices, duplicates and identity rules ----------------------------------------


def test_device_missing_from_complete_sync_becomes_stale_never_deleted(
    lnms, fake, admin_user, switch
):
    run_sync(lnms)
    asset = create_asset_from(lnms, "103", admin_user, switch)
    fake.remove_device(103)

    run = run_sync(lnms)

    assert run.links_marked_stale == 1
    asset.refresh_from_db()
    assert asset.observation_status == "stale" and asset.archived_at is None


def test_duplicate_serial_is_never_auto_merged(lnms, fake, admin_user, switch):
    run_sync(lnms)
    asset = create_asset_from(lnms, "101", admin_user, switch)
    fake.device(108)["last_polled"] = "2026-11-03 08:00:00"
    fake.device(108)["version"] = "17.6.6"  # changed payload → re-evaluated

    run_sync(lnms)

    assert SourceLink.objects.filter(asset=asset).count() == 1
    dup = candidate(lnms, "108")
    assert dup.status == ReconciliationCandidate.Status.OPEN
    assert not SourceLink.objects.filter(instance=lnms, external_id="108").exists()


def test_hostname_or_ip_alone_never_links_even_with_auto_link(lnms, fake, make_asset, hq, switch):
    existing = make_asset("cp-gw-05", site=hq, category=switch)  # same name as device 105
    lnms.auto_link_strong_matches = True
    lnms.save()

    run_sync(lnms)

    assert not SourceLink.objects.filter(asset=existing).exists()
    assert candidate(lnms, "105").status == ReconciliationCandidate.Status.OPEN


def test_locked_fields_are_never_overwritten(lnms, fake, admin_user, switch):
    run_sync(lnms)
    asset = create_asset_from(lnms, "101", admin_user, switch)
    services.lock_field(Req(admin_user), asset, "os_version", "Pinned by change CHG-1")
    fake.device(101)["version"] = "17.12.1"

    run_sync(lnms)

    asset.refresh_from_db()
    assert asset.os_version == "17.9.4"
    assert FieldLock.objects.filter(asset=asset, field="os_version").exists()
    conflict = FieldConflict.objects.get(asset=asset, field="os_version")
    assert conflict.observed_value == "17.12.1"


def test_candidates_use_the_instance_site_for_cross_site_scope(
    branch, live, fake, client_for, hq_manager
):
    instance = make_librenms(branch, name="LibreNMS Branch")
    run_sync(instance)

    assert set(ReconciliationCandidate.objects.values_list("site", flat=True)) == {branch.pk}
    listed = client_for(hq_manager).get("/api/v1/discovery/candidates/").json()["items"]
    assert listed == []


# --- Neighbour / FDB evidence ---------------------------------------------------------------------


def test_evidence_is_stored_as_evidence_and_retired_on_complete_pass(lnms, fake):
    run = run_sync(lnms)

    assert run.evidence_rows == 5
    fdb = NeighborEvidence.objects.filter(kind="fdb")
    assert fdb.count() == 3 and set(fdb.values_list("local_port", flat=True)) == {
        "port 1003",
        "vlan10",
    }
    lldp = NeighborEvidence.objects.get(kind="lldp")
    assert (lldp.local_external_id, lldp.remote_external_id, lldp.remote_port) == (
        "101",
        "103",
        "1/1/49",
    )

    fake.responses["/resources/fdb"]["ports_fdb"] = fake.responses["/resources/fdb"]["ports_fdb"][
        :1
    ]
    IntegrationInstance.objects.filter(pk=lnms.pk).update(last_evidence_at=None)
    lnms.refresh_from_db()
    run_sync(lnms)

    assert NeighborEvidence.objects.count() == 5  # nothing deleted
    assert NeighborEvidence.objects.filter(is_active=True, kind="fdb").count() == 1


def test_evidence_not_retired_when_a_capability_is_missing(lnms, fake):
    run_sync(lnms)
    del fake.responses[""]["list_links"]
    IntegrationInstance.objects.filter(pk=lnms.pk).update(last_evidence_at=None, capabilities={})
    lnms.refresh_from_db()

    run = run_sync(lnms)

    assert NeighborEvidence.objects.filter(kind="lldp", is_active=True).exists()
    assert any("neighbour links" in s["warning"] for s in run.warning_samples)


# --- Gates, queueing and scheduling --------------------------------------------------------------


def test_live_integrations_disabled_by_default(lnms, settings):
    settings.ITAM_ALLOW_LIVE_INTEGRATIONS = False
    with pytest.raises(sync.SyncRefused) as exc:
        sync.queue_sync(lnms, mode="full", triggered_by="test")
    assert exc.value.code == "LIVE_INTEGRATIONS_DISABLED"


@pytest.mark.parametrize(
    ("changes", "code"),
    [
        ({"live_access_approved": False}, "LIVE_ACCESS_NOT_APPROVED"),
        ({"is_enabled": False}, "INTEGRATION_DISABLED"),
        ({"base_url": ""}, "NOT_CONFIGURED"),
    ],
)
def test_queue_refusals(lnms, changes, code):
    for field, value in changes.items():
        setattr(lnms, field, value)
    lnms.save()
    with pytest.raises(sync.SyncRefused) as exc:
        sync.queue_sync(lnms, mode="full", triggered_by="test")
    assert exc.value.code == code


def test_sources_without_adapter_cannot_sync(hq, live):
    from apps.integrations.models import DiscoverySource
    from apps.reconciliation.tests.conftest import make_instance

    DiscoverySource.objects.create(
        code="vcenter", name="vCenter", kind="endpoint", availability="planned"
    )
    planned = make_instance(
        "vCenter", "vcenter", hq, live_access_approved=True, base_url="https://vc.example"
    )
    with pytest.raises(sync.SyncRefused) as exc:
        sync.queue_sync(planned, mode="full", triggered_by="test")
    assert exc.value.code == "NO_ADAPTER"


def test_missing_credential_fails_run_without_revealing_anything(lnms, fake, monkeypatch):
    monkeypatch.delenv("ITAM_INTEGRATION_LNMS_TOKEN")
    run = run_sync(lnms)

    assert run.status == SyncRun.Status.FAILED and run.error_message.startswith(
        "CREDENTIAL_UNAVAILABLE"
    )
    assert fake.requests == []


def test_only_one_active_run_and_abandoned_runs_are_reclaimed(lnms, fake):
    sync.queue_sync(lnms, mode="full", triggered_by="test")
    with pytest.raises(sync.SyncRefused) as exc:
        sync.queue_sync(lnms, mode="full", triggered_by="test")
    assert exc.value.code == "SYNC_IN_PROGRESS"

    SyncRun.objects.filter(instance=lnms).update(heartbeat_at=timezone.now() - timedelta(hours=1))
    assert sync.queue_sync(lnms, mode="full", triggered_by="test").status == SyncRun.Status.QUEUED
    assert SyncRun.objects.filter(instance=lnms, status=SyncRun.Status.FAILED).count() == 1


def test_queue_hands_run_to_worker_on_commit(lnms, django_capture_on_commit_callbacks, monkeypatch):
    sent = []
    monkeypatch.setattr("apps.integrations.tasks.run_sync_task.delay", sent.append)
    with django_capture_on_commit_callbacks(execute=True):
        run = sync.queue_sync(lnms, mode="full", triggered_by="test")
    assert sent == [str(run.pk)]


def test_scheduler_queues_only_due_approved_instances(lnms, hq, monkeypatch):
    monkeypatch.setattr("apps.integrations.tasks.run_sync_task.delay", lambda run_id: None)
    make_librenms(hq, name="Not approved", live_access_approved=False)
    recent = make_librenms(hq, name="Recent", last_attempt_at=timezone.now())

    assert sync.dispatch_due() == 1
    assert SyncRun.objects.get().instance == lnms
    assert not SyncRun.objects.filter(instance=recent).exists()
    assert sync.dispatch_due() == 0  # already queued


def test_execute_ignores_runs_that_are_not_queued(lnms, fake):
    run = run_sync(lnms)
    fake.requests.clear()
    assert sync.execute(run.pk).status == SyncRun.Status.SUCCEEDED
    assert fake.requests == []
