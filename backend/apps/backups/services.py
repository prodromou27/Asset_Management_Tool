from datetime import datetime, timedelta

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.accounts.models import User
from apps.audit import services as audit
from apps.notifications import services as mail
from config.api import ApiError

from . import runner
from .models import BackupJob, BackupPolicy, RestoreDrill


def policy():
    return BackupPolicy.objects.get_or_create(pk=1)[0]


def gate():
    if not settings.ITAM_BACKUP_ALLOW_RUN:
        raise ApiError(
            "BACKUP_DISABLED", "Backup execution awaits deployment approval (DEC-09).", 409
        )


def alert(message, dedup):
    # Reuse the existing disabled-by-default SMTP outbox. No fixed external recipients.
    if not mail.get_profile().enabled:
        return
    for user in User.objects.filter(is_active=True).exclude(email=""):
        if "backups.manage" in user.permission_codes():
            mail.enqueue(
                "backup_alert",
                user.email,
                {"message": message},
                event_type="backup_alert",
                dedup_key=f"backup:{dedup}:{user.pk}",
            )


def kick(job):
    from .tasks import execute

    try:
        execute.apply_async(args=[str(job.pk)], queue="backups")
    except Exception:
        # Dispatch is retried by the periodic dispatcher; no command is lost.
        pass


def request_job(kind="backup", *, actor=None, source=None, request=None):
    gate()
    if source and (source.kind != "backup" or source.status != "succeeded"):
        raise ApiError("INVALID_BACKUP", "Choose a successfully verified backup.", 422)
    try:
        with transaction.atomic():
            job = BackupJob.objects.create(
                kind=kind,
                source=source,
                created_by=actor,
                target_label=settings.ITAM_BACKUP_TARGET_LABEL,
                snapshot_id=source.snapshot_id if source else "",
                manifest=source.manifest if source else {},
                recovery_point=source.recovery_point if source else None,
                size_bytes=source.size_bytes if source else 0,
            )
            audit.record(
                action=f"backups.request_{kind}",
                actor=actor,
                request=request,
                object_type="backup_job",
                object_id=job.pk,
            )
            transaction.on_commit(lambda: kick(job))
            return job
    except IntegrityError as exc:
        raise ApiError(
            "BACKUP_BUSY", "A backup or verification is already queued or running.", 409
        ) from exc


def execute(job_id):
    now = timezone.now()
    if not BackupJob.objects.filter(pk=job_id, status="queued").update(
        status="running", started_at=now
    ):
        return
    job = BackupJob.objects.get(pk=job_id)
    try:
        gate()  # A deployment revocation also stops queued jobs.
        if job.created_by and (
            not job.created_by.is_active
            or "backups.manage" not in job.created_by.permission_codes()
        ):
            raise runner.RunnerError(
                "The requesting user no longer has backup administration access."
            )
        if job.kind == "backup":
            snapshot, manifest = runner.backup(job.id)
            job.snapshot_id = snapshot
            job.manifest = manifest
            job.size_bytes = manifest["size_bytes"]
            job.recovery_point = datetime.fromisoformat(manifest["recovery_point"])
        else:
            runner.verify(job.snapshot_id, job.manifest, runner.repository_env())
        job.status = "succeeded"
    except Exception as exc:
        job.status = "failed"
        job.error_message = (
            str(exc)[:300]
            if isinstance(exc, runner.RunnerError)
            else ("Backup failed. Review configuration in the restricted operator environment.")
        )
    if job.status == "succeeded" and job.kind == "backup":
        try:
            runner.retention(policy())
        except Exception:
            job.warning = "Backup verified; retention failed. Review retention with an operator."
            audit.record(
                action="backups.retention_failed",
                actor_label="backup-runner",
                source="system",
                outcome="failure",
                object_type="backup_job",
                object_id=job.pk,
                detail=job.warning,
            )
            alert(job.warning, f"retention:{job.pk}")
    job.finished_at = timezone.now()
    job.active_slot = None
    job.save()
    audit.record(
        action=f"backups.{job.kind}_{job.status}",
        actor_label="backup-runner",
        source="system",
        outcome="success" if job.status == "succeeded" else "failure",
        object_type="backup_job",
        object_id=job.pk,
        after={"status": job.status, "snapshot_id": job.snapshot_id},
        detail=job.error_message,
    )
    if job.status == "failed":
        alert(job.error_message, str(job.pk))


def dispatch():
    if not settings.ITAM_BACKUP_ALLOW_RUN:
        return
    now = timezone.now()
    # Never release an active slot on a timeout: the process may still be writing. An
    # operator must establish the worker is stopped before clearing a stranded job.
    for job in BackupJob.objects.filter(status__in=["queued", "running"]):
        if job.created_at < now - timedelta(hours=6):
            alert(
                "A backup job has been active for over six hours. Check the backup worker.",
                f"stuck:{job.pk}:{now.date()}",
            )
        if job.status == "queued":
            kick(job)
    p = policy()
    if not p.enabled:
        return
    latest = BackupJob.objects.filter(kind="backup", status="succeeded").first()
    if not latest or latest.recovery_point < now - timedelta(hours=p.rpo_hours):
        alert(
            "The recovery point exceeds the configured RPO, or no verified backup exists.",
            f"stale:{now.date()}",
        )
    start = now.replace(hour=p.hour_utc, minute=0, second=0, microsecond=0)
    if now < start:
        start -= timedelta(days=1)
    if not BackupJob.objects.filter(kind="backup", created_at__gte=start).exists():
        try:
            request_job()
        except ApiError:
            pass  # An active verification owns the singleton slot.


def summary():
    p = policy()
    last = BackupJob.objects.filter(kind="backup", status="succeeded").first()
    drill = RestoreDrill.objects.first()
    problems = []
    if not settings.ITAM_BACKUP_ALLOW_RUN:
        problems.append(
            "Setup incomplete: deployment approval and repository/key provisioning needed (DEC-09)."
        )
    if not p.enabled:
        problems.append("Nightly backups are disabled.")
    if not last:
        problems.append("No verified backup recorded.")
    elif last.recovery_point < timezone.now() - timedelta(hours=p.rpo_hours):
        problems.append("The last verified recovery point exceeds the RPO objective.")
    if not drill:
        problems.append("No isolated restore drill recorded.")
    elif not drill.passed or drill.finished_at < timezone.now() - timedelta(days=31):
        problems.append("The latest restore drill failed or is over 31 days old.")
    elif drill.finished_at - drill.started_at > timedelta(hours=p.rto_hours):
        problems.append("The latest recorded restore duration exceeds the RTO objective.")
    if BackupJob.objects.filter(status="failed").exists():
        latest_job = BackupJob.objects.first()
        if latest_job.status == "failed":
            problems.append("The latest backup operation failed.")
    return {
        "execution_allowed": settings.ITAM_BACKUP_ALLOW_RUN,
        "target_label": settings.ITAM_BACKUP_TARGET_LABEL,
        "encryption": "Restic authenticated encryption; key custody approval required",
        "off_host": "SFTP repository required; validate physical separation at commissioning",
        "last_backup": last,
        "last_drill": drill,
        "problems": problems,
    }
