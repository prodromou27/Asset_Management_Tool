"""Ingestion integrity: idempotency, immutability, partial runs, staleness (A01, A03, A08)."""

from datetime import timedelta

import pytest
from django.db import DatabaseError, connection, transaction
from django.utils import timezone

from apps.assets.models import Asset
from apps.integrations.models import IntegrationInstance, SyncRun
from apps.observations.models import Observation
from apps.reconciliation import services
from apps.reconciliation.models import ReconciliationCandidate, SourceLink
from tests.conftest import requires_postgres

from .conftest import Req, ingest, switch_record

pytestmark = pytest.mark.django_db


def test_new_device_becomes_candidate_never_an_asset(nms):
    run = ingest(nms, switch_record())

    assert run.status == "succeeded" and run.candidates_opened == 1
    assert Asset.objects.count() == 0
    candidate = ReconciliationCandidate.objects.get()
    assert candidate.rule == "new_device" and candidate.status == "open"
    assert candidate.suggested_category.code == "networking-switch"  # docs/15 A01
    assert candidate.site == nms.default_site
    assert candidate.observation.normalized["observed_at"] == "2026-11-02T08:00:00+00:00"


def test_repeated_sync_is_idempotent(nms):
    ingest(nms, switch_record())
    second = ingest(nms, switch_record(observed_at="2026-11-02T14:00:00+00:00"))

    assert second.observations_created == 0 and second.observations_unchanged == 1
    assert second.candidates_opened == 0 and second.candidates_updated == 0
    assert Observation.objects.count() == 1
    assert ReconciliationCandidate.objects.count() == 1
    assert Asset.objects.count() == 0


def test_changed_payload_creates_new_observation_and_updates_candidate(nms):
    ingest(nms, switch_record())
    run = ingest(nms, switch_record(os_version="17.12.1"))

    assert run.observations_created == 1 and run.candidates_updated == 1
    assert Observation.objects.count() == 2
    assert ReconciliationCandidate.objects.get().observation.normalized["os_version"] == "17.12.1"


def test_external_ids_are_scoped_to_their_instance(nms, nms_branch):
    ingest(nms, switch_record("317"))
    ingest(nms_branch, switch_record("317", serial="FOC9999", hostname="br-sw-01"))

    assert ReconciliationCandidate.objects.count() == 2
    assert set(ReconciliationCandidate.objects.values_list("instance__name", flat=True)) == {
        "NMS HQ",
        "NMS Branch",
    }


def test_bad_records_make_run_partial_without_losing_good_ones(nms):
    run = ingest(
        nms, switch_record("1"), {"external_id": "2"}, "garbage", switch_record("3", serial="X3")
    )

    assert run.status == "partial"
    assert run.errors == 2 and run.records_received == 4
    assert ReconciliationCandidate.objects.count() == 2
    assert {s["external_id"] for s in run.error_samples} == {"2", None}
    nms.refresh_from_db()
    assert nms.last_success_at is not None


def test_failed_run_degrades_instance_and_changes_nothing(nms):
    run = ingest(nms, {"bad": True})

    assert run.status == "failed"
    nms.refresh_from_db()
    assert nms.status == IntegrationInstance.Status.DEGRADED and nms.last_error


def _linked_asset(nms, admin_user, record=None):
    ingest(nms, record or switch_record())
    candidate = ReconciliationCandidate.objects.get()
    services.approve_create(Req(admin_user), candidate, {}, "Approve new switch", candidate.version)
    return SourceLink.objects.get(instance=nms).asset


def test_linked_device_updates_asset_and_keeps_address_history(nms, admin_user):
    asset = _linked_asset(nms, admin_user)
    assert asset.observation_status == "recently_seen"
    assert list(asset.ip_addresses.values_list("address", flat=True)) == ["10.10.0.2"]

    ingest(
        nms,
        switch_record(
            interfaces=[{"name": "Vlan10", "mac": "0200.0000.0001", "ips": ["10.10.0.9"]}]
        ),
    )

    asset.refresh_from_db()
    assert Asset.objects.count() == 1  # docs/15 A03: same canonical asset
    assert list(asset.ip_addresses.values_list("address", flat=True)) == ["10.10.0.9"]
    entry = asset.history.filter(change_type="discovered").first()
    assert entry.changes["ip_addresses"]["before"] == ["10.10.0.2 on Vlan10 (fixture)"]
    assert entry.actor_label == "source:NMS HQ"


def test_full_sync_marks_missing_devices_stale_never_deletes(nms, admin_user):
    asset = _linked_asset(nms, admin_user)

    run = ingest(nms, switch_record("999", serial="OTHER1", hostname="other"), mode="full")

    assert run.links_marked_stale == 1
    asset.refresh_from_db()
    assert asset.observation_status == "stale" and asset.archived_at is None
    assert SourceLink.objects.get(external_id="317").status == "stale"


def test_partial_full_sync_does_not_mark_anything_stale(nms, admin_user):
    _linked_asset(nms, admin_user)

    run = ingest(
        nms, {"external_id": "x"}, switch_record("999", serial="O2", hostname="o2"), mode="full"
    )

    assert run.status == "partial" and run.links_marked_stale == 0
    assert SourceLink.objects.get(external_id="317").status == "active"


def test_freshness_job_marks_stale_and_reappearance_restores(nms, admin_user):
    asset = _linked_asset(nms, admin_user)

    assert services.refresh_freshness(timezone.now() + timedelta(hours=49)) == 1  # docs/15 A08
    asset.refresh_from_db()
    assert asset.observation_status == "stale"

    ingest(nms, switch_record(observed_at=timezone.now().isoformat()))
    asset.refresh_from_db()
    assert asset.observation_status == "recently_seen"
    assert SourceLink.objects.get().status == "active"


def test_sync_history_is_recorded(nms):
    ingest(nms, switch_record())
    ingest(nms, switch_record())

    runs = SyncRun.objects.filter(instance=nms)
    assert runs.count() == 2
    assert all(r.finished_at for r in runs)


def test_observation_model_is_immutable(nms):
    ingest(nms, switch_record())
    observation = Observation.objects.get()

    with pytest.raises(RuntimeError):
        observation.save()
    with pytest.raises(RuntimeError):
        observation.delete()


@requires_postgres
def test_postgres_trigger_blocks_observation_tampering(nms):
    ingest(nms, switch_record())

    for sql in (
        "UPDATE observations_observation SET external_id = 'x'",
        "DELETE FROM observations_observation",
    ):
        with pytest.raises(DatabaseError), transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute(sql)
    assert Observation.objects.get().external_id == "317"


def test_load_observations_command_with_committed_fixture(nms, settings):
    import io
    from pathlib import Path

    from django.core.management import call_command

    fixture = Path(settings.BASE_DIR).parent / "fixtures" / "discovery" / "network_devices.json"
    out = io.StringIO()
    call_command(
        "load_observations",
        "--instance",
        "NMS HQ",
        "--file",
        str(fixture),
        "--mode",
        "full",
        stdout=out,
    )

    assert "succeeded" in out.getvalue()
    assert ReconciliationCandidate.objects.count() >= 4
    assert Asset.objects.count() == 0
