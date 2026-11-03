"""Microsoft Intune (Graph v1.0) synchronisation against sanitized fixtures (Task 008).

The Entra token endpoint and Graph are served by httpx.MockTransport
(conftest.FakeGraph); nothing contacts a network. The fake rejects any non-GET request
to Graph and any token request outside the fixture tenant's token path.
"""

import base64
import json
import logging
from datetime import timedelta

import httpx
import pytest
from django.utils import timezone

from apps.assets.models import Asset, AssetCategory, FieldLock
from apps.audit.models import AuditEvent
from apps.integrations import sync
from apps.integrations.adapters.intune import auth
from apps.integrations.adapters.intune.client import GraphClient
from apps.integrations.adapters.intune.mapping import device_to_record, device_type, parse_time
from apps.integrations.models import IntegrationInstance, SyncRun
from apps.observations.models import Observation
from apps.reconciliation import services
from apps.reconciliation.models import FieldConflict, ReconciliationCandidate, SourceLink
from apps.reconciliation.tests.conftest import Req

from .conftest import (
    INTUNE_SECRET,
    READ_ROLE,
    FakeGraph,
    make_endpoint_central,
    make_intune,
    run_sync,
)

pytestmark = pytest.mark.django_db


def dev(n: int) -> str:
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


def touch(graph: FakeGraph, n: int, **changes) -> None:
    """The device checked in again and reports changed values."""
    device = graph.device(n)
    device["lastSyncDateTime"] = "2026-11-03T07:30:00Z"
    device.update(changes)


@pytest.fixture
def desktop(db):
    return AssetCategory.objects.get(code="workstations-desktop")


# --- Full synchronisation and mapping -------------------------------------------------------


def test_initial_full_sync_follows_next_links_and_creates_only_candidates(intune, graph):
    run = run_sync(intune)

    assert run.status == SyncRun.Status.SUCCEEDED and run.records_received == 12
    assert run.candidates_opened == 12 and Asset.objects.count() == 0
    assert graph.graph_pages() == [1, 2, 3]
    assert run.api_requests == 4  # 1 token + 3 pages
    first = graph.requests[0].url.params
    assert (
        first["$select"].startswith("id,deviceName") and "userPrincipalName" not in first["$select"]
    )
    (form,) = graph.token_forms
    assert form["grant_type"] == "client_credentials"
    assert form["scope"] == "https://graph.microsoft.com/.default"
    assert form["client_id"] == graph.client_id and form["client_secret"] == INTUNE_SECRET
    intune.refresh_from_db()
    assert intune.status == IntegrationInstance.Status.AVAILABLE and intune.last_success_at


def test_source_ids_tenant_and_original_values_are_preserved(intune, graph):
    run_sync(intune)

    obs = latest(intune, dev(1))
    raw = obs.payload["raw"]
    assert raw["tenant_id"] == graph.tenant_id
    assert raw["managed_device_id"] == dev(1)
    assert raw["entra_device_id"] == "e1000001-0000-4000-8000-000000000001"
    assert raw["fields"]["manufacturer"] == "Dell Inc."  # original, not normalised
    assert raw["fields"]["complianceState"] == "compliant"
    assert raw["fields"]["deviceEnrollmentType"] == "windowsAzureADJoin"
    assert raw["fields"]["managementAgent"] == "mdm"
    assert raw["fields"]["enrolledDateTime"] == "2026-01-15T09:12:00Z"
    assert obs.payload["_meta"]["last_sync"] == "2026-11-02T07:30:00+00:00"
    n = obs.normalized
    assert n["observed_at"] == "2026-11-02T07:30:00+00:00"  # last Intune check-in
    assert (n["manufacturer"], n["serial_number"]) == ("Dell", "7XK2Q93") and n["serial_verified"]
    assert n["hostnames"] == ["lt-0042"] and n["mac_addresses"] == ["02:00:00:00:10:42"]
    assert (n["os_name"], n["os_version"]) == ("Windows", "10.0.22631.4460")
    assert n["category_code"] == "workstations-laptop"


def test_category_hints_only_from_unambiguous_models(intune, graph):
    run_sync(intune)

    codes = {i: latest(intune, dev(i)).normalized["category_code"] for i in (2, 3, 4, 5, 7, 8)}
    assert codes == {
        2: "workstations-desktop",  # HP EliteDesk
        3: "workstations-laptop",  # Surface Laptop
        4: "workstations-laptop",  # MacBook Pro
        5: None,  # iPhone: no phone category, reviewer decides
        7: "servers-virtual-machine",
        8: None,  # ThinkCentre: form factor not certain
    }


def test_phone_label_is_not_used_as_hostname(intune, graph):
    run_sync(intune)

    obs = latest(intune, dev(5))
    assert obs.normalized["hostnames"] == [] and obs.normalized["warnings"] == []
    assert obs.payload["raw"]["fields"]["deviceName"] == "Alex's iPhone"


def test_missing_serial_and_missing_properties_stay_unknown(intune, graph):
    run = run_sync(intune)

    android = latest(intune, dev(6)).normalized
    assert android["serial_number"] is None and android["serial_verified"] is False
    bare = latest(intune, dev(10))
    assert bare.normalized["manufacturer"] is None and bare.normalized["model"] is None
    assert bare.payload["raw"]["entra_device_id"] is None  # zero GUID
    assert bare.payload["_meta"]["last_sync"] is None
    assert any(
        s["external_id"] == dev(10) and "no check-in" in s["warning"] for s in run.warning_samples
    )


def test_oem_placeholders_and_unknown_properties(intune, graph):
    run_sync(intune)

    obs = latest(intune, dev(12))
    n = obs.normalized
    assert (n["manufacturer"], n["model"], n["serial_number"]) == (None, None, None)
    assert "someFutureProperty" not in json.dumps(obs.payload)


def test_repeat_sync_is_idempotent(intune, graph):
    run_sync(intune)
    second = run_sync(intune)

    assert second.observations_created == 0 and second.observations_unchanged == 12
    assert second.candidates_opened == 0 and second.candidates_updated == 0
    assert ReconciliationCandidate.objects.filter(status="open").count() == 12


def test_check_in_alone_is_not_a_new_observation_but_state_changes_are(intune, graph):
    run_sync(intune)
    graph.device(1)["lastSyncDateTime"] = "2026-11-03T07:30:00Z"  # only checked in
    graph.device(2)["complianceState"] = "compliant"  # compliance changed
    graph.device(3)["deviceEnrollmentType"] = "windowsAutoEnrollment"  # re-enrolled differently

    run = run_sync(intune)

    assert run.observations_created == 2 and run.observations_unchanged == 10
    assert latest(intune, dev(2)).payload["raw"]["fields"]["complianceState"] == "compliant"


# --- Identity reconciliation --------------------------------------------------------------


def test_duplicate_device_names_are_never_merged(intune, graph, admin_user, desktop):
    run_sync(intune)
    asset = create_asset_from(intune, dev(8), admin_user, desktop)
    intune.auto_link_strong_matches = True
    intune.save()
    touch(graph, 9, osVersion="10.0.26100.1")

    run_sync(intune)

    assert SourceLink.objects.filter(asset=asset).count() == 1
    other = candidate(intune, dev(9))
    assert other.proposed_asset_id == asset.pk and other.rule == "weak"  # hostname only
    assert not SourceLink.objects.filter(external_id=dev(9)).exists()


def test_reenrolled_record_with_shared_identifiers_needs_review(intune, graph, admin_user, desktop):
    run_sync(intune)
    asset = create_asset_from(intune, dev(2), admin_user, desktop)
    intune.auto_link_strong_matches = True
    intune.save()
    touch(graph, 11, osVersion="10.0.22631.4460")  # the old record reports again

    run_sync(intune)

    c = candidate(intune, dev(11))
    assert c.rule == "conflict" and c.proposed_asset_id == asset.pk
    assert any("another active Intune record" in text for text in c.conflicts)
    assert list(SourceLink.objects.filter(asset=asset).values_list("external_id", flat=True)) == [
        dev(2)
    ]


def test_changed_device_name_keeps_the_link(intune, graph, admin_user, laptop):
    run_sync(intune)
    asset = create_asset_from(intune, dev(1), admin_user, laptop)
    touch(graph, 1, deviceName="LT-0042-R")

    run = run_sync(intune)

    assert run.candidates_opened == 0 and run.observations_created == 1
    assert SourceLink.objects.get(instance=intune, external_id=dev(1)).asset == asset
    assert not ReconciliationCandidate.objects.filter(external_id=dev(1), status="open").exists()
    assert set(asset.hostnames.values_list("hostname", flat=True)) == {"lt-0042-r"}


def test_strong_serial_without_class_corroboration_is_not_auto_linked(
    intune, graph, make_asset, hq, desktop
):
    intune.auto_link_strong_matches = True
    intune.save()
    kiosk = make_asset(
        "kiosk-a", site=hq, category=desktop, manufacturer="Lenovo", serial_number="PF4KIOSK1"
    )

    run_sync(intune)

    c = candidate(intune, dev(8))  # ThinkCentre: Intune gives no form factor
    assert c.rule == "strong" and c.proposed_asset_id == kiosk.pk
    assert c.matches[0]["category_agrees"] is None
    assert not SourceLink.objects.filter(asset=kiosk).exists()


def test_same_laptop_from_endpoint_central_and_intune_is_one_asset(
    hq, live, graph, ec_fake, admin_user, laptop, monkeypatch
):
    monkeypatch.setenv("ITAM_INTEGRATION_EC_TOKEN", "ec-fixture-key")
    monkeypatch.setenv("ITAM_INTEGRATION_INTUNE_SECRET", INTUNE_SECRET)
    monkeypatch.setattr(
        sync,
        "TRANSPORT_FACTORY",
        lambda inst: httpx.MockTransport(
            ec_fake.handler if inst.source_id == "endpoint_central" else graph.handler
        ),
    )
    ec = make_endpoint_central(hq)
    intune = make_intune(hq, graph, auto_link_strong_matches=True)
    run_sync(ec)
    c = ReconciliationCandidate.objects.get(instance=ec, external_id="301")
    services.approve_create(Req(admin_user), c, {"category": laptop}, "EC laptop", c.version)
    asset = SourceLink.objects.get(instance=ec, external_id="301").asset

    run_sync(intune)

    link = SourceLink.objects.get(instance=intune, external_id=dev(1))
    assert link.asset == asset and link.method == "auto_strong_match"
    assert Asset.objects.count() == 1
    assert AuditEvent.objects.filter(action="reconciliation.auto_link").count() == 1
    # Field authority: Endpoint Central outranks Intune for the OS version.
    asset.refresh_from_db()
    assert asset.os_version == latest(ec, "301").normalized["os_version"]


def test_locked_fields_are_never_overwritten(intune, graph, admin_user, laptop):
    run_sync(intune)
    asset = create_asset_from(intune, dev(1), admin_user, laptop)
    services.lock_field(Req(admin_user), asset, "os_version", "Pinned for CHG-12")
    touch(graph, 1, osVersion="10.0.26100.2314")

    run_sync(intune)

    asset.refresh_from_db()
    assert asset.os_version == "10.0.22631.4460"
    assert FieldLock.objects.filter(asset=asset, field="os_version").exists()
    assert FieldConflict.objects.get(asset=asset, field="os_version").observed_value == (
        "10.0.26100.2314"
    )


# --- Freshness and partial enumeration -------------------------------------------------------


def test_device_missing_from_a_complete_listing_is_marked_stale(intune, graph, admin_user, laptop):
    run_sync(intune)
    asset = create_asset_from(intune, dev(1), admin_user, laptop)
    graph.remove(1)

    run = run_sync(intune)

    assert run.links_marked_stale == 1
    assert SourceLink.objects.get(external_id=dev(1)).status == SourceLink.Status.STALE
    assert Asset.objects.filter(pk=asset.pk, archived_at__isnull=True).exists()  # never deleted


def test_device_that_stopped_checking_in_becomes_stale(intune, graph, admin_user, desktop):
    run_sync(intune)
    create_asset_from(intune, dev(11), admin_user, desktop)  # last check-in 2026-02-27

    assert services.refresh_freshness(now=timezone.now()) == 1
    assert SourceLink.objects.get(external_id=dev(11)).status == SourceLink.Status.STALE


def test_failed_later_page_is_incomplete_and_marks_nothing_stale(intune, graph, admin_user, laptop):
    run_sync(intune)
    create_asset_from(intune, dev(12), admin_user, laptop)  # served on page 3
    graph.overrides["page3"] = (503, {"error": {"code": "ServiceUnavailable"}})
    graph.requests.clear()

    run = run_sync(intune)

    assert run.records_received == 8 and run.links_marked_stale == 0
    assert SourceLink.objects.get(external_id=dev(12)).status == SourceLink.Status.ACTIVE
    assert any("stopped after page 2" in s["warning"] for s in run.warning_samples)
    assert graph.graph_pages().count(3) == 3  # 1 + max_retries (2), then stop


@pytest.mark.parametrize(
    "next_base",
    [
        "https://graph.example/v1.0/deviceManagement/managedDevices",
        "http://graph.microsoft.com/v1.0/deviceManagement/managedDevices",
        "https://graph.microsoft.com/v1.0/users",
        "https://graph.microsoft.com/beta/deviceManagement/managedDevices",
        "https://user@graph.microsoft.com/v1.0/deviceManagement/managedDevices",
        "https://graph.microsoft.com:8443/v1.0/deviceManagement/managedDevices",
    ],
    ids=["other-host", "http", "other-resource", "beta", "userinfo", "port"],
)
def test_unsafe_continuation_links_are_not_followed(intune, graph, admin_user, laptop, next_base):
    run_sync(intune)
    create_asset_from(intune, dev(12), admin_user, laptop)
    graph.requests.clear()
    graph.next_link_base = next_base

    run = run_sync(intune)

    assert graph.graph_pages() == [1]  # the token never left graph.microsoft.com
    assert run.records_received == 4 and run.links_marked_stale == 0
    assert any("not followed" in s["warning"] for s in run.warning_samples)


def test_repeated_continuation_link_stops_listing(intune, graph):
    graph.overrides["page2"] = (
        200,
        {
            "value": [],
            "@odata.nextLink": "https://graph.microsoft.com/v1.0/deviceManagement/managedDevices"
            "?$skiptoken=2",
        },
    )

    run = run_sync(intune)

    assert graph.graph_pages() == [1, 2, 2]  # the loop is detected on the second repeat
    assert run.status == SyncRun.Status.SUCCEEDED and run.records_received == 4
    assert any("repeated" in s["warning"] for s in run.warning_samples)


# --- Authentication, tokens and throttling --------------------------------------------------------


def test_rejected_client_credentials_fail_with_actionable_error(intune, graph):
    graph.overrides["token"] = (
        401,
        {
            "error": "invalid_client",
            "error_description": "AADSTS7000215: Invalid client secret provided. Ensure the "
            "secret being sent is correct.\r\nTrace ID: 0000\r\nCorrelation ID: 1111",
        },
    )

    run = run_sync(intune)

    assert run.status == SyncRun.Status.FAILED
    assert run.error_message.startswith("SOURCE_AUTH_FAILED")
    assert "AADSTS7000215: Invalid client secret provided." in run.error_message
    assert "Trace ID" not in run.error_message and INTUNE_SECRET not in run.error_message
    assert graph.requests == []  # Graph never contacted without a token
    intune.refresh_from_db()
    assert intune.status == IntegrationInstance.Status.DEGRADED


def test_403_reports_the_missing_read_permission(intune, graph):
    graph.overrides["page1"] = (403, {"error": {"code": "Forbidden", "message": "denied"}})

    run = run_sync(intune)

    assert run.status == SyncRun.Status.FAILED and "SOURCE_AUTH_FAILED" in run.error_message
    assert READ_ROLE in run.error_message and "admin consent" in run.error_message


def test_expired_token_is_renewed_once_and_the_page_repeated(intune, graph, monkeypatch):
    original = graph.handler

    def expire_after_first_page(request):
        response = original(request)
        if request.url.host == "graph.microsoft.com" and len(graph.requests) == 1:
            graph.expire_tokens()
        return response

    monkeypatch.setattr(graph, "handler", expire_after_first_page)

    run = run_sync(intune)

    assert run.status == SyncRun.Status.SUCCEEDED and run.records_received == 12
    assert len(graph.token_forms) == 2
    assert graph.graph_pages() == [1, 2, 2, 3]


def test_persistent_401_fails_after_one_renewal(intune, graph):
    graph.overrides["page1"] = (401, {"error": {"code": "InvalidAuthenticationToken"}})

    run = run_sync(intune)

    assert run.status == SyncRun.Status.FAILED and "HTTP 401" in run.error_message
    assert len(graph.token_forms) == 2 and graph.graph_pages() == [1, 1]


def test_token_is_cached_and_renewed_before_expiry(graph, monkeypatch):
    clock = [1_000_000.0]
    monkeypatch.setattr(auth, "now", lambda: clock[0])
    provider = auth.TokenProvider(
        graph.tenant_id,
        graph.client_id,
        auth.ClientSecretCredential(INTUNE_SECRET),
        transport=httpx.MockTransport(graph.handler),
    )

    first = provider.token()
    clock[0] += 3000  # 3599 s lifetime, renewed 300 s early
    assert provider.token() == first and len(graph.token_forms) == 1
    clock[0] += 400
    assert provider.token() != first and len(graph.token_forms) == 2
    assert provider.roles == [READ_ROLE]


def test_429_retry_after_is_honoured(intune, graph):
    throttled = (429, {"error": {"code": "TooManyRequests"}}, {"Retry-After": "7"})
    graph.overrides["page2"] = [throttled, None]

    run = run_sync(intune)

    assert run.status == SyncRun.Status.SUCCEEDED and run.records_received == 12
    assert 7.0 in graph.sleeps and graph.graph_pages() == [1, 2, 2, 3]


def test_token_endpoint_throttling_is_retried(intune, graph):
    graph.overrides["token"] = [
        (429, {"error": "temporarily_unavailable"}, {"Retry-After": "3"}),
        None,
    ]

    run = run_sync(intune)

    assert run.status == SyncRun.Status.SUCCEEDED and 3.0 in graph.sleeps
    assert len(graph.token_forms) == 2


def test_server_errors_are_retried_a_bounded_number_of_times(intune, graph):
    graph.overrides["page1"] = (503, {"error": {"code": "ServiceUnavailable"}})

    run = run_sync(intune)

    assert run.status == SyncRun.Status.FAILED and "SOURCE_UNAVAILABLE" in run.error_message
    assert graph.graph_pages() == [1, 1, 1]  # 1 + max_retries (2)


def test_rejected_property_selection_falls_back_to_full_objects(intune, graph):
    graph.reject_select = True

    run = run_sync(intune)

    assert run.status == SyncRun.Status.SUCCEEDED and run.records_received == 12
    assert any("selection rejected" in s["warning"] for s in run.warning_samples)
    assert "someFutureProperty" not in json.dumps(latest(intune, dev(12)).payload)


# --- Certificate credentials ---------------------------------------------------------------


def _key_and_cert():
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "itam-intune-test")])
    now = timezone.now()
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(1)
        .not_valid_before(now - timedelta(days=1))
        .not_valid_after(now + timedelta(days=30))
        .sign(key, hashes.SHA256())
    )
    key_pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    return key_pem, cert.public_bytes(serialization.Encoding.PEM).decode(), cert


def _unb64(part: str) -> bytes:
    return base64.urlsafe_b64decode(part + "=" * (-len(part) % 4))


def test_certificate_credential_signs_a_client_assertion(hq, live, graph, settings, tmp_path):
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding
    from cryptography.hazmat.primitives.serialization import Encoding

    key_pem, cert_pem, cert = _key_and_cert()
    (tmp_path / "intune-app.pem").write_text(key_pem + cert_pem, encoding="utf-8")
    settings.ITAM_SECRETS_DIR = str(tmp_path)
    intune = make_intune(
        hq, graph, auth_scheme="client_certificate", credential_ref="file:intune-app.pem"
    )

    run = run_sync(intune)

    assert run.status == SyncRun.Status.SUCCEEDED
    (form,) = graph.token_forms
    assert "client_secret" not in form
    assert form["client_assertion_type"] == "urn:ietf:params:oauth:client-assertion-type:jwt-bearer"
    header_b64, claims_b64, signature_b64 = form["client_assertion"].split(".")
    header, claims = json.loads(_unb64(header_b64)), json.loads(_unb64(claims_b64))
    cert.public_key().verify(
        _unb64(signature_b64),
        f"{header_b64}.{claims_b64}".encode(),
        padding.PKCS1v15(),
        hashes.SHA256(),
    )
    import hashlib

    der = cert.public_bytes(Encoding.DER)
    assert header["alg"] == "RS256"
    assert _unb64(header["x5t#S256"]) == hashlib.sha256(der).digest()
    assert claims["aud"] == f"https://login.microsoftonline.com/{graph.tenant_id}/oauth2/v2.0/token"
    assert claims["iss"] == claims["sub"] == graph.client_id
    assert claims["exp"] - claims["iat"] == 600
    assert "PRIVATE KEY" not in json.dumps(form)


def test_certificate_without_private_key_is_refused_before_any_request(
    hq, live, graph, settings, tmp_path
):
    _, cert_pem, _ = _key_and_cert()
    (tmp_path / "cert-only.pem").write_text(cert_pem, encoding="utf-8")
    settings.ITAM_SECRETS_DIR = str(tmp_path)
    intune = make_intune(
        hq, graph, auth_scheme="client_certificate", credential_ref="file:cert-only.pem"
    )

    run = run_sync(intune)

    assert run.status == SyncRun.Status.FAILED
    assert run.error_message.startswith("CREDENTIAL_UNAVAILABLE")
    assert "BEGIN" not in run.error_message
    assert graph.token_forms == [] and graph.requests == []


# --- Secrets, connection test, configuration API and scheduling --------------------------------


def test_secrets_and_tokens_never_reach_logs_or_the_api(
    intune, graph, client_for, admin_user, caplog
):
    caplog.set_level(logging.DEBUG)
    run_sync(intune)
    tokens = list(graph.valid_tokens)
    body = client_for(admin_user).get(f"/api/v1/integrations/{intune.pk}/").content.decode()
    runs = client_for(admin_user).get(f"/api/v1/integrations/{intune.pk}/runs/").content.decode()

    for text in (caplog.text, body, runs):
        assert INTUNE_SECRET not in text
        assert all(token not in text for token in tokens)
    assert json.loads(body)["credential_status"] == "configured"


def test_connection_test_reports_permissions(client_for, admin_user, intune, graph):
    body = client_for(admin_user).post(f"/api/v1/integrations/{intune.pk}/test/").json()

    assert body["ok"] is True and body["version"] == "Microsoft Graph v1.0"
    assert body["capabilities"] == {
        "managed_devices": True,
        "detected_apps": False,
        "permission_read_all": True,
        "excess_permissions": False,
    }
    assert "Warning" not in body["message"]
    (request,) = graph.requests
    assert request.url.params["$top"] == "1" and request.url.params["$select"] == "id"


def test_write_permissions_on_the_app_are_reported(client_for, admin_user, intune, graph):
    graph.roles = [
        READ_ROLE,
        "DeviceManagementManagedDevices.PrivilegedOperations.All",
        "DeviceManagementManagedDevices.ReadWrite.All",
    ]

    body = client_for(admin_user).post(f"/api/v1/integrations/{intune.pk}/test/").json()
    run = run_sync(intune)

    assert body["ok"] is True and body["capabilities"]["excess_permissions"] is True
    assert "PrivilegedOperations.All" in body["message"] and "ReadWrite.All" in body["message"]
    assert any("never uses them" in s["warning"] for s in run.warning_samples)


def test_configuration_api_fixes_the_graph_endpoint_and_validates_ids(
    client_for, admin_user, hq, live, graph
):
    client = client_for(admin_user)
    bad = client.post(
        "/api/v1/integrations/",
        {
            "source": "intune",
            "name": "Intune",
            "default_site": str(hq.pk),
            "tenant_id": "common",
            "client_id": "not-a-guid",
        },
        format="json",
    )
    assert bad.status_code == 422
    assert set(bad.json()["error"]["field_errors"]) >= {"tenant_id", "client_id"}

    created = client.post(
        "/api/v1/integrations/",
        {
            "source": "intune",
            "name": "Intune",
            "default_site": str(hq.pk),
            "base_url": "https://attacker.example",
            "tenant_id": graph.tenant_id,
            "client_id": graph.client_id.upper(),
        },
        format="json",
    )
    data = created.json()
    assert created.status_code == 201
    assert data["base_url"] == "https://graph.microsoft.com"
    assert data["client_id"] == graph.client_id
    assert data["auth_scheme"] == "client_certificate"  # preferred credential type
    assert (data["sync_interval_minutes"], data["stale_after_hours"]) == (1440, 168)
    assert data["connector"]["permissions"] == [READ_ROLE]
    assert data["connector"]["fixed_base_url"] == "https://graph.microsoft.com"
    assert data["connector"]["required_settings"] == ["tenant_id", "client_id"]
    assert data["connector"]["auth_schemes"] == ["client_certificate", "client_secret"]

    patched = client.patch(
        f"/api/v1/integrations/{data['id']}/",
        {"base_url": "https://attacker.example", "auth_scheme": "bearer"},
        format="json",
        HTTP_IF_MATCH=f'"{data["version"]}"',
    )
    assert patched.status_code == 422 and "auth_scheme" in patched.json()["error"]["field_errors"]
    ok = client.patch(
        f"/api/v1/integrations/{data['id']}/",
        {"base_url": "https://attacker.example", "auth_scheme": "client_secret"},
        format="json",
        HTTP_IF_MATCH=f'"{data["version"]}"',
    )
    assert ok.status_code == 200 and ok.json()["base_url"] == "https://graph.microsoft.com"


def test_missing_tenant_or_client_id_refuses_before_any_request(hq, live, graph, monkeypatch):
    monkeypatch.setenv("ITAM_INTEGRATION_INTUNE_SECRET", INTUNE_SECRET)
    intune = make_intune(hq, graph, tenant_id="")

    with pytest.raises(sync.SyncRefused) as exc:
        sync.queue_sync(intune, mode="full", triggered_by="test")

    assert exc.value.code == "NOT_CONFIGURED" and "tenant ID" in str(exc.value)
    assert graph.token_forms == []


def test_live_integrations_switch_blocks_intune(intune, graph, settings):
    settings.ITAM_ALLOW_LIVE_INTEGRATIONS = False

    with pytest.raises(sync.SyncRefused) as exc:
        sync.queue_sync(intune, mode="full", triggered_by="test")

    assert exc.value.code == "LIVE_INTEGRATIONS_DISABLED" and graph.token_forms == []


def test_scheduler_includes_intune(intune, monkeypatch):
    monkeypatch.setattr("apps.integrations.tasks.run_sync_task.delay", lambda run_id: None)

    assert sync.dispatch_due() == 1 and SyncRun.objects.get().instance == intune


# --- Mapping helpers ---------------------------------------------------------------------------


def test_parse_time_handles_graph_formats():
    assert parse_time("2026-11-02T07:30:00Z") == "2026-11-02T07:30:00+00:00"
    assert parse_time("2026-11-02T07:30:00.1234567Z") == "2026-11-02T07:30:00.123456+00:00"
    assert parse_time("2026-11-02T07:30:00") == "2026-11-02T07:30:00+00:00"  # Graph is UTC
    assert parse_time("0001-01-01T00:00:00Z") is None
    assert parse_time("") is None and parse_time(None) is None and parse_time("yesterday") is None


def test_device_type_rules():
    assert device_type("Windows", "Dell Inc.", "Latitude 5550") == "laptop"
    assert device_type("Windows", "HP", "HP ProDesk 400 G9") == "desktop"
    assert device_type("Windows", "VMware, Inc.", "VMware7,1") == "virtual_machine"
    assert device_type("Windows", "Dell Inc.", "Precision 3680") is None
    assert device_type("Android", "samsung", "SM-S921B") is None


def test_invalid_wifi_mac_is_ignored_with_a_warning():
    record, warnings = device_to_record(
        {"id": "x", "lastSyncDateTime": "2026-11-02T07:30:00Z", "wiFiMacAddress": "unknown"},
        tenant_id="t",
        fetched_at="2026-11-02T08:00:00+00:00",
    )
    assert record["interfaces"] == [] and "Wi-Fi MAC" in warnings[0]


def test_graph_client_is_fixed_to_graph_v1(graph):
    tokens = auth.TokenProvider(
        graph.tenant_id,
        graph.client_id,
        auth.ClientSecretCredential(INTUNE_SECRET),
        transport=httpx.MockTransport(graph.handler),
    )
    client = GraphClient(tokens, transport=httpx.MockTransport(graph.handler))
    assert client.base_url == "https://graph.microsoft.com" and client.api_prefix == "/v1.0"
    assert "***" in repr(auth.ClientSecretCredential(INTUNE_SECRET))
    assert INTUNE_SECRET not in repr(tokens)
