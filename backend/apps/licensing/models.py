"""Microsoft 365 / Entra license inventory (Task 010, docs/06 software and license model).

What a tenant reports, kept as inventory and allocation facts, never as billing or
compliance truth (docs/06: "Graph tenant inventory is not a billing agreement"):

- ``LicenseSku``: a subscribed SKU of one tenant (Graph ``subscribedSkus``), scoped to
  the integration instance.
- ``SubscriptionSnapshot``: purchased (enabled/warning/suspended/locked-out) and consumed
  units as of a time, plus ITAM's own distinct assigned-user count. Append-only: a new
  row is written only when a value changes, so quantity history is preserved.
- ``DirectoryUser``: the minimum directory identity needed to show an allocation
  (object ID, UPN, display name, enabled). No e-mail, phone or other profile data.
- ``LicenseAllocation``: one row per user and SKU while assigned, whatever the number of
  assignment paths (direct and/or one or more groups), so a user is never counted twice.
  When the assignment disappears from a complete listing the row is ended, not deleted;
  a later re-assignment opens a new row.

Manually maintained entitlements (Task 016b, ASM-55):

- ``LicenseProduct``: what is licensed (publisher, name, vendor SKU) and how it is
  counted (metric). Optionally linked to an observed ``SoftwareProduct`` so installation
  counts can be shown next to purchased quantities; the two are never merged.
- ``LicenseEntitlement``: purchased units under one agreement/order reference, with term
  and owner. Retired, never deleted.
- ``EntitlementAllocation``: units of an entitlement given to an asset or a named user.
  Ended, never deleted. ITAM records allocations; it does not judge compliance.
"""

import uuid

from django.conf import settings
from django.db import models
from django.db.models import Q

from apps.integrations.models import IntegrationInstance, SyncRun


class LicenseSku(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    instance = models.ForeignKey(IntegrationInstance, on_delete=models.PROTECT, related_name="+")
    tenant_id = models.CharField(max_length=100, blank=True)
    sku_id = models.CharField(max_length=36)
    sku_part_number = models.CharField(max_length=120, blank=True)
    applies_to = models.CharField(max_length=20, blank=True)
    capability_status = models.CharField(max_length=30, blank=True)
    # False for SKUs only seen in user assignments (not in subscribedSkus).
    subscribed = models.BooleanField(default=True)
    service_plans = models.JSONField(default=list, blank=True)
    first_seen_at = models.DateTimeField()
    last_seen_at = models.DateTimeField()
    missing_since = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["sku_part_number", "sku_id"]
        constraints = [
            models.UniqueConstraint(fields=["instance", "sku_id"], name="license_sku_instance_sku")
        ]

    def __str__(self):
        return self.sku_part_number or self.sku_id


class SubscriptionSnapshot(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    sku = models.ForeignKey(LicenseSku, on_delete=models.CASCADE, related_name="snapshots")
    run = models.ForeignKey(
        SyncRun, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    taken_at = models.DateTimeField()
    last_confirmed_at = models.DateTimeField()
    capability_status = models.CharField(max_length=30, blank=True)
    # As reported by the tenant (prepaidUnits.*, consumedUnits).
    enabled_units = models.IntegerField(null=True, blank=True)
    warning_units = models.IntegerField(null=True, blank=True)
    suspended_units = models.IntegerField(null=True, blank=True)
    locked_out_units = models.IntegerField(null=True, blank=True)
    consumed_units = models.IntegerField(null=True, blank=True)
    # Counted by ITAM from active allocations (distinct users); null when the user listing
    # was incomplete.
    assigned_users = models.IntegerField(null=True, blank=True)
    direct_users = models.IntegerField(null=True, blank=True)
    group_users = models.IntegerField(null=True, blank=True)
    original = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-taken_at"]
        indexes = [models.Index(fields=["sku", "taken_at"])]


class DirectoryUser(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    instance = models.ForeignKey(IntegrationInstance, on_delete=models.PROTECT, related_name="+")
    tenant_id = models.CharField(max_length=100, blank=True)
    object_id = models.CharField(max_length=36)
    user_principal_name = models.CharField(max_length=320, blank=True)
    display_name = models.CharField(max_length=256, blank=True)
    account_enabled = models.BooleanField(null=True, blank=True)
    first_seen_at = models.DateTimeField()
    last_seen_at = models.DateTimeField()
    missing_since = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["display_name", "user_principal_name"]
        constraints = [
            models.UniqueConstraint(
                fields=["instance", "object_id"], name="directory_user_instance_object"
            )
        ]

    def __str__(self):
        return self.user_principal_name or self.object_id


class DirectoryGroup(models.Model):
    """Display name of a group that assigns licenses. Only stored when the app holds an
    optional group-read permission; otherwise allocations show group object IDs."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    instance = models.ForeignKey(IntegrationInstance, on_delete=models.PROTECT, related_name="+")
    object_id = models.CharField(max_length=36)
    display_name = models.CharField(max_length=256)
    last_seen_at = models.DateTimeField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["instance", "object_id"], name="directory_group_instance_object"
            )
        ]

    def __str__(self):
        return self.display_name


class LicenseAllocation(models.Model):
    class State(models.TextChoices):
        ACTIVE = "Active", "Active"
        ACTIVE_WITH_ERROR = "ActiveWithError", "Active with error"
        DISABLED = "Disabled", "Disabled"
        ERROR = "Error", "Error"
        UNKNOWN = "Unknown", "Unknown"

    # States that consume a seat for ITAM's assigned-user count. Unknown: listed in
    # assignedLicenses without a licenseAssignmentStates entry, so a seat is assigned.
    COUNTED = (State.ACTIVE, State.ACTIVE_WITH_ERROR, State.UNKNOWN)

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    instance = models.ForeignKey(IntegrationInstance, on_delete=models.PROTECT, related_name="+")
    sku = models.ForeignKey(LicenseSku, on_delete=models.PROTECT, related_name="allocations")
    user = models.ForeignKey(DirectoryUser, on_delete=models.PROTECT, related_name="allocations")
    assigned_directly = models.BooleanField(default=False)
    group_ids = models.JSONField(default=list, blank=True)
    state = models.CharField(max_length=20, choices=State.choices, default=State.UNKNOWN)
    # Original licenseAssignmentStates entries for this SKU (one per assignment path).
    paths = models.JSONField(default=list, blank=True)
    first_seen_at = models.DateTimeField()
    last_seen_at = models.DateTimeField()
    changed_at = models.DateTimeField()
    ended_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-first_seen_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["sku", "user"],
                condition=Q(ended_at__isnull=True),
                name="license_allocation_one_active",
            )
        ]
        indexes = [models.Index(fields=["instance", "ended_at"])]

    @property
    def method(self) -> str:
        if self.assigned_directly and self.group_ids:
            return "direct_and_group"
        return "direct" if self.assigned_directly else "group"


# --- Manually maintained entitlements (Task 016b) --------------------------------------------

_USER = settings.AUTH_USER_MODEL


class LicenseProduct(models.Model):
    class Metric(models.TextChoices):
        USER = "user", "Per user"
        DEVICE = "device", "Per device"
        CORE = "core", "Per core"
        CONCURRENT = "concurrent", "Concurrent users"
        SUBSCRIPTION = "subscription", "Subscription"
        OTHER = "other", "Other"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    publisher = models.CharField(max_length=200, blank=True)
    name = models.CharField(max_length=200)
    sku = models.CharField(max_length=120, blank=True)
    identity_key = models.CharField(max_length=530, unique=True, editable=False)
    metric = models.CharField(max_length=15, choices=Metric.choices, default=Metric.USER)
    software_product = models.ForeignKey(
        "software.SoftwareProduct",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="license_products",
    )
    note = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    version = models.PositiveIntegerField(default=1)
    created_by = models.ForeignKey(_USER, null=True, on_delete=models.SET_NULL, related_name="+")
    modified_by = models.ForeignKey(_USER, null=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    modified_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name", "publisher", "sku"]

    def __str__(self):
        label = f"{self.publisher} {self.name}".strip()
        return f"{label} ({self.sku})" if self.sku else label


class LicenseEntitlement(models.Model):
    class Source(models.TextChoices):
        MANUAL = "manual", "Manual"
        IMPORT = "import", "Import"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    product = models.ForeignKey(
        LicenseProduct, on_delete=models.PROTECT, related_name="entitlements"
    )
    # Agreement, order or contract number that identifies the purchase.
    reference = models.CharField(max_length=120)
    reference_key = models.CharField(max_length=120, editable=False)
    quantity = models.PositiveIntegerField()
    starts_on = models.DateField(null=True, blank=True)
    ends_on = models.DateField(null=True, blank=True)  # empty: perpetual
    supplier = models.CharField(max_length=200, blank=True)
    owner = models.CharField(max_length=200, blank=True)  # responsible person or team
    note = models.TextField(blank=True)
    source = models.CharField(max_length=10, choices=Source.choices, default=Source.MANUAL)
    retired_at = models.DateTimeField(null=True, blank=True)
    retired_by = models.ForeignKey(_USER, null=True, on_delete=models.SET_NULL, related_name="+")
    retired_reason = models.CharField(max_length=500, blank=True)
    version = models.PositiveIntegerField(default=1)
    created_by = models.ForeignKey(_USER, null=True, on_delete=models.SET_NULL, related_name="+")
    modified_by = models.ForeignKey(_USER, null=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    modified_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["product__name", "reference"]
        constraints = [
            models.UniqueConstraint(
                fields=["product", "reference_key"], name="license_entitlement_reference"
            ),
            models.CheckConstraint(
                condition=Q(quantity__gte=1), name="license_entitlement_quantity"
            ),
            models.CheckConstraint(
                condition=Q(ends_on__isnull=True)
                | Q(starts_on__isnull=True)
                | Q(ends_on__gte=models.F("starts_on")),
                name="license_entitlement_term",
            ),
        ]

    def __str__(self):
        return f"{self.product} / {self.reference}"

    def status(self, today) -> str:
        """retired | not_started | expired | active (calendar days, UTC)."""
        if self.retired_at:
            return "retired"
        if self.starts_on and today < self.starts_on:
            return "not_started"
        if self.ends_on and today > self.ends_on:
            return "expired"
        return "active"


class EntitlementAllocation(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    entitlement = models.ForeignKey(
        LicenseEntitlement, on_delete=models.PROTECT, related_name="allocations"
    )
    asset = models.ForeignKey(
        "assets.Asset",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="license_allocations",
    )
    # Named user (name, UPN or e-mail as the organisation records it); personal data.
    user_name = models.CharField(max_length=320, blank=True)
    user_key = models.CharField(max_length=320, blank=True, editable=False)
    units = models.PositiveIntegerField(default=1)
    note = models.CharField(max_length=500, blank=True)
    allocated_at = models.DateTimeField()
    allocated_by = models.ForeignKey(_USER, null=True, on_delete=models.SET_NULL, related_name="+")
    ended_at = models.DateTimeField(null=True, blank=True)
    ended_by = models.ForeignKey(_USER, null=True, on_delete=models.SET_NULL, related_name="+")
    ended_reason = models.CharField(max_length=500, blank=True)

    class Meta:
        ordering = ["-allocated_at"]
        constraints = [
            models.CheckConstraint(
                condition=(Q(asset__isnull=False) & Q(user_key=""))
                | (Q(asset__isnull=True) & ~Q(user_key="")),
                name="entitlement_allocation_one_target",
            ),
            models.CheckConstraint(condition=Q(units__gte=1), name="entitlement_allocation_units"),
            models.UniqueConstraint(
                fields=["entitlement", "asset"],
                condition=Q(ended_at__isnull=True, asset__isnull=False),
                name="entitlement_allocation_asset_active",
            ),
            models.UniqueConstraint(
                fields=["entitlement", "user_key"],
                condition=Q(ended_at__isnull=True) & ~Q(user_key=""),
                name="entitlement_allocation_user_active",
            ),
        ]
        indexes = [models.Index(fields=["entitlement", "ended_at"])]

    @property
    def target(self) -> str:
        return "asset" if self.asset_id else "user"
