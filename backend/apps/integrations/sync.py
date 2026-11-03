"""Connector orchestration: live-access gate, connection test, queued/scheduled runs,
progress, evidence and run finalisation.

No request reaches a source unless BOTH the deployment allows live integrations
(ITAM_ALLOW_LIVE_INTEGRATIONS) AND an administrator recorded approval on the
instance (who, when, why). Fixture loading (load_observations) never contacts a source.
"""

import logging
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.audit import services as audit
from apps.network.models import NeighborEvidence
from apps.reconciliation import services as reconciliation

from . import secrets
from .adapters.base import AuthError, SourceError
from .adapters.librenms import adapter as librenms
from .adapters.librenms.client import LibreNMSClient
from .models import IntegrationInstance, SyncRun

logger = logging.getLogger(__name__)
ADAPTERS = {"librenms"}
HEARTBEAT_TIMEOUT = timedelta(minutes=30)
ACTIVE = (SyncRun.Status.QUEUED, SyncRun.Status.RUNNING)

# Tests replace this to serve sanitized fixtures through httpx.MockTransport.
TRANSPORT_FACTORY = None
RESOLVER = None
SLEEP = None  # tests: record throttle/backoff waits instead of sleeping


class SyncRefused(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def has_adapter(instance: IntegrationInstance) -> bool:
    return instance.source_id in ADAPTERS


def check_live_access(instance: IntegrationInstance) -> None:
    if not has_adapter(instance):
        raise SyncRefused("NO_ADAPTER", "This source has no adapter; it cannot be synchronised.")
    if not getattr(settings, "ITAM_ALLOW_LIVE_INTEGRATIONS", False):
        raise SyncRefused(
            "LIVE_INTEGRATIONS_DISABLED",
            "Live integrations are disabled for this deployment (ITAM_ALLOW_LIVE_INTEGRATIONS).",
        )
    if not instance.live_access_approved:
        raise SyncRefused(
            "LIVE_ACCESS_NOT_APPROVED",
            "An administrator must record approval for live access to this source first.",
        )
    if not instance.base_url:
        raise SyncRefused("NOT_CONFIGURED", "Set the source base URL first.")


def build_client(instance: IntegrationInstance) -> LibreNMSClient:
    check_live_access(instance)
    try:
        token = secrets.resolve(instance.credential_ref)
        verify = secrets.resolve_path(instance.ca_bundle_ref) or True
    except secrets.SecretError as exc:
        raise SyncRefused("CREDENTIAL_UNAVAILABLE", str(exc)) from exc
    return LibreNMSClient(
        instance.base_url,
        token,
        auth_scheme=instance.auth_scheme,
        timeout=instance.timeout_seconds,
        max_retries=instance.max_retries,
        requests_per_second=instance.requests_per_second,
        verify=verify,
        transport=TRANSPORT_FACTORY(instance) if TRANSPORT_FACTORY else None,
        resolver=RESOLVER,
        **({"sleep": SLEEP} if SLEEP else {}),
    )


# --- Connection test -------------------------------------------------------------------


def test_connection(request, instance: IntegrationInstance) -> dict:
    result = {"ok": False, "message": "", "version": "", "capabilities": {}}
    try:
        with build_client(instance) as client:
            details = librenms.test_connection(client)
        result.update(
            ok=True,
            message="Connected. Read-only API access works.",
            **{"version": details["version"], "capabilities": details["capabilities"]},
        )
    except SyncRefused as exc:
        result["message"] = str(exc)
    except SourceError as exc:
        result["message"] = str(exc)
    instance.last_test_at = timezone.now()
    instance.last_test_ok = result["ok"]
    instance.last_test_message = result["message"][:500]
    if result["ok"]:
        instance.source_software_version = result["version"]
        instance.capabilities = result["capabilities"]
    instance.save(
        update_fields=[
            "last_test_at",
            "last_test_ok",
            "last_test_message",
            "source_software_version",
            "capabilities",
            "modified_at",
        ]
    )
    audit.record(
        action="integrations.test_connection",
        actor=request.user,
        request=request,
        object_type="integration",
        object_id=instance.pk,
        object_label=instance.name,
        outcome="success" if result["ok"] else "failure",
        detail=result["message"][:500],
    )
    return result


# --- Queueing and scheduling --------------------------------------------------------------


def _abandon_stale(instance) -> None:
    cutoff = timezone.now() - HEARTBEAT_TIMEOUT
    SyncRun.objects.filter(instance=instance, status__in=ACTIVE).filter(
        Q(heartbeat_at__lt=cutoff) | Q(heartbeat_at__isnull=True, started_at__lt=cutoff)
    ).update(
        status=SyncRun.Status.FAILED,
        finished_at=timezone.now(),
        error_message="Abandoned: no heartbeat.",
    )


def queue_sync(instance: IntegrationInstance, *, mode: str, triggered_by: str) -> SyncRun:
    """Create a queued run (refused if one is active) and hand it to the worker."""
    if not instance.is_enabled:
        raise SyncRefused("INTEGRATION_DISABLED", "The integration is disabled.")
    check_live_access(instance)
    with transaction.atomic():
        IntegrationInstance.objects.select_for_update().get(pk=instance.pk)
        _abandon_stale(instance)
        if SyncRun.objects.filter(instance=instance, status__in=ACTIVE).exists():
            raise SyncRefused("SYNC_IN_PROGRESS", "A synchronisation is already queued or running.")
        run = SyncRun.objects.create(
            instance=instance,
            mode=mode,
            triggered_by=triggered_by[:150],
            status=SyncRun.Status.QUEUED,
            heartbeat_at=timezone.now(),
        )
    from .tasks import run_sync_task

    transaction.on_commit(lambda: run_sync_task.delay(str(run.pk)))
    return run


def due_instances(now=None):
    now = now or timezone.now()
    for instance in IntegrationInstance.objects.filter(is_enabled=True, live_access_approved=True):
        if not has_adapter(instance):
            continue
        last = instance.last_attempt_at
        if last is None or now - last >= timedelta(minutes=instance.sync_interval_minutes):
            yield instance


def dispatch_due(now=None) -> int:
    queued = 0
    for instance in due_instances(now):
        try:
            queue_sync(instance, mode=SyncRun.Mode.FULL, triggered_by="schedule")
            queued += 1
        except SyncRefused as exc:
            logger.info("Scheduled sync for %s skipped: %s", instance.name, exc)
    return queued


# --- Execution ---------------------------------------------------------------------------


def execute(run_id) -> SyncRun:
    run = SyncRun.objects.select_related("instance__source").get(pk=run_id)
    if run.status != SyncRun.Status.QUEUED:
        return run
    instance = run.instance
    run.status = SyncRun.Status.RUNNING
    run.heartbeat_at = timezone.now()
    run.save(update_fields=["status", "heartbeat_at"])

    def progress(_=None):
        run.heartbeat_at = timezone.now()
        SyncRun.objects.filter(pk=run.pk).update(
            phase=run.phase,
            devices_total=run.devices_total,
            devices_processed=run.devices_processed,
            devices_enriched=run.devices_enriched,
            checkpoint=run.checkpoint,
            heartbeat_at=run.heartbeat_at,
            warnings=run.warnings,
            warning_samples=run.warning_samples,
        )

    try:
        with build_client(instance) as client:
            adapter = librenms.LibreNMSAdapter(instance, client)
            if not adapter.caps:
                adapter.caps = librenms.discover_capabilities(client)
                IntegrationInstance.objects.filter(pk=instance.pk).update(capabilities=adapter.caps)
            records, complete = adapter.collect(run, progress)
            run.phase = "reconciliation"
            progress()
            run = reconciliation.ingest(
                instance,
                records,
                mode=run.mode,
                triggered_by=run.triggered_by,
                run=run,
                complete=complete,
                on_progress=progress,
            )
            if _evidence_due(instance):
                run.phase = "evidence"
                progress()
                _store_evidence(instance, run, adapter)
            run.api_requests = client.requests
    except (SyncRefused, AuthError, SourceError) as exc:
        _fail(run, instance, exc)
        return run
    except Exception as exc:
        _fail(run, instance, SourceError(f"Internal error ({type(exc).__name__})."))
        raise
    run.phase = "done"
    run.heartbeat_at = timezone.now()
    run.save()
    return run


def _fail(run, instance, exc) -> None:
    code = getattr(exc, "code", "SOURCE_ERROR")
    run.status = SyncRun.Status.FAILED
    run.phase = "failed"
    run.finished_at = timezone.now()
    run.error_message = f"{code}: {exc}"[:500]
    run.save()
    instance.last_attempt_at = run.finished_at
    instance.last_error = run.error_message
    instance.status = IntegrationInstance.Status.DEGRADED
    instance.consecutive_failures += 1
    instance.save(
        update_fields=[
            "last_attempt_at",
            "last_error",
            "status",
            "consecutive_failures",
            "modified_at",
        ]
    )
    logger.warning("Sync %s for %s failed: %s", run.pk, instance.name, code)


def _evidence_due(instance) -> bool:
    last = instance.last_evidence_at
    return last is None or timezone.now() - last >= timedelta(
        hours=instance.evidence_interval_hours
    )


def _port_names(adapter) -> dict[str, str]:
    """port_id → name for the IP-bearing ports read (or reused) in this run."""
    return dict(getattr(adapter, "port_names", {}))


def _store_evidence(instance, run, adapter) -> None:
    try:
        fdb, links, skipped = adapter.collect_evidence()
    except AuthError:
        raise
    except SourceError as exc:
        adapter._warn(run, None, f"Evidence pass skipped: {exc}")
        return
    for note in skipped:
        adapter._warn(run, None, f"Not collected: {note}.")
    from apps.assets.network import normalize_mac

    now = timezone.now()
    ports = _port_names(adapter)
    rows = {}
    for row in fdb:
        try:
            mac = normalize_mac(str(row.get("mac_address") or ""))
        except ValueError:
            continue
        if not mac:
            continue
        key = (
            "fdb",
            str(row.get("device_id")),
            ports.get(str(row.get("port_id")), f"port {row.get('port_id')}"),
            mac,
            "",
            "",
            "",
            str(row.get("vlan_id") or ""),
        )
        rows[key] = {}
    for row in links:
        protocol = str(row.get("protocol") or "").lower()
        kind = protocol if protocol in ("lldp", "cdp") else "other"
        key = (
            kind,
            str(row.get("local_device_id")),
            ports.get(str(row.get("local_port_id")), f"port {row.get('local_port_id')}"),
            "",
            str(row.get("remote_device_id") or ""),
            str(row.get("remote_hostname") or "")[:253],
            str(row.get("remote_port") or "")[:100],
            "",
        )
        rows[key] = {"remote_platform": str(row.get("remote_platform") or "")[:200]}

    fields = [
        "kind",
        "local_external_id",
        "local_port",
        "remote_mac",
        "remote_external_id",
        "remote_hostname",
        "remote_port",
        "vlan",
    ]
    existing = {
        tuple(values[1:]): values[0]
        for values in NeighborEvidence.objects.filter(instance=instance).values_list("id", *fields)
    }
    to_create, seen_ids = [], []
    for key, extra in rows.items():
        if key in existing:
            seen_ids.append(existing[key])
        else:
            to_create.append(
                NeighborEvidence(
                    instance=instance,
                    **dict(zip(fields, key, strict=True)),
                    first_seen_at=now,
                    last_seen_at=now,
                    last_run=run,
                    **extra,
                )
            )
    with transaction.atomic():
        NeighborEvidence.objects.bulk_create(to_create, batch_size=2000)
        for start in range(0, len(seen_ids), 5000):
            NeighborEvidence.objects.filter(pk__in=seen_ids[start : start + 5000]).update(
                last_seen_at=now, is_active=True, last_run=run
            )
        if not skipped:  # only a complete pass may retire rows
            NeighborEvidence.objects.filter(instance=instance, is_active=True).exclude(
                last_run=run
            ).update(is_active=False)
    run.evidence_rows = len(rows)
    IntegrationInstance.objects.filter(pk=instance.pk).update(last_evidence_at=now)


# --- Approval ----------------------------------------------------------------------------


def set_live_access(
    request, instance: IntegrationInstance, approved: bool, reason: str
) -> IntegrationInstance:
    with transaction.atomic():
        instance = IntegrationInstance.objects.select_for_update().get(pk=instance.pk)
        before = {"live_access_approved": instance.live_access_approved}
        instance.live_access_approved = approved
        instance.live_access_reason = reason
        instance.live_access_approved_by = request.user if approved else None
        instance.live_access_approved_at = timezone.now() if approved else None
        instance.save()
        audit.record(
            action="integrations.live_access_" + ("approve" if approved else "revoke"),
            actor=request.user,
            request=request,
            object_type="integration",
            object_id=instance.pk,
            object_label=instance.name,
            before=before,
            after={"live_access_approved": approved},
            detail=reason,
        )
    return instance
