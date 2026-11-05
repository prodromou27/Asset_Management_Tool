"""Export job lifecycle: create (202) -> worker builds the file -> creator downloads until
expiry -> file purged (Task 014, docs/04 "Background job created returns 202").

Security (docs/14 data exfiltration):
- the worker re-reads the creator's permissions and site scope when it runs, so access
  removed after queueing is honoured;
- personal-data columns need ``exports.personal`` and are masked at query time;
- files are Fernet-encrypted at rest, downloadable only by their creator, only while
  unexpired, and every create, completion, failure and download is audited.
"""

import hashlib
import json
import logging
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from apps.accounts import catalog
from apps.audit import services as audit
from apps.audit.models import AuditEvent
from apps.imports import crypto
from config.api import ApiError

from . import families, writers
from .models import ExportJob

logger = logging.getLogger(__name__)

ACTIVE_JOB_LIMIT = 3
MAX_SELECTED_IDS = 10_000
ACTIVE = (ExportJob.Status.QUEUED, ExportJob.Status.RUNNING)


def family_or_404(code: str) -> families.Family:
    family = families.FAMILIES.get(code)
    if family is None:
        raise ApiError("NOT_FOUND", f"Unknown export family '{code}'.", 404)
    return family


def _denied() -> ApiError:
    return ApiError("PERMISSION_DENIED", "You do not have permission to export this data.", 403)


def can_export(user, family: families.Family) -> bool:
    granted = user.permission_codes()
    allowed = catalog.EXPORTS_RUN in granted and family.permission in granted
    if family.code.startswith("report_"):
        from apps.reports.services import can_view

        allowed = allowed and can_view(user, family.code.removeprefix("report_"))
    return allowed


def authorization_fingerprint(user):
    from apps.accounts.models import User
    from apps.organizations.scope import accessible_site_ids

    fresh = User.objects.get(pk=user.pk)
    sites = accessible_site_ids(fresh)
    policy = [
        fresh.is_active,
        sorted(fresh.permission_codes()),
        "all" if sites is None else sorted(str(pk) for pk in sites),
    ]
    return hashlib.sha256(json.dumps(policy).encode()).hexdigest()


def describe(family: families.Family, user) -> dict:
    """Columns and related tables this user may choose, for the export dialog."""
    granted = user.permission_codes()
    personal = catalog.EXPORTS_PERSONAL in granted
    return {
        "code": family.code,
        "label": family.label,
        "description": family.description,
        "allowed": can_export(user, family),
        "filter_keys": list(family.filter_keys),
        "columns": [
            {
                "key": c.key,
                "label": c.label,
                "personal": c.personal,
                "allowed": personal or not c.personal,
            }
            for c in family.columns()
        ],
        "related": [
            {"key": r.key, "label": r.label} for r in families.allowed_related(family, granted)
        ],
        "personal_data_allowed": personal,
    }


def create_job(request, data: dict) -> ExportJob:
    user = request.user
    family = family_or_404(data["family"])
    if not can_export(user, family):
        raise _denied()

    errors: dict[str, list[str]] = {}
    available = {c.key for c in family.columns()}
    unknown = [c for c in data.get("columns", []) if c not in available]
    if unknown:
        errors["columns"] = [f"Unknown columns: {', '.join(unknown)}."]
    permitted = {r.key for r in families.allowed_related(family, user.permission_codes())}
    refused = [r for r in data.get("related", []) if r not in permitted]
    if refused:
        errors["related"] = [f"Not available to you: {', '.join(refused)}."]
    filters = data.get("filters") or {}
    if family.code.startswith("report_"):
        from apps.reports.services import clean_filters

        if data["scope"] == "selected":
            raise ApiError("VALIDATION_ERROR", "Reports use filtered or all-authorized scope.", 422)
        filters = clean_filters(user, family.code.removeprefix("report_"), filters)
    bad_filters = [k for k in filters if k not in family.filter_keys]
    if bad_filters:
        errors["filters"] = [f"Unknown filters: {', '.join(bad_filters)}."]
    ids = [str(i) for i in data.get("ids") or []]
    if data["scope"] == ExportJob.Scope.SELECTED:
        if not ids:
            errors["ids"] = ["Select at least one record."]
        elif len(ids) > MAX_SELECTED_IDS:
            errors["ids"] = [f"Select at most {MAX_SELECTED_IDS:,} records."]
    if errors:
        raise ApiError("VALIDATION_ERROR", "The export request is not valid.", 422, errors)

    if ExportJob.objects.filter(created_by=user, status__in=ACTIVE).count() >= ACTIVE_JOB_LIMIT:
        raise ApiError(
            "EXPORT_LIMIT",
            f"You already have {ACTIVE_JOB_LIMIT} exports in progress. Wait for one to finish.",
            429,
        )

    with transaction.atomic():
        job = ExportJob.objects.create(
            family=family.code,
            file_format=data["format"],
            scope=data["scope"],
            filters=filters if data["scope"] == ExportJob.Scope.FILTERED else {},
            ids=ids if data["scope"] == ExportJob.Scope.SELECTED else [],
            columns=list(dict.fromkeys(data.get("columns", []))),
            related=list(dict.fromkeys(data.get("related", []))),
            created_by=user,
        )
        audit.record(
            action="exports.create",
            actor=user,
            request=request,
            object_type="export",
            object_id=job.pk,
            object_label=family.label,
            after={
                "family": job.family,
                "format": job.file_format,
                "scope": job.scope,
                "filters": job.filters,
                "selected": len(job.ids),
                "related": job.related,
            },
        )
        from .tasks import run_export

        transaction.on_commit(lambda: run_export.delay(str(job.pk)))
    return job


def _fail(job: ExportJob, message: str) -> ExportJob:
    job.status = ExportJob.Status.FAILED
    job.error_message = message[:500]
    job.completed_at = timezone.now()
    job.save(update_fields=["status", "error_message", "completed_at"])
    audit.record(
        action="exports.fail",
        actor=job.created_by,
        object_type="export",
        object_id=job.pk,
        object_label=job.family,
        outcome=AuditEvent.Outcome.FAILURE,
        source=AuditEvent.Source.SYSTEM,
        detail=job.error_message,
    )
    return job


def run_export(job_id) -> ExportJob:
    with transaction.atomic():
        job = (
            ExportJob.objects.select_for_update()
            .select_related("created_by")
            .filter(pk=job_id)
            .first()
        )
        if job is None or job.status != ExportJob.Status.QUEUED:
            return job
        job.status = ExportJob.Status.RUNNING
        job.started_at = timezone.now()
        job.save(update_fields=["status", "started_at"])

    user = job.created_by
    family = families.FAMILIES.get(job.family)
    if family is None or not can_export(user, family):
        return _fail(job, "Your permission to export this data was removed before it ran.")
    try:
        fingerprint = authorization_fingerprint(user)
        data = families.build(job, user, settings.ITAM_EXPORT_MAX_ROWS)
        now = timezone.now()
        meta = {
            "family": family.code,
            "family_label": family.label,
            "exported_at": now.isoformat(),
            "exported_by": user.username,
            "scope": job.scope,
            "scope_label": ExportJob.Scope(job.scope).label,
            "filters": job.filters,
        }
        body, extension, content_type = writers.WRITERS[job.file_format](data, meta)
    except families.ExportTooLarge as exc:
        return _fail(job, str(exc))
    except Exception:  # noqa: BLE001 - recorded on the job; details only in the server log
        logger.exception("Export %s failed", job.pk)
        return _fail(job, "The export could not be created. Try again or contact an admin.")

    job.row_count = len(data.main.rows)
    job.related_counts = {name: len(t.rows) for name, t in data.related.items()}
    job.masked_columns = data.masked
    job.filename = writers.filename(family.code, extension, now)
    job.content_type = content_type
    job.size_bytes = len(body)
    job.checksum = hashlib.sha256(body).hexdigest()
    job.authorization_fingerprint = fingerprint
    job.file_encrypted = crypto.encrypt(body, crypto.EXPORTS)
    job.status = ExportJob.Status.COMPLETED
    job.completed_at = now
    job.expires_at = now + timedelta(hours=settings.ITAM_EXPORT_RETENTION_HOURS)
    job.save()
    audit.record(
        action="exports.complete",
        actor=user,
        object_type="export",
        object_id=job.pk,
        object_label=job.filename,
        source=AuditEvent.Source.SYSTEM,
        after={
            "rows": job.row_count,
            "related": job.related_counts,
            "masked": job.masked_columns,
            "checksum": job.checksum,
        },
    )
    return job


def download(request, job: ExportJob) -> tuple[bytes, ExportJob]:
    user = request.user
    if job.created_by_id != user.pk:
        raise ApiError(
            "PERMISSION_DENIED", "Only the person who created an export can download it.", 403
        )
    family = families.FAMILIES.get(job.family)
    if family is None or not can_export(user, family):
        raise _denied()
    if job.status == ExportJob.Status.EXPIRED or (
        job.expires_at and job.expires_at <= timezone.now()
    ):
        raise ApiError("EXPORT_EXPIRED", "This export has expired. Create a new one.", 410)
    if job.status != ExportJob.Status.COMPLETED or job.file_encrypted is None:
        raise ApiError("EXPORT_NOT_READY", "This export is not ready yet.", 409)
    if (
        not job.authorization_fingerprint
        or job.authorization_fingerprint != authorization_fingerprint(user)
    ):
        raise ApiError(
            "EXPORT_ACCESS_CHANGED",
            "Export authorization is unavailable or changed. Create a fresh export.",
            403,
        )
    body = crypto.decrypt(job.file_encrypted, crypto.EXPORTS)
    if body is None:
        raise ApiError("EXPORT_UNREADABLE", "The stored file cannot be decrypted.", 409)
    ExportJob.objects.filter(pk=job.pk).update(
        download_count=F("download_count") + 1, last_downloaded_at=timezone.now()
    )
    audit.record(
        action="exports.download",
        actor=user,
        request=request,
        object_type="export",
        object_id=job.pk,
        object_label=job.filename,
        after={"rows": job.row_count, "size_bytes": job.size_bytes},
    )
    return body, job


def purge_expired(now=None) -> int:
    """Delete files past their expiry; the job row remains as the export record."""
    now = now or timezone.now()
    return ExportJob.objects.filter(status=ExportJob.Status.COMPLETED, expires_at__lte=now).update(
        status=ExportJob.Status.EXPIRED, file_encrypted=None, purged_at=now
    )


def fail_stuck(now=None, minutes: int = 60) -> int:
    """Jobs left running by a crashed worker become failed instead of blocking the user."""
    now = now or timezone.now()
    return ExportJob.objects.filter(
        status__in=ACTIVE, created_at__lte=now - timedelta(minutes=minutes)
    ).update(
        status=ExportJob.Status.FAILED,
        error_message="The export did not finish in time. Try again.",
        completed_at=now,
    )
