"""Data-quality findings (Task 011, docs/01 dedicated queues).

Each finding is one asset with one problem kind, with severity, evidence, an assignee and a
resolution state. Findings are recomputed from the asset register (``services.refresh``):
- a condition that holds opens a finding (or refreshes the open/dismissed one);
- a condition that no longer holds resolves the finding automatically;
- a dismissed finding stays dismissed while its condition holds (no re-nagging); if the
  condition clears and later returns, a new finding opens.
Nothing here changes an asset: findings only point at work to do.
"""

import uuid

from django.conf import settings
from django.db import models
from django.db.models import Q

from apps.assets.models import Asset

ACTIVE_STATES = ("open", "dismissed")


class DataQualityFinding(models.Model):
    class Kind(models.TextChoices):
        DUPLICATE_CANDIDATE = "duplicate_candidate", "Duplicate candidate"
        MODEL_UNKNOWN = "model_unknown", "Model unknown"
        SOURCE_STALE = "source_stale", "Source stale"
        OWNER_MISSING = "owner_missing", "Owner missing"

    class Severity(models.TextChoices):
        HIGH = "high", "High"
        MEDIUM = "medium", "Medium"
        LOW = "low", "Low"

    class Status(models.TextChoices):
        OPEN = "open", "Open"
        DISMISSED = "dismissed", "Dismissed (accepted as is)"
        RESOLVED = "resolved", "Resolved"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    kind = models.CharField(max_length=30, choices=Kind.choices)
    asset = models.ForeignKey(Asset, on_delete=models.CASCADE, related_name="quality_findings")
    severity = models.CharField(max_length=10, choices=Severity.choices)
    summary = models.CharField(max_length=300)
    evidence = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.OPEN)
    assignee = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    assigned_at = models.DateTimeField(null=True, blank=True)
    detected_at = models.DateTimeField()
    last_confirmed_at = models.DateTimeField()
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="+",
    )
    resolution_reason = models.CharField(max_length=500, blank=True)
    version = models.PositiveIntegerField(default=1)

    class Meta:
        ordering = ["-detected_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["kind", "asset"],
                condition=Q(status__in=ACTIVE_STATES),
                name="quality_one_active_finding_per_kind",
            )
        ]
        indexes = [models.Index(fields=["kind", "status", "severity"])]
