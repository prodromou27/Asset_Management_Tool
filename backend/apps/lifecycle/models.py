"""Lifecycle catalogue, evidence, asset matches, assessments and exceptions (Task 015).

docs/06: lifecycle is evidence-backed per dimension (hardware model/part, OS/firmware
release, software version); Unknown is the safe default (ADR-009). Nothing here is seeded:
every product, milestone and source is entered (or later imported through an adapter) and
verified by an authorised reviewer.

- ``LifecycleProduct``: a hardware model, OS/firmware release or software version.
- ``LifecycleAlias``: an explicit, approved alternative name (model alias, part number,
  OS name/build) that maps observed strings to one product.
- ``VendorAlias``: an explicit alternative manufacturer/publisher name.
- ``LifecycleSource``: one evidence document (URL, publisher, type, collection and last
  verification dates).
- ``LifecycleMilestone``: one dated claim (milestone type + date) backed by a source, with
  its own verification status. Several sources may claim the same milestone.
- ``LifecycleRevision``: numbered snapshot of a product with its aliases and milestones
  after every change (change history).
- ``AssetLifecycleMatch``: the asset's match to a product for one dimension, with the
  observed values and their provenance, method, candidates and review state.
- ``LifecycleAssessment``: the calculated status for one asset and dimension, with the
  governing milestone, evidence and any active exception; ``LifecycleAssessmentHistory``
  keeps earlier results.
- ``LifecycleException``: an approved, expiring manual assessment override. It never
  changes vendor evidence.
"""

import uuid

from django.conf import settings
from django.db import models
from django.db.models import Q

_USER = settings.AUTH_USER_MODEL


class Dimension(models.TextChoices):
    HARDWARE = "hardware", "Hardware"
    OS = "os", "Operating system / firmware"
    SOFTWARE = "software", "Software"


class Status(models.TextChoices):
    """docs/06 lifecycle states plus ``not_applicable`` (ASM-53)."""

    SUPPORTED = "supported", "Supported"
    EOL_ANNOUNCED = "eol_announced", "EOL announced"
    EXPIRING = "expiring", "Approaching end of support"
    SECURITY_MAINTENANCE_ENDED = "security_maintenance_ended", "Security updates ended"
    EOS = "eos", "End of support"
    NOT_ANNOUNCED = "not_announced", "Not announced"
    UNKNOWN = "unknown", "Unknown"
    UNVERIFIED = "unverified", "Unverified"
    NOT_APPLICABLE = "not_applicable", "Not applicable"


class LifecycleProduct(models.Model):
    class Kind(models.TextChoices):
        HARDWARE = "hardware", "Hardware model"
        OPERATING_SYSTEM = "operating_system", "Operating system"
        FIRMWARE = "firmware", "Firmware / network OS"
        SOFTWARE = "software", "Software"

    class SupportStatement(models.TextChoices):
        NONE = "", "No statement recorded"
        SUPPORTED = "supported", "Vendor states the product is supported"
        NOT_ANNOUNCED = "not_announced", "Vendor has not announced end of life"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    kind = models.CharField(max_length=20, choices=Kind.choices)
    vendor = models.CharField(max_length=150)
    vendor_key = models.CharField(max_length=150, editable=False)
    name = models.CharField(max_length=200)  # model / product name, e.g. "C9300-48P"
    name_key = models.CharField(max_length=200, editable=False)
    release = models.CharField(max_length=100, blank=True)  # e.g. "17.9", "22H2"
    release_key = models.CharField(max_length=100, blank=True, editable=False)
    family = models.CharField(max_length=150, blank=True)  # informational; never auto-matched
    description = models.CharField(max_length=500, blank=True)
    # A verified vendor statement used when no milestone dates exist (docs/06 Supported /
    # Not Announced). It never applies without a verified source.
    support_statement = models.CharField(
        max_length=20, choices=SupportStatement.choices, blank=True, default=""
    )
    statement_source = models.ForeignKey(
        "LifecycleSource", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    statement_verified_by = models.ForeignKey(
        _USER, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    statement_verified_at = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(_USER, null=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    modified_by = models.ForeignKey(_USER, null=True, on_delete=models.SET_NULL, related_name="+")
    modified_at = models.DateTimeField(auto_now=True)
    version = models.PositiveIntegerField(default=1)  # optimistic lock

    class Meta:
        ordering = ["vendor", "name", "release"]
        constraints = [
            models.UniqueConstraint(
                fields=["kind", "vendor_key", "name_key", "release_key"],
                name="lifecycle_product_unique",
            )
        ]
        indexes = [models.Index(fields=["kind", "vendor_key"])]

    def __str__(self):
        return " ".join(p for p in (self.vendor, self.name, self.release) if p)

    @property
    def dimension(self) -> str:
        if self.kind == self.Kind.HARDWARE:
            return Dimension.HARDWARE
        if self.kind == self.Kind.SOFTWARE:
            return Dimension.SOFTWARE
        return Dimension.OS


class VendorAlias(models.Model):
    """'Cisco Systems' -> 'Cisco'. Only explicit entries; no fuzzy vendor guessing."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    alias = models.CharField(max_length=150)
    alias_key = models.CharField(max_length=150, unique=True, editable=False)
    vendor = models.CharField(max_length=150)
    created_by = models.ForeignKey(_USER, null=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["alias"]


class LifecycleAlias(models.Model):
    class Kind(models.TextChoices):
        MODEL = "model", "Model name"
        PART_NUMBER = "part_number", "Part number / SKU"
        OS_NAME = "os_name", "OS or firmware name"
        PRODUCT_NAME = "product_name", "Software product name"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    product = models.ForeignKey(LifecycleProduct, on_delete=models.CASCADE, related_name="aliases")
    kind = models.CharField(max_length=20, choices=Kind.choices)
    value = models.CharField(max_length=200)
    value_key = models.CharField(max_length=200, editable=False)
    # For OS/software aliases: the observed version/build this alias stands for
    # (e.g. build "10.0.19045" for release "22H2"). Blank = the product's own release.
    release = models.CharField(max_length=100, blank=True)
    release_key = models.CharField(max_length=100, blank=True, editable=False)
    note = models.CharField(max_length=300, blank=True)
    created_by = models.ForeignKey(_USER, null=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["kind", "value"]
        constraints = [
            models.UniqueConstraint(
                fields=["product", "kind", "value_key", "release_key"],
                name="lifecycle_alias_unique",
            )
        ]
        indexes = [models.Index(fields=["value_key"])]


class LifecycleSource(models.Model):
    class SourceType(models.TextChoices):
        VENDOR = "vendor", "Official vendor documentation"
        MANUAL = "manual", "Manual record (vendor correspondence, contract)"
        THIRD_PARTY = "third_party", "Third party (supporting only)"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    publisher = models.CharField(max_length=150)
    title = models.CharField(max_length=300)
    url = models.URLField(max_length=1000, blank=True)
    source_type = models.CharField(max_length=20, choices=SourceType.choices)
    document_ref = models.CharField(max_length=200, blank=True)  # bulletin number, file name
    collected_on = models.DateField()
    last_verified_on = models.DateField(null=True, blank=True)
    notes = models.TextField(blank=True, max_length=2000)
    created_by = models.ForeignKey(_USER, null=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    modified_at = models.DateTimeField(auto_now=True)
    version = models.PositiveIntegerField(default=1)

    class Meta:
        ordering = ["publisher", "title"]


class MilestoneType(models.TextChoices):
    ANNOUNCEMENT = "announcement", "End-of-life announcement"
    END_OF_SALE = "end_of_sale", "End of sale"
    END_OF_MAINTENANCE = "end_of_maintenance", "End of maintenance (bug fixes)"
    END_OF_SECURITY_UPDATES = "end_of_security_updates", "End of security updates"
    END_OF_STANDARD_SUPPORT = "end_of_standard_support", "End of standard support"
    END_OF_EXTENDED_SUPPORT = "end_of_extended_support", "End of extended support"
    END_OF_SUPPORT = "end_of_support", "Final end of support"


class LifecycleMilestone(models.Model):
    class Verification(models.TextChoices):
        PENDING = "pending", "Awaiting verification"
        VERIFIED = "verified", "Verified"
        REJECTED = "rejected", "Rejected"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    product = models.ForeignKey(
        LifecycleProduct, on_delete=models.CASCADE, related_name="milestones"
    )
    milestone_type = models.CharField(max_length=30, choices=MilestoneType.choices)
    # The last calendar day the milestone's service is provided (ASM-53); "passed" means
    # today (UTC) is after this date.
    date = models.DateField()
    source = models.ForeignKey(LifecycleSource, on_delete=models.PROTECT, related_name="milestones")
    verification = models.CharField(
        max_length=10, choices=Verification.choices, default=Verification.PENDING
    )
    reviewed_by = models.ForeignKey(
        _USER, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    notes = models.CharField(max_length=1000, blank=True)  # interpretation notes
    created_by = models.ForeignKey(_USER, null=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    modified_at = models.DateTimeField(auto_now=True)
    version = models.PositiveIntegerField(default=1)

    class Meta:
        ordering = ["product", "date", "milestone_type"]
        indexes = [models.Index(fields=["product", "milestone_type", "verification"])]


class LifecycleRevision(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    product = models.ForeignKey(
        LifecycleProduct, on_delete=models.CASCADE, related_name="revisions"
    )
    number = models.PositiveIntegerField()
    action = models.CharField(max_length=60)
    summary = models.CharField(max_length=500, blank=True)
    snapshot = models.JSONField()
    actor = models.ForeignKey(_USER, null=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-number"]
        constraints = [
            models.UniqueConstraint(fields=["product", "number"], name="lifecycle_revision_unique")
        ]


class AssetLifecycleMatch(models.Model):
    class Method(models.TextChoices):
        EXACT = "exact", "Exact match"
        ALIAS = "alias", "Approved alias"
        MANUAL = "manual", "Approved by reviewer"
        NONE = "none", "No match"

    class State(models.TextChoices):
        MATCHED = "matched", "Matched"
        CANDIDATE = "candidate", "Needs review"
        NO_MATCH = "no_match", "No match"
        NOT_APPLICABLE = "not_applicable", "Not applicable"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    asset = models.ForeignKey(
        "assets.Asset", on_delete=models.CASCADE, related_name="lifecycle_matches"
    )
    dimension = models.CharField(max_length=10, choices=Dimension.choices)
    state = models.CharField(max_length=15, choices=State.choices)
    method = models.CharField(max_length=10, choices=Method.choices, default=Method.NONE)
    product = models.ForeignKey(
        LifecycleProduct, null=True, blank=True, on_delete=models.PROTECT, related_name="matches"
    )
    # Observed values the match was made from, with their provenance (source identity).
    observed = models.JSONField(default=dict)
    observed_key = models.CharField(max_length=64)  # hash of the matching inputs
    candidates = models.JSONField(default=list)  # [{product_id, label, reason}]
    reason = models.CharField(max_length=500, blank=True)
    rejected_products = models.JSONField(default=list)  # product IDs a reviewer rejected
    reviewed_by = models.ForeignKey(
        _USER, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_note = models.CharField(max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    modified_at = models.DateTimeField(auto_now=True)
    version = models.PositiveIntegerField(default=1)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["asset", "dimension"], name="lifecycle_match_unique")
        ]
        indexes = [models.Index(fields=["state", "dimension"])]


class LifecycleException(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    asset = models.ForeignKey(
        "assets.Asset", on_delete=models.CASCADE, related_name="lifecycle_exceptions"
    )
    dimension = models.CharField(max_length=10, choices=Dimension.choices)
    status = models.CharField(max_length=30, choices=Status.choices)
    reason = models.CharField(max_length=1000)
    compensating_controls = models.CharField(max_length=1000, blank=True)
    expires_on = models.DateField()
    approved_by = models.ForeignKey(_USER, on_delete=models.PROTECT, related_name="+")
    approved_at = models.DateTimeField(auto_now_add=True)
    revoked_by = models.ForeignKey(
        _USER, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    revoked_at = models.DateTimeField(null=True, blank=True)
    revoke_reason = models.CharField(max_length=500, blank=True)
    version = models.PositiveIntegerField(default=1)

    class Meta:
        ordering = ["-approved_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["asset", "dimension"],
                condition=Q(revoked_at__isnull=True),
                name="lifecycle_one_open_exception",
            )
        ]


class LifecycleAssessment(models.Model):
    class SupportLevel(models.TextChoices):
        NONE = "", "Not determined"
        STANDARD = "standard", "Standard support"
        EXTENDED = "extended", "Extended support"
        ENDED = "ended", "Support ended"

    class EvidenceQuality(models.TextChoices):
        NONE = "", "No evidence"
        VENDOR = "vendor", "Official vendor"
        MANUAL = "manual", "Manual record"
        THIRD_PARTY = "third_party", "Third party only"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    asset = models.ForeignKey(
        "assets.Asset", on_delete=models.CASCADE, related_name="lifecycle_assessments"
    )
    dimension = models.CharField(max_length=10, choices=Dimension.choices)
    status = models.CharField(max_length=30, choices=Status.choices)  # calculated from evidence
    effective_status = models.CharField(max_length=30, choices=Status.choices)  # after exception
    product = models.ForeignKey(
        LifecycleProduct, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    support_level = models.CharField(
        max_length=10, choices=SupportLevel.choices, blank=True, default=""
    )
    milestone_type = models.CharField(max_length=30, choices=MilestoneType.choices, blank=True)
    milestone_date = models.DateField(null=True, blank=True)
    days_remaining = models.IntegerField(null=True, blank=True)
    threshold_days = models.PositiveIntegerField(null=True, blank=True)  # warning tier reached
    evidence_quality = models.CharField(
        max_length=15, choices=EvidenceQuality.choices, blank=True, default=""
    )
    milestone_ids = models.JSONField(default=list)  # evidence used
    reasons = models.JSONField(default=list)  # plain-language explanation lines
    exception = models.ForeignKey(
        LifecycleException, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    assessed_on = models.DateField()
    assessed_at = models.DateTimeField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["asset", "dimension"], name="lifecycle_assessment_unique"
            )
        ]
        indexes = [models.Index(fields=["effective_status", "dimension"])]


class LifecycleAssessmentHistory(models.Model):
    """Previous results, written whenever the status, governing date or product changes."""

    id = models.BigAutoField(primary_key=True)
    asset = models.ForeignKey("assets.Asset", on_delete=models.CASCADE, related_name="+")
    dimension = models.CharField(max_length=10, choices=Dimension.choices)
    status = models.CharField(max_length=30)
    effective_status = models.CharField(max_length=30)
    product_label = models.CharField(max_length=500, blank=True)
    milestone_type = models.CharField(max_length=30, blank=True)
    milestone_date = models.DateField(null=True, blank=True)
    reasons = models.JSONField(default=list)
    recorded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-recorded_at", "-id"]
        indexes = [models.Index(fields=["asset", "dimension"])]
