import uuid

from django.conf import settings
from django.db import models

from apps.assets.models import Asset, AssetCategory
from apps.integrations.models import IntegrationInstance
from apps.observations.models import Observation
from apps.organizations.models import Site

_USER = settings.AUTH_USER_MODEL


class SourceLink(models.Model):
    """(integration instance, external ID) → canonical asset. Unique per instance,
    never across products (docs/03)."""

    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        STALE = "stale", "Stale"
        UNLINKED = "unlinked", "Unlinked"

    class Method(models.TextChoices):
        APPROVED_CANDIDATE = "approved_candidate", "Approved match"
        CREATED_FROM_CANDIDATE = "created_from_candidate", "Created from discovery"
        AUTO_STRONG_MATCH = "auto_strong_match", "Automatic strong match"
        MERGE = "merge", "Moved by merge"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    instance = models.ForeignKey(
        IntegrationInstance, on_delete=models.PROTECT, related_name="links"
    )
    external_id = models.CharField(max_length=200)
    asset = models.ForeignKey(
        Asset, null=True, blank=True, on_delete=models.PROTECT, related_name="source_links"
    )
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ACTIVE)
    method = models.CharField(max_length=30, choices=Method.choices)
    first_seen_at = models.DateTimeField()
    last_seen_at = models.DateTimeField()
    last_observation = models.ForeignKey(
        Observation, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    linked_at = models.DateTimeField(auto_now_add=True)
    linked_by = models.ForeignKey(
        _USER, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    unlinked_at = models.DateTimeField(null=True, blank=True)
    unlinked_by = models.ForeignKey(
        _USER, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    unlink_reason = models.CharField(max_length=500, blank=True)
    version = models.PositiveIntegerField(default=1)

    class Meta:
        ordering = ["instance__name", "external_id"]
        constraints = [
            models.UniqueConstraint("instance", "external_id", name="reconciliation_link_unique")
        ]
        indexes = [
            models.Index(fields=["asset", "status"]),
            models.Index(fields=["instance", "last_seen_at"]),
        ]


class ReconciliationCandidate(models.Model):
    """A discovered device awaiting a human decision (link, create, hold or reject)."""

    class Status(models.TextChoices):
        OPEN = "open", "Open"
        HELD = "held", "On hold"
        LINKED = "linked", "Linked"
        CREATED = "created", "Asset created"
        REJECTED = "rejected", "Rejected"
        SUPERSEDED = "superseded", "Superseded"

    class Rule(models.TextChoices):
        NEW_DEVICE = "new_device", "No matching asset"
        WEAK = "weak", "Weak identifier only"
        CORROBORATED = "corroborated", "Multiple corroborating identifiers"
        STRONG = "strong", "Strong identifier"
        CONFLICT = "conflict", "Conflicting identifiers"

    OPEN_STATES = (Status.OPEN, Status.HELD)

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    instance = models.ForeignKey(
        IntegrationInstance, on_delete=models.PROTECT, related_name="candidates"
    )
    external_id = models.CharField(max_length=200)
    observation = models.ForeignKey(Observation, on_delete=models.PROTECT, related_name="+")
    site = models.ForeignKey(Site, on_delete=models.PROTECT, related_name="+")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.OPEN)
    rule = models.CharField(max_length=20, choices=Rule.choices)
    score = models.PositiveSmallIntegerField(default=0)
    proposed_asset = models.ForeignKey(
        Asset, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    matches = models.JSONField(default=list)
    conflicts = models.JSONField(default=list)
    suggested_category = models.ForeignKey(
        AssetCategory, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    decision = models.CharField(max_length=20, blank=True)
    decision_reason = models.CharField(max_length=500, blank=True)
    decided_by = models.ForeignKey(
        _USER, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    decided_at = models.DateTimeField(null=True, blank=True)
    resulting_asset = models.ForeignKey(
        Asset, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    modified_at = models.DateTimeField(auto_now=True)
    version = models.PositiveIntegerField(default=1)

    class Meta:
        ordering = ["-modified_at"]
        constraints = [
            models.UniqueConstraint(
                "instance",
                "external_id",
                condition=models.Q(status__in=["open", "held"]),
                name="reconciliation_one_open_candidate",
            )
        ]
        indexes = [models.Index(fields=["status", "rule", "modified_at"])]


class FieldConflict(models.Model):
    """A source reported a different value for a manually locked or higher-authority field."""

    class Status(models.TextChoices):
        OPEN = "open", "Open"
        ACCEPTED = "accepted", "Observed value accepted"
        DISMISSED = "dismissed", "Current value kept"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    asset = models.ForeignKey(Asset, on_delete=models.PROTECT, related_name="field_conflicts")
    field = models.CharField(max_length=40)
    current_value = models.CharField(max_length=200, blank=True)
    observed_value = models.CharField(max_length=200)
    reason = models.CharField(max_length=40)  # "locked" | "lower_authority"
    instance = models.ForeignKey(IntegrationInstance, on_delete=models.PROTECT, related_name="+")
    observation = models.ForeignKey(Observation, on_delete=models.PROTECT, related_name="+")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.OPEN)
    created_at = models.DateTimeField(auto_now_add=True)
    modified_at = models.DateTimeField(auto_now=True)
    resolved_by = models.ForeignKey(
        _USER, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolution_reason = models.CharField(max_length=500, blank=True)

    class Meta:
        ordering = ["-modified_at"]
        constraints = [
            models.UniqueConstraint(
                "asset",
                "field",
                "instance",
                condition=models.Q(status="open"),
                name="reconciliation_one_open_conflict",
            )
        ]


class AssetMerge(models.Model):
    """Reversible merge: links and discovered identifiers move to the survivor, the
    merged asset is archived (never deleted). Revert moves them back."""

    class Status(models.TextChoices):
        MERGED = "merged", "Merged"
        REVERTED = "reverted", "Reverted"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    survivor = models.ForeignKey(Asset, on_delete=models.PROTECT, related_name="merges_received")
    merged = models.ForeignKey(Asset, on_delete=models.PROTECT, related_name="merges_into")
    reason = models.CharField(max_length=500)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.MERGED)
    moved_link_ids = models.JSONField(default=list)
    moved_identifier_ids = models.JSONField(default=dict)
    merged_snapshot = models.JSONField(default=dict)
    performed_by = models.ForeignKey(_USER, on_delete=models.PROTECT, related_name="+")
    performed_at = models.DateTimeField(auto_now_add=True)
    reverted_by = models.ForeignKey(
        _USER, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    reverted_at = models.DateTimeField(null=True, blank=True)
    revert_reason = models.CharField(max_length=500, blank=True)

    class Meta:
        ordering = ["-performed_at"]
