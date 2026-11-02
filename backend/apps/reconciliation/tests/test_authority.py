"""Field authority, manual locks, conflicts and field-level permissions (closes ASM-09)."""

import pytest

from apps.assets.models import FieldLock, FieldProvenance
from apps.reconciliation import services
from apps.reconciliation.models import FieldConflict, ReconciliationCandidate, SourceLink

from .conftest import Req, grant, ingest, switch_record

pytestmark = pytest.mark.django_db
ASSETS = "/api/v1/assets/"


@pytest.fixture
def linked(nms, admin_user):
    ingest(nms, switch_record())
    c = ReconciliationCandidate.objects.get()
    services.approve_create(Req(admin_user), c, {}, "Approve new switch", c.version)
    return SourceLink.objects.get().asset


@pytest.fixture
def engineer(make_user, hq):
    return grant(make_user("hq.engineer", roles=["infrastructure_engineer"]), hq)


def test_discovered_values_carry_source_and_time(linked, nms):
    linked.refresh_from_db()
    assert linked.manufacturer == "Cisco" and linked.serial_number == "FOC2233X0AB"
    prov = FieldProvenance.objects.get(asset=linked, field="serial_number")
    assert prov.kind == "discovery" and prov.instance == nms
    assert prov.observed_at.isoformat() == "2026-11-02T08:00:00+00:00"
    assert not FieldLock.objects.filter(asset=linked).exists()


def test_business_fields_are_never_written_by_discovery(linked, nms):
    before = (
        linked.name,
        linked.site_id,
        linked.owner_id,
        linked.business_status,
        linked.category_id,
    )

    ingest(nms, switch_record(hostname="renamed.example", device_type="router"))

    linked.refresh_from_db()
    assert (
        linked.name,
        linked.site_id,
        linked.owner_id,
        linked.business_status,
        linked.category_id,
    ) == before


def test_missing_values_do_not_clear_existing_data(linked, nms):
    ingest(nms, switch_record(serial=None, os_version=None))

    linked.refresh_from_db()
    assert linked.serial_number == "FOC2233X0AB" and linked.os_version == "17.9.4"


def test_manual_edit_locks_and_discovery_raises_conflict(client_for, engineer, linked, nms):
    response = client_for(engineer).patch(
        f"{ASSETS}{linked.pk}/",
        {"os_version": "17.9.5a"},
        format="json",
        HTTP_IF_MATCH=f'"{linked.version}"',
    )
    assert response.status_code == 200, response.json()
    assert FieldLock.objects.filter(asset=linked, field="os_version").exists()

    run = ingest(nms, switch_record(os_version="17.12.1"))

    linked.refresh_from_db()
    assert linked.os_version == "17.9.5a"  # never silently overwritten
    assert run.conflicts_opened == 1
    conflict = FieldConflict.objects.get()
    assert (conflict.current_value, conflict.observed_value, conflict.reason) == (
        "17.9.5a",
        "17.12.1",
        "locked",
    )

    ingest(nms, switch_record(os_version="17.12.1", model="C9300-48T "))  # same value again
    assert FieldConflict.objects.filter(status="open").count() == 1


def test_accepting_conflict_applies_value_and_unlocks(client_for, engineer, linked, nms):
    FieldLock.objects.create(asset=linked, field="os_version", reason="test")
    ingest(nms, switch_record(os_version="17.12.1"))
    conflict = FieldConflict.objects.get()

    response = client_for(engineer).post(
        f"/api/v1/discovery/conflicts/{conflict.pk}/resolve/",
        {"resolution": "accept_observed", "reason": "Upgrade confirmed"},
        format="json",
    )

    assert response.status_code == 200 and response.json()["status"] == "accepted"
    linked.refresh_from_db()
    assert linked.os_version == "17.12.1"
    assert not FieldLock.objects.filter(asset=linked, field="os_version").exists()
    assert FieldProvenance.objects.get(asset=linked, field="os_version").kind == "discovery"


def test_keep_current_dismisses_and_stays_locked(client_for, engineer, linked, nms):
    FieldLock.objects.create(asset=linked, field="os_version", reason="test")
    ingest(nms, switch_record(os_version="17.12.1"))
    conflict = FieldConflict.objects.get()

    client_for(engineer).post(
        f"/api/v1/discovery/conflicts/{conflict.pk}/resolve/",
        {"resolution": "keep_current", "reason": "Source reports wrong train"},
        format="json",
    )

    linked.refresh_from_db()
    assert linked.os_version == "17.9.4"
    assert FieldLock.objects.filter(asset=linked, field="os_version").exists()


def test_higher_authority_source_wins_while_fresh(linked, ec, nms, admin_user):
    ingest(ec, switch_record("ec-77", os_name="Cisco IOS-XE (EC)"))
    c = ReconciliationCandidate.objects.get(instance=ec)
    services.approve_link(Req(admin_user), c, linked, "Same switch", c.version)
    linked.refresh_from_db()
    assert linked.os_name == "Cisco IOS-XE (EC)"

    ingest(nms, switch_record(os_name="IOS XE (nms)"))

    linked.refresh_from_db()
    assert linked.os_name == "Cisco IOS-XE (EC)"  # endpoint_central outranks fixture for os_name


# --- Field-level permissions (ASM-09) -------------------------------------------------


def test_operator_cannot_override_discovered_technical_fields(client_for, hq_operator, linked):
    response = client_for(hq_operator).patch(
        f"{ASSETS}{linked.pk}/",
        {"serial_number": "TYPO"},
        format="json",
        HTTP_IF_MATCH=f'"{linked.version}"',
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FIELD_PERMISSION_DENIED"
    assert "serial_number" in response.json()["error"]["field_errors"]
    linked.refresh_from_db()
    assert linked.serial_number == "FOC2233X0AB"


def test_operator_can_still_edit_business_fields_and_manual_technical_values(
    client_for, hq_operator, linked, make_asset, hq, switch
):
    ok = client_for(hq_operator).patch(
        f"{ASSETS}{linked.pk}/",
        {"notes": "Rack A3", "business_status": "deployed"},
        format="json",
        HTTP_IF_MATCH=f'"{linked.version}"',
    )
    assert ok.status_code == 200

    manual = make_asset("monitor", site=hq, category=switch, serial_number="MANUAL1")
    edit = client_for(hq_operator).patch(
        f"{ASSETS}{manual.pk}/", {"serial_number": "MANUAL2"}, format="json", HTTP_IF_MATCH='"1"'
    )
    assert edit.status_code == 200


def test_engineer_edits_technical_but_not_business_fields(
    client_for, engineer, linked, hq_operator
):
    client = client_for(engineer)

    technical = client.patch(
        f"{ASSETS}{linked.pk}/",
        {"firmware_version": "17.9.5"},
        format="json",
        HTTP_IF_MATCH=f'"{linked.version}"',
    )
    assert technical.status_code == 200
    business = client.patch(
        f"{ASSETS}{linked.pk}/",
        {"owner": str(hq_operator.pk)},
        format="json",
        HTTP_IF_MATCH=f'"{technical.json()["version"]}"',
    )
    assert business.status_code == 403
    assert "owner" in business.json()["error"]["field_errors"]


def test_locks_require_technical_permission_and_are_audited(
    client_for, hq_operator, engineer, linked
):
    body = {"field": "model", "reason": "Verified on site"}

    assert (
        client_for(hq_operator)
        .post(f"{ASSETS}{linked.pk}/field-locks/", body, format="json")
        .status_code
        == 403
    )
    locked = client_for(engineer).post(f"{ASSETS}{linked.pk}/field-locks/", body, format="json")
    assert locked.status_code == 200
    model_row = next(r for r in locked.json()["field_evidence"] if r["field"] == "model")
    assert model_row["lock"]["locked_by"] == "hq.engineer"
    assert linked.history.filter(change_type="field_locked").exists()

    unlocked = client_for(engineer).post(
        f"{ASSETS}{linked.pk}/field-locks/unlock/", body, format="json"
    )
    assert unlocked.status_code == 200
    again = client_for(engineer).post(
        f"{ASSETS}{linked.pk}/field-locks/unlock/", body, format="json"
    )
    assert again.status_code == 409


def test_business_field_lock_is_rejected(client_for, engineer, linked):
    response = client_for(engineer).post(
        f"{ASSETS}{linked.pk}/field-locks/",
        {"field": "owner", "reason": "nope nope"},
        format="json",
    )
    assert response.status_code == 422
