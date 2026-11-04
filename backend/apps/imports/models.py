"""CSV/XLSX import jobs (Task 013, docs/11 "Import").

A job moves through: uploaded → (mapping) → previewing → previewed → committing →
completed | failed, and optionally rolled_back. The original file is kept encrypted
(``file_encrypted``) until ``purge_after``; every data row gets an ``ImportRow`` with the
planned action from the dry run and, after commit, the applied result, so re-imports,
errors and rollback are explainable row by row.
"""

import uuid

from django.conf import settings
from django.db import models
from django.db.models import Q

_USER = settings.AUTH_USER_MODEL


class ImportJob(models.Model):
    class Status(models.TextChoices):
        UPLOADED = "uploaded", "Uploaded"
        PREVIEWING = "previewing", "Checking"
        PREVIEWED = "previewed", "Ready to import"
        COMMITTING = "committing", "Importing"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"
        ROLLED_BACK = "rolled_back", "Rolled back"

    class Mode(models.TextChoices):
        CREATE_ONLY = "create_only", "Create only"
        UPDATE_MATCHED = "update_matched", "Update matched"
        UPSERT = "upsert", "Create and update"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    family = models.CharField(max_length=40)
    template_version = models.PositiveSmallIntegerField()
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.UPLOADED)
    mode = models.CharField(max_length=20, choices=Mode.choices, default=Mode.CREATE_ONLY)
    filename = models.CharField(max_length=255)
    file_format = models.CharField(max_length=10)  # csv | xlsx
    size_bytes = models.PositiveIntegerField()
    checksum = models.CharField(max_length=64)
    encoding = models.CharField(max_length=20, blank=True)
    delimiter = models.CharField(max_length=4, blank=True)
    sheet = models.CharField(max_length=100, blank=True)
    headers = models.JSONField(default=list)
    mapping = models.JSONField(default=dict)  # file column -> template field ("" = ignore)
    row_count = models.PositiveIntegerField(default=0)
    totals = models.JSONField(default=dict)  # action -> count (preview) / result -> count
    warnings = models.JSONField(default=list)
    error_message = models.CharField(max_length=500, blank=True)
    file_encrypted = models.BinaryField(null=True, blank=True, editable=False)
    purge_after = models.DateTimeField()
    purged_at = models.DateTimeField(null=True, blank=True)
    idempotency_key = models.CharField(max_length=100, null=True, blank=True)
    created_by = models.ForeignKey(_USER, on_delete=models.PROTECT, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    previewed_at = models.DateTimeField(null=True, blank=True)
    committed_by = models.ForeignKey(
        _USER, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    committed_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    rolled_back_at = models.DateTimeField(null=True, blank=True)
    rolled_back_by = models.ForeignKey(
        _USER, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    progress = models.PositiveIntegerField(default=0)
    version = models.PositiveIntegerField(default=1)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["created_by", "idempotency_key"],
                condition=Q(idempotency_key__isnull=False),
                name="imports_unique_idempotency_key",
            )
        ]
        indexes = [models.Index(fields=["family", "checksum", "status"])]


class ImportRow(models.Model):
    class Action(models.TextChoices):
        CREATE = "create", "Create"
        UPDATE = "update", "Update"
        SKIP = "skip", "Skip"
        CONFLICT = "conflict", "Conflict"
        ERROR = "error", "Error"

    class Result(models.TextChoices):
        PENDING = "", "Not applied"
        APPLIED = "applied", "Applied"
        SKIPPED = "skipped", "Skipped"
        FAILED = "failed", "Failed"
        ROLLED_BACK = "rolled_back", "Rolled back"
        NOT_ROLLED_BACK = "not_rolled_back", "Changed since import; not rolled back"

    id = models.BigAutoField(primary_key=True)
    job = models.ForeignKey(ImportJob, on_delete=models.CASCADE, related_name="rows")
    row_number = models.PositiveIntegerField()  # 1-based data row (header excluded)
    action = models.CharField(max_length=10, choices=Action.choices)
    key = models.CharField(max_length=300, blank=True)
    target_id = models.CharField(max_length=40, blank=True)
    target_label = models.CharField(max_length=200, blank=True)
    messages = models.JSONField(default=list)
    values = models.JSONField(default=dict)  # mapped raw values (template field -> text)
    changes = models.JSONField(default=dict)  # field -> {before, after} planned / applied
    result = models.CharField(max_length=20, choices=Result.choices, blank=True, default="")
    result_message = models.CharField(max_length=500, blank=True)
    version_after = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        ordering = ["row_number"]
        constraints = [
            models.UniqueConstraint(fields=["job", "row_number"], name="imports_row_unique")
        ]
        indexes = [models.Index(fields=["job", "action"])]
