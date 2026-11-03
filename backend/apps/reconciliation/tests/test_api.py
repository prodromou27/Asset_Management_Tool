"""Reconciliation, evidence, merge and integration APIs: permissions, scope, audit."""

import pytest

from apps.assets.models import Asset
from apps.audit.models import AuditEvent
from apps.integrations.models import IntegrationInstance
from apps.reconciliation.models import AssetMerge, ReconciliationCandidate, SourceLink

from .conftest import ingest, switch_record

pytestmark = pytest.mark.django_db
CANDIDATES = "/api/v1/discovery/candidates/"


def approve(client, c, **body):
    return client.post(
        f"/api/v1/reconciliation/{c.pk}/approve/",
        body,
        format="json",
        HTTP_IF_MATCH=f'"{c.version}"',
    )


@pytest.fixture
def hq_candidate(nms):
    ingest(nms, switch_record())
    return ReconciliationCandidate.objects.get()


@pytest.fixture
def branch_candidate(nms_branch):
    ingest(nms_branch, switch_record("b-1", serial="BR-SERIAL", hostname="br-sw"))
    return ReconciliationCandidate.objects.get(instance=nms_branch)


# --- Visibility -------------------------------------------------------------------------


def test_unauthenticated_and_unprivileged_are_denied(
    api_client, client_for, hq_operator, hq_candidate
):
    assert api_client.get(CANDIDATES).status_code == 401
    assert (
        client_for(hq_operator).get(CANDIDATES).status_code == 403
    )  # operators lack discovery.view


def test_candidates_are_site_scoped(client_for, hq_manager, hq_candidate, branch_candidate):
    client = client_for(hq_manager)

    ids = [c["id"] for c in client.get(CANDIDATES).json()["items"]]
    assert ids == [str(hq_candidate.pk)]
    assert client.get(f"{CANDIDATES}{branch_candidate.pk}/").status_code == 404
    assert (
        approve(client, branch_candidate, action="create", reason="cross site").status_code == 404
    )


def test_matches_in_unauthorized_sites_are_hidden(
    client_for, hq_manager, nms, make_asset, branch, switch
):
    make_asset(
        "secret-branch",
        site=branch,
        category=switch,
        manufacturer="Cisco",
        serial_number="FOC2233X0AB",
    )
    ingest(nms, switch_record())

    body = client_for(hq_manager).get(CANDIDATES).json()["items"][0]

    assert body["matches"] == [] and body["hidden_match_count"] == 1
    assert body["proposed_asset"] is None
    assert "secret-branch" not in str(body)


def test_observation_detail_shows_raw_and_normalized(client_for, hq_manager, hq_candidate):
    body = (
        client_for(hq_manager)
        .get(f"/api/v1/discovery/observations/{hq_candidate.observation_id}/")
        .json()
    )

    assert body["payload"]["manufacturer"] == "Cisco Systems, Inc."
    assert body["normalized"]["manufacturer"] == "Cisco"
    assert len(body["checksum"]) == 64


# --- Decisions -------------------------------------------------------------------------


def test_decide_requires_permission(client_for, hq_reader, make_user, hq, hq_candidate):
    from .conftest import grant

    analyst = grant(make_user("analyst", roles=["security_analyst"]), hq)
    assert client_for(analyst).get(CANDIDATES).status_code == 200
    response = approve(client_for(analyst), hq_candidate, action="create", reason="no rights here")
    assert response.status_code == 403
    assert not Asset.objects.exists()


def test_approve_create_builds_asset_links_and_audits(client_for, hq_manager, hq_candidate):
    response = approve(
        client_for(hq_manager),
        hq_candidate,
        action="create",
        reason="New core switch",
        name="sw-core-01",
    )

    assert response.status_code == 200, response.json()
    body = response.json()
    assert body["status"] == "created" and body["decided_by"] == "hq.manager"
    asset = Asset.objects.get()
    assert asset.name == "sw-core-01" and asset.category.code == "networking-switch"
    assert asset.business_status == "deployed" and asset.observation_status == "recently_seen"
    assert SourceLink.objects.get().asset == asset
    event = AuditEvent.objects.get(action="reconciliation.create")
    assert event.detail == "New core switch" and event.after["rule"] == "new_device"


def test_approve_link_and_unlink_are_reversible(
    client_for, hq_manager, hq_candidate, make_asset, hq, switch
):
    target = make_asset("existing", site=hq, category=switch)
    client = client_for(hq_manager)

    linked = approve(
        client, hq_candidate, action="link", asset=str(target.pk), reason="Same physical switch"
    )
    assert linked.status_code == 200, linked.json()
    link = SourceLink.objects.get()
    assert link.asset == target
    assert target.hostnames.filter(source="fixture").exists()

    unlinked = client.post(
        f"/api/v1/source-links/{link.pk}/unlink/", {"reason": "Wrong device"}, format="json"
    )
    assert unlinked.status_code == 200 and unlinked.json()["status"] == "unlinked"
    assert not target.hostnames.filter(source="fixture").exists()
    assert ReconciliationCandidate.objects.filter(status="open").count() == 1  # back in the queue
    assert {e.change_type for e in target.history.all()} >= {"linked", "unlinked"}
    assert AuditEvent.objects.filter(action="reconciliation.unlink").exists()


def test_link_to_invisible_asset_is_rejected(
    client_for, hq_manager, hq_candidate, make_asset, branch, switch
):
    hidden = make_asset("hidden", site=branch, category=switch)

    response = approve(
        client_for(hq_manager),
        hq_candidate,
        action="link",
        asset=str(hidden.pk),
        reason="trying it",
    )

    assert response.status_code == 422
    assert not SourceLink.objects.exists()


@pytest.mark.parametrize("action", ["reject", "hold"])
def test_reject_and_hold_need_reason_and_version(client_for, hq_manager, hq_candidate, action):
    client = client_for(hq_manager)
    url = f"/api/v1/reconciliation/{hq_candidate.pk}/{action}/"

    assert client.post(url, {"reason": "x"}, format="json", HTTP_IF_MATCH='"1"').status_code == 422
    assert client.post(url, {"reason": "Lab equipment"}, format="json").status_code == 428
    ok = client.post(url, {"reason": "Lab equipment"}, format="json", HTTP_IF_MATCH='"1"')
    assert ok.status_code == 200
    assert ok.json()["status"] == {"reject": "rejected", "hold": "held"}[action]
    assert AuditEvent.objects.filter(action=f"reconciliation.{action}").exists()


def test_decided_candidate_cannot_be_decided_again(client_for, hq_manager, hq_candidate):
    client = client_for(hq_manager)
    approve(client, hq_candidate, action="create", reason="New core switch")
    hq_candidate.refresh_from_db()

    again = approve(client, hq_candidate, action="create", reason="Second time")

    assert again.status_code == 409
    assert Asset.objects.count() == 1


def test_operator_cannot_create_from_candidate_without_decide(
    client_for, hq_operator, hq_candidate
):
    assert (
        approve(
            client_for(hq_operator), hq_candidate, action="create", reason="Operator try"
        ).status_code
        == 403
    )


# --- Merge -------------------------------------------------------------------------------


def test_merge_moves_links_archives_duplicate_and_reverts(
    client_for, hq_manager, hq_candidate, make_asset, hq, switch
):
    client = client_for(hq_manager)
    approve(client, hq_candidate, action="create", reason="New core switch")
    duplicate = Asset.objects.get()
    survivor = make_asset("sw-core-01 (manual)", site=hq, category=switch)

    merged = client.post(
        f"/api/v1/assets/{survivor.pk}/merge/",
        {"source_asset": str(duplicate.pk), "reason": "Duplicate record"},
        format="json",
        HTTP_IF_MATCH='"1"',
    )
    assert merged.status_code == 200, merged.json()
    duplicate.refresh_from_db()
    assert duplicate.archived_at is not None and "Merged into" in duplicate.archive_reason
    assert SourceLink.objects.get().asset == survivor
    assert survivor.hostnames.filter(source="fixture").exists()
    assert AuditEvent.objects.filter(action="assets.merge").exists()

    record = AssetMerge.objects.get()
    reverted = client.post(
        f"/api/v1/merges/{record.pk}/revert/", {"reason": "Merged in error"}, format="json"
    )
    assert reverted.status_code == 200 and reverted.json()["status"] == "reverted"
    duplicate.refresh_from_db()
    assert duplicate.archived_at is None
    assert SourceLink.objects.get().asset == duplicate
    assert duplicate.hostnames.filter(source="fixture").exists()
    assert (
        client.post(
            f"/api/v1/merges/{record.pk}/revert/", {"reason": "again please"}, format="json"
        ).status_code
        == 409
    )


def test_merge_requires_permission_and_scope(
    client_for, hq_operator, hq_manager, make_asset, hq, branch, switch
):
    a = make_asset("a", site=hq, category=switch)
    b = make_asset("b", site=hq, category=switch)
    hidden = make_asset("c", site=branch, category=switch)

    body = {"source_asset": str(b.pk), "reason": "Duplicate record"}
    assert (
        client_for(hq_operator)
        .post(f"/api/v1/assets/{a.pk}/merge/", body, format="json", HTTP_IF_MATCH='"1"')
        .status_code
        == 403
    )
    cross = client_for(hq_manager).post(
        f"/api/v1/assets/{a.pk}/merge/",
        {"source_asset": str(hidden.pk), "reason": "Cross site"},
        format="json",
        HTTP_IF_MATCH='"1"',
    )
    assert cross.status_code == 422


# --- Evidence ----------------------------------------------------------------------------


def test_evidence_shows_value_source_time_and_disagreement(
    client_for, hq_manager, hq_candidate, ec, nms
):
    client = client_for(hq_manager)
    approve(client, hq_candidate, action="create", reason="New core switch")
    asset = Asset.objects.get()
    ingest(ec, switch_record("ec-1", firmware_version="17.9.3"))
    ec_candidate = ReconciliationCandidate.objects.get(instance=ec)
    approve(client, ec_candidate, action="link", asset=str(asset.pk), reason="Same switch")

    body = client.get(f"/api/v1/assets/{asset.pk}/evidence/").json()

    firmware = next(r for r in body["field_evidence"] if r["field"] == "firmware_version")
    # Endpoint Central outranks the fixture source for firmware in the default policy.
    assert firmware["value"] == "17.9.3"
    assert firmware["provenance"]["instance"]["name"] == "Endpoint Central"
    assert {s["instance"]["name"]: s["differs"] for s in firmware["sources"]} == {
        "NMS HQ": True,
        "Endpoint Central": False,
    }
    assert len(body["links"]) == 2
    observations = client.get(f"/api/v1/assets/{asset.pk}/observations/").json()
    assert observations["count"] == 2


# --- Integrations admin --------------------------------------------------------------------


def test_integration_admin_and_planned_sources(client_for, admin_user, hq_manager, hq):
    client = client_for(admin_user)
    sources = {
        s["code"]: s["availability"] for s in client.get("/api/v1/discovery/sources/").json()
    }
    # LibreNMS has a fixture-tested adapter (Task 006) but is not live-validated: beta.
    assert sources["librenms"] == "beta" and sources["fixture"] == "available"
    assert sources["intune"] == "beta" and sources["defender"] == "beta"
    assert sources["m365"] == "planned"

    bad = client.post(
        "/api/v1/integrations/",
        {
            "source": "librenms",
            "name": "LNMS",
            "default_site": str(hq.pk),
            "base_url": "http://librenms.internal",
        },
        format="json",
    )
    assert bad.status_code == 422 and "base_url" in bad.json()["error"]["field_errors"]
    forced = client.post(
        "/api/v1/integrations/",
        {"source": "librenms", "name": "LNMS", "default_site": str(hq.pk), "status": "available"},
        format="json",
    )
    assert forced.status_code == 422  # Available is only earned by a working adapter
    created = client.post(
        "/api/v1/integrations/",
        {
            "source": "librenms",
            "name": "LNMS",
            "default_site": str(hq.pk),
            "base_url": "https://librenms.internal",
        },
        format="json",
    )
    assert created.status_code == 201 and created.json()["status"] == "configured"
    assert created.json()["freshness"] == "never"
    assert AuditEvent.objects.filter(action="integrations.create").exists()

    assert (
        client_for(hq_manager).post("/api/v1/integrations/", {}, format="json").status_code == 403
    )
    assert client_for(hq_manager).get("/api/v1/integrations/").status_code == 200


def test_field_authority_policy_is_validated_and_audited(client_for, admin_user):
    client = client_for(admin_user)
    current = client.get("/api/v1/discovery/field-authority/")
    version = current.json()["version"]

    bad = client.patch(
        "/api/v1/discovery/field-authority/",
        {"precedence": {"owner": ["librenms"]}},
        format="json",
        HTTP_IF_MATCH=f'"{version}"',
    )
    assert bad.status_code == 422
    ok = client.patch(
        "/api/v1/discovery/field-authority/",
        {"precedence": {"os_name": ["intune", "endpoint_central"]}},
        format="json",
        HTTP_IF_MATCH=f'"{version}"',
    )
    assert ok.status_code == 200 and ok.json()["precedence"]["os_name"] == [
        "intune",
        "endpoint_central",
    ]
    assert AuditEvent.objects.filter(action="integrations.field_authority").exists()


def test_sync_runs_listed_per_instance(client_for, hq_manager, nms, hq_candidate):
    body = client_for(hq_manager).get(f"/api/v1/integrations/{nms.pk}/runs/").json()

    assert body["count"] == 1 and body["items"][0]["candidates_opened"] == 1
    assert IntegrationInstance.objects.get(pk=nms.pk).status == "available"
