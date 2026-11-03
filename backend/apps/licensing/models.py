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
"""

import uuid

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
