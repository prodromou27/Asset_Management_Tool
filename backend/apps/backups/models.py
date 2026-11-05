"""Backup metadata only. Repository credentials and recovery keys stay outside the DB."""

import uuid

from django.conf import settings
from django.db import models
from django.db.models import Q


class BackupPolicy(models.Model):
    id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    enabled = models.BooleanField(default=False)
    hour_utc = models.PositiveSmallIntegerField(default=2)
    rpo_hours = models.PositiveSmallIntegerField(default=24)
    rto_hours = models.PositiveSmallIntegerField(default=4)
    keep_daily = models.PositiveSmallIntegerField(default=30)
    keep_weekly = models.PositiveSmallIntegerField(default=8)
    keep_monthly = models.PositiveSmallIntegerField(default=12)
    retention_enabled = models.BooleanField(default=False)
    version = models.PositiveIntegerField(default=1)
    modified_at = models.DateTimeField(auto_now=True)


class BackupJob(models.Model):
    class Kind(models.TextChoices):
        BACKUP = "backup", "Backup"
        VERIFY = "verify", "Verification"

    class Status(models.TextChoices):
        QUEUED = "queued", "Queued"
        RUNNING = "running", "Running"
        SUCCEEDED = "succeeded", "Verified"
        FAILED = "failed", "Failed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    kind = models.CharField(max_length=10, choices=Kind.choices)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.QUEUED)
    target_label = models.CharField(max_length=120)
    snapshot_id = models.CharField(max_length=64, blank=True)
    source = models.ForeignKey("self", null=True, on_delete=models.PROTECT)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True)
    finished_at = models.DateTimeField(null=True)
    recovery_point = models.DateTimeField(null=True)
    size_bytes = models.PositiveBigIntegerField(default=0)
    manifest = models.JSONField(default=dict)
    error_message = models.CharField(max_length=300, blank=True)
    warning = models.CharField(max_length=300, blank=True)
    # A database constraint serializes all requests, including periodic runs.
    active_slot = models.PositiveSmallIntegerField(null=True, default=1, unique=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(
                condition=(Q(status__in=["queued", "running"], active_slot=1))
                | (Q(status__in=["succeeded", "failed"], active_slot__isnull=True)),
                name="backup_active_slot_matches_status",
            )
        ]


class RestoreDrill(models.Model):
    """Operator-attested drill report, never an instruction to restore production."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    backup = models.ForeignKey(BackupJob, on_delete=models.PROTECT)
    target_label = models.CharField(max_length=120)
    started_at = models.DateTimeField()
    finished_at = models.DateTimeField()
    passed = models.BooleanField()
    notes = models.CharField(max_length=2000)
    recorded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    recorded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-finished_at"]
