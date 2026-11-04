"""Import workflow (docs/11 wizard): upload → map → dry run → commit → (rollback).

- Upload parses the file with hard limits, stores it encrypted and suggests a mapping.
- Preview (dry run) plans every row without writing business data; totals per action.
- Commit re-plans each row against the current data (it may have changed since the
  preview) and applies only creates/updates, each in its own savepoint; one failing row
  never undoes the others. Missing rows never delete or archive anything.
- Rollback undoes rows whose record has not changed since the import; other rows are
  listed for supervised correction.
"""

import csv
import hashlib
import io
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.db.models import Count, F
from django.utils import timezone
from rest_framework import serializers

from apps.audit import services as audit
from config.api import ApiError

from . import crypto, parsing
from .families import FAMILIES, Context, RowError
from .models import ImportJob, ImportRow

RETENTION_DAYS = 90


def family_or_404(code: str):
    family = FAMILIES.get(code)
    if family is None:
        raise serializers.ValidationError({"family": ["Unknown import family."]})
    return family


def _normal(name: str) -> str:
    return "".join(ch for ch in name.lower() if ch.isalnum())


def suggest_mapping(family, headers: list[str]) -> dict[str, str]:
    """Map file columns to template fields by name, label or alias; cf.<key> columns map
    to custom fields for families that allow them."""
    index: dict[str, str] = {}
    for column in family.columns:
        for name in (column.name, column.label, *column.aliases):
            index.setdefault(_normal(name), column.name)
    mapping = {}
    used: set[str] = set()
    for header in headers:
        target = index.get(_normal(header), "")
        if not target and family.allow_custom_columns and header.lower().startswith("cf."):
            target = "cf." + header[3:].strip()
        if target in used:
            target = ""
        if target:
            used.add(target)
        mapping[header] = target
    return mapping


def validate_mapping(family, headers: list[str], mapping: dict) -> dict[str, str]:
    allowed = family.field_names()
    clean, used = {}, set()
    for header in headers:
        target = (mapping.get(header) or "").strip()
        if (
            target
            and target not in allowed
            and not (family.allow_custom_columns and target.startswith("cf.") and len(target) > 3)
        ):
            raise serializers.ValidationError(
                {"mapping": [f"{header!r}: unknown field {target!r}."]}
            )
        if target and target in used:
            raise serializers.ValidationError(
                {"mapping": [f"Field {target!r} is mapped from more than one column."]}
            )
        if target:
            used.add(target)
        clean[header] = target
    required = [c.name for c in family.columns if c.required == "always" and c.name not in used]
    if required:
        raise serializers.ValidationError(
            {"mapping": [f"Map a column to the required field(s): {', '.join(required)}."]}
        )
    match = [c.name for c in family.columns if c.required in ("match", "create")]
    if match and not used & set(match):
        raise serializers.ValidationError(
            {"mapping": [f"Map at least one of: {', '.join(match)}."]}
        )
    return clean


def create_job(request, family_code: str, upload) -> ImportJob:
    family = family_or_404(family_code)
    _check_permission(request.user, family)
    data = upload.read(parsing.MAX_BYTES + 1)
    try:
        parsed = parsing.parse(data, upload.name or "")
    except parsing.ParseError as exc:
        raise serializers.ValidationError({"file": [str(exc)]}) from exc
    checksum = hashlib.sha256(data).hexdigest()
    warnings = list(parsed.warnings)
    previous = (
        ImportJob.objects.filter(family=family.code, checksum=checksum, status="completed")
        .order_by("-completed_at")
        .first()
    )
    if previous is not None:
        warnings.append(
            f"This exact file was already imported on {previous.completed_at:%Y-%m-%d %H:%M} "
            f"(import {previous.pk}). Rows that match by id or tag will show as unchanged."
        )
    retention = getattr(settings, "ITAM_IMPORT_RETENTION_DAYS", RETENTION_DAYS)
    job = ImportJob.objects.create(
        family=family.code,
        template_version=family.version,
        filename=(upload.name or "upload")[-255:].replace("/", "_").replace("\\", "_"),
        file_format=parsed.file_format,
        size_bytes=len(data),
        checksum=checksum,
        encoding=parsed.encoding,
        delimiter=parsed.delimiter,
        sheet=parsed.sheet,
        headers=parsed.headers,
        mapping=suggest_mapping(family, parsed.headers),
        row_count=len(parsed.rows),
        warnings=warnings,
        file_encrypted=crypto.encrypt(data),
        purge_after=timezone.now() + timedelta(days=retention),
        created_by=request.user,
    )
    audit.record(
        action="imports.upload",
        actor=request.user,
        request=request,
        object_type="import",
        object_id=job.pk,
        object_label=job.filename,
        after={"family": job.family, "rows": job.row_count, "checksum": checksum},
    )
    return job


def sample_rows(job: ImportJob, limit: int = 5) -> list[list[str]]:
    parsed = _parsed(job)
    return [[parsing.escape_cell(v) for v in row] for row in parsed.rows[:limit]]


def _parsed(job: ImportJob) -> parsing.Parsed:
    if job.file_encrypted is None:
        raise ApiError("IMPORT_FILE_PURGED", "The original file is no longer kept.", 409)
    data = crypto.decrypt(job.file_encrypted)
    if data is None:
        raise ApiError("IMPORT_FILE_UNREADABLE", "The stored file cannot be decrypted.", 409)
    return parsing.parse(data, job.filename, job.sheet)


def _row_values(job: ImportJob, headers, row) -> dict[str, str]:
    return {job.mapping[h]: v for h, v in zip(headers, row, strict=True) if job.mapping.get(h)}


def update_job(request, job: ImportJob, data: dict, expected_version) -> ImportJob:
    from apps.organizations.services import check_version

    family = family_or_404(job.family)
    with transaction.atomic():
        job = ImportJob.objects.select_for_update().get(pk=job.pk)
        check_version(job, expected_version)
        if job.status not in (ImportJob.Status.UPLOADED, ImportJob.Status.PREVIEWED):
            raise ApiError("IMPORT_LOCKED", "This import can no longer be changed.", 409)
        if "mapping" in data:
            job.mapping = validate_mapping(family, job.headers, data["mapping"])
        if "mode" in data:
            job.mode = data["mode"]
        job.status = ImportJob.Status.UPLOADED  # any change invalidates the preview
        job.totals = {}
        job.version = F("version") + 1
        job.save()
        job.rows.all().delete()
        job.refresh_from_db()
    return job


def _context(job: ImportJob, user) -> Context:
    return Context(user, job.mode, job)


def run_preview(job_id) -> ImportJob:
    """Dry run: plan every row, store planned actions and totals. No business writes."""
    job = ImportJob.objects.select_related("created_by").get(pk=job_id)
    try:
        return _preview(job)
    except (ApiError, parsing.ParseError, serializers.ValidationError) as exc:
        detail = getattr(exc, "detail", None) or str(exc)
        ImportJob.objects.filter(pk=job.pk).update(
            status=ImportJob.Status.UPLOADED,
            error_message=str(detail)[:500],
            version=F("version") + 1,
        )
        job.refresh_from_db()
        return job
    except Exception as exc:
        # Never leave a job stuck in "previewing": report and let the user retry.
        ImportJob.objects.filter(pk=job.pk).update(
            status=ImportJob.Status.UPLOADED,
            error_message=f"The check failed unexpectedly ({type(exc).__name__}); try again.",
            version=F("version") + 1,
        )
        raise


def _preview(job: ImportJob) -> ImportJob:
    family = family_or_404(job.family)
    validate_mapping(family, job.headers, job.mapping)
    parsed = _parsed(job)
    ctx = _context(job, job.created_by)
    rows = []
    for number, raw in enumerate(parsed.rows, start=1):
        values = _row_values(job, parsed.headers, raw)
        plan = family.plan(ctx, values, number)
        rows.append(
            ImportRow(
                job=job,
                row_number=number,
                action=plan.action,
                key=plan.key[:300],
                target_id=plan.target_id,
                target_label=plan.target_label[:200],
                messages=plan.messages,
                values=values,
                changes=plan.changes,
            )
        )
    with transaction.atomic():
        job.rows.all().delete()
        ImportRow.objects.bulk_create(rows, batch_size=1000)
        totals = {a: 0 for a in ImportRow.Action.values}
        for row in rows:
            totals[row.action] += 1
        ImportJob.objects.filter(pk=job.pk).update(
            status=ImportJob.Status.PREVIEWED,
            error_message="",
            totals=totals,
            previewed_at=timezone.now(),
            version=F("version") + 1,
        )
    job.refresh_from_db()
    return job


def start_preview(request, job: ImportJob, expected_version) -> ImportJob:
    from apps.organizations.services import check_version

    with transaction.atomic():
        job = ImportJob.objects.select_for_update().get(pk=job.pk)
        check_version(job, expected_version)
        if job.status not in (ImportJob.Status.UPLOADED, ImportJob.Status.PREVIEWED):
            raise ApiError("IMPORT_LOCKED", "This import can no longer be previewed.", 409)
        validate_mapping(family_or_404(job.family), job.headers, job.mapping)
        job.status = ImportJob.Status.PREVIEWING
        job.version = F("version") + 1
        job.save()
    from .tasks import preview_import

    preview_import.delay(str(job.pk))
    job.refresh_from_db()
    return job


def start_commit(request, job: ImportJob, idempotency_key: str, expected_version) -> ImportJob:
    from apps.organizations.services import check_version

    if not idempotency_key or len(idempotency_key) > 100:
        raise ApiError(
            "IDEMPOTENCY_KEY_REQUIRED", "Send an X-Idempotency-Key header (1-100 characters).", 428
        )
    earlier = ImportJob.objects.filter(
        created_by=request.user, idempotency_key=idempotency_key
    ).first()
    if earlier is not None:
        return earlier  # duplicate request: the original job and its result
    with transaction.atomic():
        job = ImportJob.objects.select_for_update().get(pk=job.pk)
        check_version(job, expected_version)
        if job.status != ImportJob.Status.PREVIEWED:
            raise ApiError("IMPORT_NOT_PREVIEWED", "Preview the import before committing it.", 409)
        family = family_or_404(job.family)
        _check_permission(request.user, family)
        job.status = ImportJob.Status.COMMITTING
        job.idempotency_key = idempotency_key
        job.committed_by = request.user
        job.committed_at = timezone.now()
        job.version = F("version") + 1
        job.save()
        audit.record(
            action="imports.commit",
            actor=request.user,
            request=request,
            object_type="import",
            object_id=job.pk,
            object_label=job.filename,
            after={"family": job.family, "mode": job.mode, "planned": job.totals},
        )
    from .tasks import commit_import

    commit_import.delay(str(job.pk))
    job.refresh_from_db()
    return job


def _check_permission(user, family) -> None:
    if family.permission and family.permission not in user.permission_codes():
        raise ApiError("PERMISSION_DENIED", f"You cannot import {family.label.lower()}.", 403)


def run_commit(job_id) -> ImportJob:
    job = ImportJob.objects.select_related("committed_by").get(pk=job_id)
    if job.status != ImportJob.Status.COMMITTING:
        return job
    family = family_or_404(job.family)
    ctx = _context(job, job.committed_by)
    results = {r: 0 for r in ("applied", "skipped", "failed")}
    try:
        for done, row in enumerate(job.rows.order_by("row_number").iterator(), start=1):
            if row.action not in (ImportRow.Action.CREATE, ImportRow.Action.UPDATE):
                row.result, row.result_message = (
                    ImportRow.Result.SKIPPED,
                    "; ".join(row.messages)[:500],
                )
                results["skipped"] += 1
            else:
                plan = family.plan(ctx, row.values, row.row_number)  # current data, not stale
                if plan.action != row.action:
                    row.result = ImportRow.Result.FAILED
                    row.result_message = (
                        f"Changed since the preview (now {plan.action}): "
                        + "; ".join(plan.messages)
                    )[:500]
                    results["failed"] += 1
                else:
                    try:
                        with transaction.atomic():
                            target_id, label, version_after = family.apply(ctx, plan, row.values)
                        row.result, row.result_message = ImportRow.Result.APPLIED, ""
                        row.target_id, row.target_label = target_id, label[:200]
                        row.version_after = version_after
                        row.changes = plan.changes
                        results["applied"] += 1
                    except (RowError, serializers.ValidationError, ApiError) as exc:
                        detail = getattr(exc, "detail", None) or str(exc)
                        row.result, row.result_message = ImportRow.Result.FAILED, str(detail)[:500]
                        results["failed"] += 1
            row.save(
                update_fields=[
                    "result",
                    "result_message",
                    "target_id",
                    "target_label",
                    "version_after",
                    "changes",
                ]
            )
            if done % 100 == 0:
                ImportJob.objects.filter(pk=job.pk).update(progress=done)
    except Exception as exc:
        ImportJob.objects.filter(pk=job.pk).update(
            status=ImportJob.Status.FAILED, error_message=f"Internal error ({type(exc).__name__})."
        )
        raise
    ImportJob.objects.filter(pk=job.pk).update(
        status=ImportJob.Status.COMPLETED,
        completed_at=timezone.now(),
        progress=job.row_count,
        totals={**job.totals, "result": results},
        version=F("version") + 1,
    )
    audit.record(
        action="imports.complete",
        actor=job.committed_by,
        object_type="import",
        object_id=job.pk,
        object_label=job.filename,
        after=results,
        source="system",
    )
    job.refresh_from_db()
    return job


def rollback(request, job: ImportJob, reason: str, expected_version) -> ImportJob:
    from apps.organizations.services import check_version

    with transaction.atomic():
        job = ImportJob.objects.select_for_update().get(pk=job.pk)
        check_version(job, expected_version)
        if job.status != ImportJob.Status.COMPLETED:
            raise ApiError(
                "IMPORT_NOT_COMPLETED", "Only completed imports can be rolled back.", 409
            )
        family = family_or_404(job.family)
        _check_permission(request.user, family)
        ctx = Context(request.user, job.mode, job, request=request)
        undone = kept = 0
        for row in job.rows.filter(result=ImportRow.Result.APPLIED).order_by("-row_number"):
            try:
                with transaction.atomic():
                    ok, message = family.rollback(ctx, row)
            except (RowError, serializers.ValidationError, ApiError) as exc:
                ok, message = False, str(getattr(exc, "detail", exc))[:500]
            row.result = ImportRow.Result.ROLLED_BACK if ok else ImportRow.Result.NOT_ROLLED_BACK
            row.result_message = message[:500]
            row.save(update_fields=["result", "result_message"])
            undone, kept = undone + ok, kept + (not ok)
        job.status = ImportJob.Status.ROLLED_BACK
        job.rolled_back_at = timezone.now()
        job.rolled_back_by = request.user
        job.totals = {**job.totals, "rollback": {"rolled_back": undone, "needs_correction": kept}}
        job.version = F("version") + 1
        job.save()
        audit.record(
            action="imports.rollback",
            actor=request.user,
            request=request,
            object_type="import",
            object_id=job.pk,
            object_label=job.filename,
            after={"rolled_back": undone, "needs_correction": kept},
            detail=reason,
        )
    job.refresh_from_db()
    return job


def purge_expired(now=None) -> int:
    """Drop retained originals past their retention date (rows and receipts stay)."""
    now = now or timezone.now()
    return ImportJob.objects.filter(purge_after__lte=now, purged_at__isnull=True).update(
        file_encrypted=None, purged_at=now
    )


def error_report(job: ImportJob) -> str:
    """CSV of rows that are not applied: row number, action/result, messages, values
    (every cell formula-escaped)."""
    fields = [h for h in job.headers if job.mapping.get(h)]
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["row", "action", "result", "messages", *fields])
    rows = job.rows.exclude(result=ImportRow.Result.APPLIED).exclude(
        action__in=[ImportRow.Action.CREATE, ImportRow.Action.UPDATE], result=""
    )
    for row in rows.order_by("row_number"):
        message = "; ".join(row.messages) or row.result_message
        writer.writerow(
            [
                row.row_number,
                row.action,
                row.result,
                parsing.escape_cell(message),
                *[parsing.escape_cell(row.values.get(job.mapping[h], "")) for h in fields],
            ]
        )
    return out.getvalue()


def counts(job: ImportJob) -> dict:
    return dict(job.rows.values_list("action").annotate(n=Count("pk")))
