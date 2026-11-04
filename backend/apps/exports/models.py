"""Export jobs (Task 014, docs/11 "Export", docs/14 data exfiltration).

A job is created by an authorized user, built by a Celery worker from the user's own
site-scoped view of the data (permissions re-checked when the job runs), stored encrypted
and downloadable only by its creator until ``expires_at``. The file is then deleted; the
job row stays as the record of what was exported, by whom and how many rows.
"""

import uuid

from django.conf import settings
from django.db import models

_USER = settings.AUTH_USER_MODEL


class ExportJob(models.Model):
    class Status(models.TextChoices):
        QUEUED = "queued", "Queued"
        RUNNING = "running", "Preparing"
        COMPLETED = "completed", "Ready"
        FAILED = "failed", "Failed"
        EXPIRED = "expired", "Expired"

    class Format(models.TextChoices):
        CSV = "csv", "CSV"
        XLSX = "xlsx", "Excel (XLSX)"
        JSON = "json", "JSON"

    class Scope(models.TextChoices):
        FILTERED = "filtered", "Current filters"
        SELECTED = "selected", "Selected records"
        ALL = "all", "All records I can see"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    family = models.CharField(max_length=40)
    file_format = models.CharField(max_length=10, choices=Format.choices)
    scope = models.CharField(max_length=10, choices=Scope.choices)
    filters = models.JSONField(default=dict, blank=True)
    ids = models.JSONField(default=list, blank=True)
    columns = models.JSONField(default=list, blank=True)  # empty = every permitted column
    related = models.JSONField(default=list, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.QUEUED)
    row_count = models.PositiveIntegerField(default=0)
    related_counts = models.JSONField(default=dict, blank=True)
    masked_columns = models.JSONField(default=list, blank=True)
    filename = models.CharField(max_length=200, blank=True)
    content_type = models.CharField(max_length=100, blank=True)
    size_bytes = models.PositiveIntegerField(default=0)
    checksum = models.CharField(max_length=64, blank=True)
    file_encrypted = models.BinaryField(null=True, blank=True, editable=False)
    error_message = models.CharField(max_length=500, blank=True)
    created_by = models.ForeignKey(_USER, on_delete=models.PROTECT, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    purged_at = models.DateTimeField(null=True, blank=True)
    download_count = models.PositiveIntegerField(default=0)
    last_downloaded_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["created_by", "status"]),
            models.Index(fields=["status", "expires_at"]),
        ]
