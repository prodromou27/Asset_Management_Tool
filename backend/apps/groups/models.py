"""Asset groups (Task 012, docs/03 "Group rule representation", docs/11 "Groups").

- Static groups: members are added and removed explicitly (audited, with a reason for
  removals).
- Dynamic groups: members are evaluated from a validated JSON rule tree (``rules.py``)
  compiled into parameterised ORM conditions. Each rule change is a new
  ``AssetGroupRuleVersion``; evaluated memberships record the rule version that added or
  removed them, so "why is this asset (no longer) in the group" is answerable.
- Memberships are never deleted: removal sets ``removed_at``. One active row per group
  and asset.
- Groups never grant access: every member list is filtered by the viewer's site scope.
- ``parent`` organises groups in a tree; parents and ``member_of`` rule references must
  be acyclic.
"""

import uuid

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.db.models.functions import Lower

from apps.assets.models import Asset

_USER = settings.AUTH_USER_MODEL


class AssetGroup(models.Model):
    class Kind(models.TextChoices):
        STATIC = "static", "Static"
        DYNAMIC = "dynamic", "Dynamic"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=120)
    description = models.CharField(max_length=500, blank=True)
    kind = models.CharField(max_length=10, choices=Kind.choices)
    parent = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.PROTECT, related_name="children"
    )
    owner = models.ForeignKey(
        _USER, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    # Dynamic groups: the current rule (also kept in AssetGroupRuleVersion history).
    rule = models.JSONField(null=True, blank=True)
    rule_version = models.PositiveIntegerField(default=0)
    last_evaluated_at = models.DateTimeField(null=True, blank=True)
    archived_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(_USER, null=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    modified_at = models.DateTimeField(auto_now=True)
    version = models.PositiveIntegerField(default=1)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                Lower("name"),
                condition=Q(archived_at__isnull=True),
                name="groups_unique_active_name",
            )
        ]

    def __str__(self):
        return self.name


class AssetGroupRuleVersion(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    group = models.ForeignKey(AssetGroup, on_delete=models.CASCADE, related_name="rule_versions")
    number = models.PositiveIntegerField()
    rule = models.JSONField()
    reason = models.CharField(max_length=500, blank=True)
    created_by = models.ForeignKey(_USER, null=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-number"]
        constraints = [
            models.UniqueConstraint(fields=["group", "number"], name="groups_rule_version_unique")
        ]


class AssetGroupMembership(models.Model):
    class Source(models.TextChoices):
        EXPLICIT = "explicit", "Added manually"
        EVALUATED = "evaluated", "Matched the rule"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    group = models.ForeignKey(AssetGroup, on_delete=models.CASCADE, related_name="memberships")
    asset = models.ForeignKey(Asset, on_delete=models.CASCADE, related_name="group_memberships")
    source = models.CharField(max_length=10, choices=Source.choices)
    rule_version = models.PositiveIntegerField(null=True, blank=True)
    added_at = models.DateTimeField()
    added_by = models.ForeignKey(
        _USER, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    added_reason = models.CharField(max_length=500, blank=True)
    removed_at = models.DateTimeField(null=True, blank=True)
    removed_by = models.ForeignKey(
        _USER, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    removed_reason = models.CharField(max_length=500, blank=True)

    class Meta:
        ordering = ["-added_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["group", "asset"],
                condition=Q(removed_at__isnull=True),
                name="groups_one_active_membership",
            )
        ]
        indexes = [
            models.Index(fields=["group", "removed_at"]),
            models.Index(fields=["asset", "removed_at"]),
        ]
