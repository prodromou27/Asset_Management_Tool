"""Software products, versions and installations (Task 016a, docs/03 "Software", docs/06).

- ``SoftwareProduct``: publisher + name as reported, normalised only by case and spacing
  (no fuzzy merging; "Office 2016" and "Office 2019" stay different products).
- ``SoftwareVersion``: one reported version string of a product. Its lifecycle match and
  assessment against the lifecycle catalogue (software products) are kept here, per
  version, because every installation of a version shares them (ASM-54).
- ``SoftwareInstallation``: one product version seen on one device.
  * Discovered rows are keyed by the source device (instance + external ID), like
    Defender facts: the asset is resolved through the device's source link when read,
    so linking, unlinking or merging never leaves software on the wrong asset.
  * Manual rows reference the asset directly (``instance`` is empty).
  Raw publisher/name/version strings are preserved. A row is marked removed only when a
  complete read for that device no longer reports it; nothing is deleted.
"""

from django.conf import settings
from django.db import models
from django.db.models import Q

_USER = settings.AUTH_USER_MODEL


class SoftwareProduct(models.Model):
    id = models.BigAutoField(primary_key=True)
    publisher = models.CharField(max_length=200, blank=True)
    publisher_key = models.CharField(max_length=200, blank=True, editable=False)
    name = models.CharField(max_length=300)
    name_key = models.CharField(max_length=300, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name_key", "publisher_key"]
        constraints = [
            models.UniqueConstraint(
                fields=["publisher_key", "name_key"], name="software_product_unique"
            )
        ]
        indexes = [models.Index(fields=["name_key"])]

    def __str__(self):
        return f"{self.publisher} {self.name}".strip()


class SoftwareVersion(models.Model):
    id = models.BigAutoField(primary_key=True)
    product = models.ForeignKey(SoftwareProduct, on_delete=models.PROTECT, related_name="versions")
    version = models.CharField(max_length=100, blank=True)
    version_key = models.CharField(max_length=100, blank=True, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)

    # Lifecycle match (lifecycle catalogue products of kind "software").
    lifecycle_state = models.CharField(max_length=15, default="no_match")
    lifecycle_method = models.CharField(max_length=10, default="none")
    lifecycle_product = models.ForeignKey(
        "lifecycle.LifecycleProduct",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="software_versions",
    )
    lifecycle_candidates = models.JSONField(default=list, blank=True)
    lifecycle_rejected = models.JSONField(default=list, blank=True)
    lifecycle_reviewed_by = models.ForeignKey(
        _USER, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    lifecycle_reviewed_at = models.DateTimeField(null=True, blank=True)
    # Lifecycle assessment (same rules as hardware/OS, docs/06).
    lifecycle_status = models.CharField(max_length=30, default="unknown")
    lifecycle_milestone_type = models.CharField(max_length=30, blank=True)
    lifecycle_milestone_date = models.DateField(null=True, blank=True)
    lifecycle_days_remaining = models.IntegerField(null=True, blank=True)
    lifecycle_evidence_quality = models.CharField(max_length=15, blank=True)
    lifecycle_reasons = models.JSONField(default=list, blank=True)
    lifecycle_assessed_at = models.DateTimeField(null=True, blank=True)
    lifecycle_version = models.PositiveIntegerField(default=1)  # optimistic lock for reviews

    class Meta:
        ordering = ["product", "version_key"]
        constraints = [
            models.UniqueConstraint(
                fields=["product", "version_key"], name="software_version_unique"
            )
        ]
        indexes = [
            models.Index(fields=["lifecycle_state"]),
            models.Index(fields=["lifecycle_status"]),
        ]

    def __str__(self):
        return f"{self.product} {self.version}".strip()


class SoftwareInstallation(models.Model):
    id = models.BigAutoField(primary_key=True)
    version = models.ForeignKey(
        SoftwareVersion, on_delete=models.PROTECT, related_name="installations"
    )
    # Discovered: the source device. Manual: empty instance, asset set.
    instance = models.ForeignKey(
        "integrations.IntegrationInstance",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="+",
    )
    external_id = models.CharField(max_length=200, blank=True)
    asset = models.ForeignKey(
        "assets.Asset", null=True, blank=True, on_delete=models.CASCADE, related_name="software"
    )
    raw_publisher = models.CharField(max_length=200, blank=True)
    raw_name = models.CharField(max_length=300)
    raw_version = models.CharField(max_length=100, blank=True)
    source_ref = models.CharField(max_length=200, blank=True)  # app ID in the source
    installed_on = models.DateField(null=True, blank=True)
    first_seen_at = models.DateTimeField()
    last_seen_at = models.DateTimeField()
    removed_at = models.DateTimeField(null=True, blank=True)
    removed_reason = models.CharField(max_length=300, blank=True)
    created_by = models.ForeignKey(
        _USER, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    note = models.CharField(max_length=500, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["instance", "external_id", "version"],
                condition=Q(instance__isnull=False),
                name="software_install_unique_discovered",
            ),
            models.UniqueConstraint(
                fields=["asset", "version"],
                condition=Q(instance__isnull=True, removed_at__isnull=True),
                name="software_install_unique_manual",
            ),
            models.CheckConstraint(
                condition=Q(instance__isnull=False, asset__isnull=True)
                | Q(instance__isnull=True, asset__isnull=False),
                name="software_install_one_owner",
            ),
        ]
        indexes = [
            models.Index(fields=["instance", "external_id"]),
            models.Index(fields=["version", "removed_at"]),
            models.Index(fields=["asset", "removed_at"]),
        ]
