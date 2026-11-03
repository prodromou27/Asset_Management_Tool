"""Microsoft Defender for Endpoint synchronisation against sanitized fixtures (Task 009).

The Entra token endpoint and the Defender API are served by httpx.MockTransport
(conftest.FakeDefender); nothing contacts a network. The fake rejects any non-GET API
request, any token request for another audience than the Defender API, and any request
to a host other than api.security.microsoft.com / login.microsoftonline.com.
"""

import json
import logging
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from django.utils import timezone

from apps.assets.models import Asset, AssetCategory, FieldLock
from apps.assets.tests.fixtures import grant
from apps.integrations import sync
from apps.integrations.adapters.defender import adapter as defender_adapter
from apps.integrations.adapters.defender import client as defender_client
from apps.integrations.adapters.defender.mapping import machine_to_record, parse_time
from apps.integrations.models import IntegrationInstance, SyncRun
from apps.observations.models import Observation
from apps.reconciliation import services
from apps.reconciliation.models import FieldConflict, ReconciliationCandidate, SourceLink
from apps.reconciliation.tests.conftest import Req
from apps.security.models import EndpointSecurityState

from .conftest import (
    INTUNE_SECRET,
    MACHINE_ROLE,
    certificate_pem,
    make_defender,
    make_intune,
    run_sync,
)

pytestmark = pytest.mark.django_db


def mid(n: int) -> str:
    return f"1e5c3b2a0d9f8e7c6b5a4f3e2d1c0b9a8f7e6d{n:02d}"


def intune_id(n: int) -> str:
    return f"a1{n:06d}-0000-4000-8000-{n:012d}"


def candidate(instance, external_id):
    return ReconciliationCandidate.objects.get(
        instance=instance, external_id=external_id, status__in=["open", "held"]
    )


def latest(instance, external_id) -> Observation:
    return (
        Observation.objects.filter(instance=instance, external_id=external_id)
        .order_by("-received_at")
        .first()
    )


def create_asset_from(instance, external_id, user, category):
    c = candidate(instance, external_id)
    services.approve_create(Req(user), c, {"category": category}, "Approve device", c.version)
    return SourceLink.objects.get(instance=instance, external_id=external_id).asset


def state(n: int) -> EndpointSecurityState:
    return EndpointSecurityState.objects.get(external_id=mid(n))


@pytest.fixture
def server_category(db):
    return AssetCategory.objects.get(code="servers-physical-server")


@pytest.fixture
def desktop(db):
    return AssetCategory.objects.get(code="workstations-desktop")


@pytest.fixture
def small_pages(monkeypatch):
    monkeypatch.setattr(defender_adapter, "PAGE_SIZE", 4)


@pytest.fixture
def both(hq, live, graph, defender_api, settings, tmp_path, monkeypatch):
    """Intune and Defender for the same tenant, each served by its own fake."""
    (tmp_path / "defender-app.pem").write_text(certificate_pem(), encoding="utf-8")
    settings.ITAM_SECRETS_DIR = str(tmp_path)
    monkeypatch.setenv("ITAM_INTEGRATION_INTUNE_SECRET", INTUNE_SECRET)
    monkeypatch.setattr(
        sync,
        "TRANSPORT_FACTORY",
        lambda inst: httpx.MockTransport(
            graph.handler if inst.source_id == "intune" else defender_api.handler
        ),
    )
    assert graph.tenant_id == defender_api.tenant_id
    intune = make_intune(hq, graph)
    defender = make_defender(hq, defender_api, auto_link_strong_matches=True)
    return intune, defender


# --- Full synchronisation, pagination and mapping ------------------------------------------


def test_initial_full_sync_uses_the_defender_audience_and_certificate(defender, defender_api):
    run = run_sync(defender)

    assert run.status == SyncRun.Status.SUCCEEDED and run.records_received == 10
    assert run.candidates_opened == 10 and Asset.objects.count() == 0
    (form,) = defender_api.token_forms
    assert form["scope"] == "https://api.securitycenter.microsoft.com/.default"
    assert "client_secret" not in form and form["client_assertion"].count(".") == 2
    (request,) = defender_api.requests
    assert request.url.params["$top"] == "1000" and "$filter" not in request.url.params
    assert run.api_requests == 2
    defender.refresh_from_db()
    assert defender.status == IntegrationInstance.Status.AVAILABLE and defender.last_success_at


def test_skip_pagination(defender, defender_api, small_pages):
    run = run_sync(defender)

    assert run.records_received == 10 and defender_api.pages() == [1, 2, 3]
    assert [r.url.params.get("$skip") for r in defender_api.requests] == [None, "4", "8"]
    assert run.checkpoint == "page 3, 10 machines"


def test_next_link_pagination(defender, defender_api, small_pages):
    defender_api.use_next_link = True

    run = run_sync(defender)

    assert run.records_received == 10 and defender_api.pages() == [1, 2, 3]


def test_empty_response(defender, defender_api):
    defender_api.machines.clear()

    run = run_sync(defender)

    assert run.status == SyncRun.Status.SUCCEEDED and run.records_received == 0
    assert not ReconciliationCandidate.objects.exists()
    assert not EndpointSecurityState.objects.exists()


def test_mapping_keeps_original_values_and_tenant_scope(defender, defender_api):
    run_sync(defender)

    obs = latest(defender, mid(1))
    n, raw = obs.normalized, obs.payload["raw"]
    assert n["observed_at"] == "2026-11-02T07:41:12.123456+00:00"  # lastSeen
    assert n["hostnames"] == ["lt-0042.corp.example"]
    assert n["entra_device_id"] == "e1000001-0000-4000-8000-000000000001"
    assert n["mac_addresses"] == ["02:00:00:00:10:42"]
    assert [ip["address"] for ip in n["ip_addresses"]] == ["192.0.2.42"]  # no fe80/loopback
    assert (n["os_name"], n["os_version"]) == ("Windows11", "10.0 (build 22631)")
    assert n["manufacturer"] is None and n["serial_number"] is None  # not reported
    assert raw["tenant_id"] == defender_api.tenant_id and raw["machine_id"] == mid(1)
    assert raw["fields"]["healthStatus"] == "Active" and raw["fields"]["machineTags"] == [
        "Finance",
        "VIP",
    ]
    for volatile in ("lastSeen", "lastIpAddress", "lastExternalIpAddress"):
        assert volatile not in raw["fields"]
    assert obs.payload["_meta"]["last_seen"] == n["observed_at"]


def test_security_facts_are_stored_apart_from_asset_fields(defender, defender_api):
    run = run_sync(defender)

    s = state(1)
    assert (s.onboarding_status, s.health_status) == ("Onboarded", "Active")
    assert (s.exposure_level, s.risk_score) == ("Medium", "Low")
    assert s.device_tags == ["Finance", "VIP"] and s.machine_group == "Workstations"
    assert s.tenant_id == defender_api.tenant_id
    assert s.entra_device_id == "e1000001-0000-4000-8000-000000000001"
    assert s.last_seen_at.isoformat() == "2026-11-02T07:41:12.123456+00:00"
    assert s.first_seen_at.isoformat() == "2026-01-15T09:30:00+00:00"
    assert s.original["riskScore"] == "Low" and s.last_run_id == run.pk
    assert s.observation_id == latest(defender, mid(1)).pk
    assert EndpointSecurityState.objects.count() == 10
    assert not hasattr(Asset, "risk_score") and not hasattr(Asset, "health_status")


def test_category_hints_and_missing_identifiers(defender, defender_api):
    run = run_sync(defender)

    codes = {n: latest(defender, mid(n)).normalized["category_code"] for n in (1, 3, 6)}
    assert codes == {1: None, 3: "servers-physical-server", 6: "servers-virtual-machine"}
    assert latest(defender, mid(3)).normalized["entra_device_id"] is None  # not reported
    assert latest(defender, mid(10)).normalized["entra_device_id"] is None  # zero GUID
    assert "someFutureProperty" not in json.dumps(latest(defender, mid(10)).payload)
    assert any(
        s["external_id"] == mid(9) and "first seen" in s["warning"] for s in run.warning_samples
    )


def test_repeat_sync_is_idempotent_and_last_seen_alone_is_not_a_change(defender, defender_api):
    run_sync(defender)
    before = state(1).changed_at
    defender_api.machine(1)["lastSeen"] = "2026-11-03T07:00:00Z"

    second = run_sync(defender)

    assert second.observations_created == 0 and second.observations_unchanged == 10
    assert second.candidates_opened == 0 and second.candidates_updated == 0
    s = state(1)
    assert s.last_seen_at.isoformat() == "2026-11-03T07:00:00+00:00" and s.changed_at == before


def test_onboarding_and_sensor_health_changes_are_recorded(defender, defender_api):
    run_sync(defender)
    before = state(2).changed_at
    defender_api.machine(2)["healthStatus"] = "Active"
    defender_api.machine(8)["onboardingStatus"] = "Onboarded"

    run = run_sync(defender)

    assert run.observations_created == 2
    assert state(2).health_status == "Active" and state(2).changed_at > before
    assert state(8).onboarding_status == "Onboarded"
    assert latest(defender, mid(2)).payload["raw"]["fields"]["healthStatus"] == "Active"


# --- Reconciliation -------------------------------------------------------------------------


def test_duplicate_dns_names_are_never_merged(defender, defender_api, admin_user, desktop):
    run_sync(defender)
    asset = create_asset_from(defender, mid(4), admin_user, desktop)
    defender.auto_link_strong_matches = True
    defender.save()
    defender_api.machine(5)["machineTags"] = ["Kiosk", "Lobby"]

    run_sync(defender)

    assert SourceLink.objects.filter(asset=asset).count() == 1
    other = candidate(defender, mid(5))
    assert other.proposed_asset_id == asset.pk and other.rule == "weak"
    assert not SourceLink.objects.filter(external_id=mid(5)).exists()


def test_entra_device_id_links_across_sources_with_corroboration(
    both, graph, defender_api, admin_user, laptop, client_for
):
    intune, defender = both
    run_sync(intune)
    asset = create_asset_from(intune, intune_id(1), admin_user, laptop)

    run = run_sync(defender)

    assert run.status == SyncRun.Status.SUCCEEDED
    link = SourceLink.objects.get(instance=defender, external_id=mid(1))
    assert link.asset == asset and link.method == "auto_strong_match"
    assert Asset.objects.count() == 1
    # Field authority: Intune outranks Defender for the OS version.
    asset.refresh_from_db()
    assert asset.os_version == "10.0.22631.4460"
    rows = client_for(admin_user).get(f"/api/v1/assets/{asset.pk}/security/").json()
    assert [r["external_id"] for r in rows] == [mid(1)]
    assert rows[0]["health_status"] == "Active" and rows[0]["link_status"] == "active"


def test_entra_device_id_without_corroboration_needs_review(
    both, graph, defender_api, admin_user, laptop
):
    intune, defender = both
    run_sync(intune)
    asset = create_asset_from(intune, intune_id(4), admin_user, laptop)  # MBP-0012
    defender_api.machine(9)["computerDnsName"] = "renamed-mac.corp.example"

    run_sync(defender)

    c = candidate(defender, mid(9))
    assert c.rule == "strong" and c.proposed_asset_id == asset.pk
    assert [k["key"] for k in c.matches[0]["keys"]] == ["entra_device_id"]
    assert not SourceLink.objects.filter(instance=defender, external_id=mid(9)).exists()


def test_entra_device_id_from_another_tenant_is_not_evidence(
    both, graph, defender_api, admin_user, laptop
):
    intune, defender = both
    defender.tenant_id = "contoso.onmicrosoft.com"
    defender.save()
    run_sync(intune)
    create_asset_from(intune, intune_id(4), admin_user, laptop)
    defender_api.machine(9)["computerDnsName"] = "renamed-mac.corp.example"
    defender_api.tenant_id = "contoso.onmicrosoft.com"

    run_sync(defender)

    c = candidate(defender, mid(9))
    assert c.rule == "new_device" and c.matches == []


def test_changed_entra_device_id_pointing_at_another_asset_is_a_conflict(
    both, graph, defender_api, admin_user, laptop, desktop
):
    intune, defender = both
    run_sync(intune)
    lt = create_asset_from(intune, intune_id(1), admin_user, laptop)
    dt = create_asset_from(intune, intune_id(2), admin_user, desktop)
    run_sync(defender)
    assert SourceLink.objects.get(instance=defender, external_id=mid(1)).asset == lt
    defender_api.machine(1)["aadDeviceId"] = "e1000002-0000-4000-8000-000000000002"

    run_sync(defender)

    flagged = candidate(defender, mid(1))
    assert flagged.rule == "conflict" and "duplicate" in flagged.conflicts[0]
    assert str(dt.pk) in {m["asset_id"] for m in flagged.matches}
    assert SourceLink.objects.get(instance=defender, external_id=mid(1)).asset == lt


def test_conflicting_entra_device_id_on_a_hostname_match_is_a_conflict(
    both, graph, defender_api, admin_user, laptop
):
    intune, defender = both
    run_sync(intune)
    lt = create_asset_from(intune, intune_id(1), admin_user, laptop)
    other = create_asset_from(intune, intune_id(3), admin_user, laptop)  # LT-0077
    # d01 keeps LT-0042's Entra ID but now also shares LT-0077's name and Wi-Fi MAC.
    defender_api.machine(1)["computerDnsName"] = "lt-0077.corp.example"
    defender_api.machine(1)["ipAddresses"][0]["macAddress"] = "020000001077"

    run_sync(defender)

    c = candidate(defender, mid(1))
    assert c.rule == "conflict" and c.proposed_asset_id == lt.pk
    assert any("several identifiers" in text for text in c.conflicts)
    assert str(other.pk) in {m["asset_id"] for m in c.matches}
    assert not SourceLink.objects.filter(instance=defender).exists()


def test_locked_fields_are_never_overwritten(defender, defender_api, admin_user, server_category):
    run_sync(defender)
    asset = create_asset_from(defender, mid(3), admin_user, server_category)
    services.lock_field(Req(admin_user), asset, "os_version", "Pinned for CHG-31")
    defender_api.machine(3)["osBuild"] = 20349

    run_sync(defender)

    asset.refresh_from_db()
    assert asset.os_version == "10.0 (build 20348)"
    assert FieldLock.objects.filter(asset=asset, field="os_version").exists()
    assert FieldConflict.objects.get(asset=asset, field="os_version").observed_value == (
        "10.0 (build 20349)"
    )


# --- Freshness and partial enumeration -------------------------------------------------------


def test_machine_missing_from_a_complete_listing(
    defender, defender_api, admin_user, server_category
):
    run_sync(defender)
    asset = create_asset_from(defender, mid(3), admin_user, server_category)
    defender_api.remove(3)

    run = run_sync(defender)

    assert run.links_marked_stale == 1
    assert SourceLink.objects.get(external_id=mid(3)).status == SourceLink.Status.STALE
    assert state(3).missing_since is not None  # kept, flagged, never deleted
    assert Asset.objects.filter(pk=asset.pk, archived_at__isnull=True).exists()


def test_partial_enumeration_marks_nothing_stale_or_missing(
    defender, defender_api, admin_user, server_category, small_pages
):
    run_sync(defender)
    create_asset_from(defender, mid(10), admin_user, server_category)  # on page 3
    defender_api.overrides["page3"] = (503, {"error": {"code": "ServiceUnavailable"}})

    run = run_sync(defender)

    assert run.records_received == 8 and run.links_marked_stale == 0
    assert SourceLink.objects.get(external_id=mid(10)).status == SourceLink.Status.ACTIVE
    assert state(10).missing_since is None
    assert any("stopped after page 2" in s["warning"] for s in run.warning_samples)


@pytest.mark.parametrize(
    "next_base",
    [
        "https://api.securitycenter.example/api/machines",
        "http://api.security.microsoft.com/api/machines",
        "https://api.security.microsoft.com/api/machines/actions",
        "https://graph.microsoft.com/v1.0/deviceManagement/managedDevices",
    ],
    ids=["other-host", "http", "other-path", "graph"],
)
def test_unsafe_continuation_links_are_not_followed(defender, defender_api, small_pages, next_base):
    defender_api.use_next_link = True
    defender_api.next_link_base = next_base

    run = run_sync(defender)

    assert defender_api.pages() == [1] and run.records_received == 4
    assert any("not followed" in s["warning"] for s in run.warning_samples)
    assert not EndpointSecurityState.objects.filter(missing_since__isnull=False).exists()


def test_hourly_request_budget_stops_the_listing(defender, defender_api, small_pages, monkeypatch):
    monkeypatch.setattr(defender_client, "HOURLY_BUDGET", 2)

    run = run_sync(defender)

    assert defender_api.pages() == [1, 2] and run.records_received == 8
    assert any("hourly limit" in s["warning"] for s in run.warning_samples)


def test_request_rate_never_exceeds_the_published_limit(defender):
    defender.requests_per_second = 20
    defender.save()

    with sync.build_client(defender) as client:
        assert client.min_interval == pytest.approx(0.6)


def test_incremental_sync_filters_on_last_seen(defender, defender_api):
    defender.last_success_at = datetime(2026, 11, 2, 7, 0, tzinfo=UTC)
    defender.save()

    run = sync.execute(sync.queue_sync(defender, mode="incremental", triggered_by="test").pk)

    (request,) = defender_api.requests
    assert request.url.params["$filter"] == "lastSeen gt 2026-11-02T06:00:00Z"
    assert run.records_received == 4  # d01, d02, d03, d06
    assert run.links_marked_stale == 0
    assert not EndpointSecurityState.objects.filter(missing_since__isnull=False).exists()


# --- Authentication, tokens and throttling ---------------------------------------------------


def test_rejected_credentials_fail_with_actionable_error(defender, defender_api):
    defender_api.overrides["token"] = (
        401,
        {
            "error": "invalid_client",
            "error_description": "AADSTS700027: Client assertion failed signature validation."
            "\r\nTrace ID: 0000",
        },
    )

    run = run_sync(defender)

    assert run.status == SyncRun.Status.FAILED and "SOURCE_AUTH_FAILED" in run.error_message
    assert "AADSTS700027" in run.error_message and "Trace ID" not in run.error_message
    assert defender_api.requests == []


def test_403_names_the_machine_read_permission(defender, defender_api):
    defender_api.overrides["page1"] = (403, {"error": {"code": "Forbidden", "message": "x"}})

    run = run_sync(defender)

    assert run.status == SyncRun.Status.FAILED and MACHINE_ROLE in run.error_message
    assert "WindowsDefenderATP" in run.error_message


def test_expired_token_is_renewed_once(defender, defender_api, small_pages, monkeypatch):
    original = defender_api.handler

    def expire_after_first_page(request):
        response = original(request)
        if request.url.host == "api.security.microsoft.com" and len(defender_api.requests) == 1:
            defender_api.expire_tokens()
        return response

    monkeypatch.setattr(defender_api, "handler", expire_after_first_page)

    run = run_sync(defender)

    assert run.status == SyncRun.Status.SUCCEEDED and run.records_received == 10
    assert len(defender_api.token_forms) == 2 and defender_api.pages() == [1, 2, 2, 3]


def test_429_retry_after_and_bounded_retries(defender, defender_api, small_pages):
    throttled = (429, {"error": {"code": "TooManyRequests"}}, {"Retry-After": "11"})
    defender_api.overrides["page2"] = [throttled, None]

    run = run_sync(defender)

    assert run.status == SyncRun.Status.SUCCEEDED and 11.0 in defender_api.sleeps
    assert defender_api.pages() == [1, 2, 2, 3]


def test_persistent_throttling_on_the_first_page_fails(defender, defender_api):
    defender_api.overrides["page1"] = (429, {"error": {"code": "TooManyRequests"}})

    run = run_sync(defender)

    assert run.status == SyncRun.Status.FAILED and "SOURCE_UNAVAILABLE" in run.error_message
    assert defender_api.pages() == [1, 1, 1]  # 1 + max_retries (2)


# --- Connection test, configuration and security API -------------------------------------------


def test_connection_test_reports_permissions(client_for, admin_user, defender, defender_api):
    body = client_for(admin_user).post(f"/api/v1/integrations/{defender.pk}/test/").json()

    assert body["ok"] is True and body["version"] == "Defender for Endpoint API"
    assert body["capabilities"] == {
        "machines": True,
        "advanced_hunting": False,
        "device_actions": False,
        "permission_read_all": True,
        "excess_permissions": False,
    }
    (request,) = defender_api.requests
    assert request.url.params["$top"] == "1"


def test_device_action_permissions_are_reported(client_for, admin_user, defender, defender_api):
    defender_api.roles = [MACHINE_ROLE, "Machine.Isolate", "Machine.Scan", "Ti.ReadWrite.All"]

    body = client_for(admin_user).post(f"/api/v1/integrations/{defender.pk}/test/").json()
    run = run_sync(defender)

    assert body["ok"] is True and body["capabilities"]["excess_permissions"] is True
    for role in ("Machine.Isolate", "Machine.Scan", "Ti.ReadWrite.All"):
        assert role in body["message"]
    assert any("never uses them" in s["warning"] for s in run.warning_samples)


def test_configuration_api(client_for, admin_user, hq, live, defender_api):
    client = client_for(admin_user)
    created = client.post(
        "/api/v1/integrations/",
        {
            "source": "defender",
            "name": "Defender",
            "default_site": str(hq.pk),
            "base_url": "https://attacker.example",
            "tenant_id": defender_api.tenant_id,
            "client_id": defender_api.client_id,
        },
        format="json",
    )
    data = created.json()
    assert created.status_code == 201
    assert data["base_url"] == "https://api.security.microsoft.com"
    assert data["auth_scheme"] == "client_certificate"
    assert (data["sync_interval_minutes"], data["stale_after_hours"]) == (1440, 168)
    assert data["requests_per_second"] == 1
    assert data["connector"]["permissions"] == [MACHINE_ROLE]
    assert data["connector"]["auth_schemes"] == ["client_certificate"]
    secret = client.patch(
        f"/api/v1/integrations/{data['id']}/",
        {"auth_scheme": "client_secret"},
        format="json",
        HTTP_IF_MATCH=f'"{data["version"]}"',
    )
    assert secret.status_code == 422 and "auth_scheme" in secret.json()["error"]["field_errors"]


def test_security_api_respects_site_access(
    defender, defender_api, admin_user, server_category, client_for, make_user, hq, branch
):
    run_sync(defender)
    asset = create_asset_from(defender, mid(3), admin_user, server_category)
    url = f"/api/v1/assets/{asset.pk}/security/"
    analyst = grant(make_user("sec.analyst", roles=["security_analyst"]), hq)
    elsewhere = grant(make_user("branch.analyst", roles=["security_analyst"]), branch)
    reader = grant(make_user("hq.reader2", roles=["read_only"]), hq)

    rows = client_for(analyst).get(url).json()
    assert [r["external_id"] for r in rows] == [mid(3)]
    row = rows[0]
    assert row["instance"]["source"] == "defender" and row["original"]["healthStatus"] == "Active"
    assert row["tenant_id"] == defender_api.tenant_id and row["freshness"] == "fresh"
    assert "online" not in json.dumps(row).lower()  # lastSeen is never an online status
    assert client_for(elsewhere).get(url).status_code == 404
    assert client_for(reader).get(url).status_code == 403


def test_security_freshness_reflects_old_reports_and_missing_machines(
    defender, defender_api, admin_user, server_category, client_for
):
    run_sync(defender)
    asset = create_asset_from(defender, mid(7), admin_user, server_category)  # seen 2026-10-20
    EndpointSecurityState.objects.filter(external_id=mid(7)).update(
        last_seen_at=timezone.now() - timedelta(days=10)
    )

    (row,) = client_for(admin_user).get(f"/api/v1/assets/{asset.pk}/security/").json()

    assert row["freshness"] == "stale" and row["missing_since"] is None


def test_credentials_and_tokens_never_reach_logs_or_the_api(
    defender, defender_api, client_for, admin_user, caplog
):
    caplog.set_level(logging.DEBUG)
    run_sync(defender)
    pem = certificate_pem()
    body = client_for(admin_user).get(f"/api/v1/integrations/{defender.pk}/").content.decode()
    for text in (caplog.text, body):
        assert "PRIVATE KEY" not in text and pem[40:120] not in text
        assert all(token not in text for token in defender_api.valid_tokens)
        assert all(f["client_assertion"] not in text for f in defender_api.token_forms)


def test_scheduler_includes_defender(defender, monkeypatch):
    monkeypatch.setattr("apps.integrations.tasks.run_sync_task.delay", lambda run_id: None)

    assert sync.dispatch_due() == 1 and SyncRun.objects.get().instance == defender


def test_live_integrations_switch_blocks_defender(defender, defender_api, settings):
    settings.ITAM_ALLOW_LIVE_INTEGRATIONS = False

    with pytest.raises(sync.SyncRefused) as exc:
        sync.queue_sync(defender, mode="full", triggered_by="test")
    assert exc.value.code == "LIVE_INTEGRATIONS_DISABLED" and defender_api.token_forms == []


# --- Mapping helpers ---------------------------------------------------------------------------


def test_parse_time_and_interface_grouping():
    assert parse_time("2026-11-02T07:41:12.1234567Z") == "2026-11-02T07:41:12.123456+00:00"
    assert parse_time("0001-01-01T00:00:00Z") is None and parse_time(None) is None
    record, warnings = machine_to_record(
        {
            "id": "m",
            "lastSeen": "2026-11-02T07:00:00Z",
            "computerDnsName": "bad name!",
            "ipAddresses": [
                {"ipAddress": "192.0.2.1", "macAddress": "020000000001", "type": "Ethernet"},
                {"ipAddress": "192.0.2.2", "macAddress": "020000000001", "type": "Ethernet"},
                {"ipAddress": "192.0.2.3", "macAddress": "000000000000", "type": "Tunnel"},
            ],
        },
        tenant_id="t",
        fetched_at="2026-11-02T08:00:00+00:00",
    )
    assert record["interfaces"] == [
        {"name": "Ethernet 1", "mac": "020000000001", "ips": ["192.0.2.1", "192.0.2.2"]}
    ]
    assert record["hostname"] is None and "invalid DNS name" in warnings[0]
