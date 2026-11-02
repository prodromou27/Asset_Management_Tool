import uuid

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from apps.organizations.models import Site


class DiscoverySource(models.Model):
    """Catalogue of source types. `planned` sources have no working adapter yet and
    cannot be presented as Available (docs/00, docs/15 A21)."""

    class Kind(models.TextChoices):
        NETWORK = "network", "Network inventory"
        ENDPOINT = "endpoint", "Endpoint management"
        SECURITY = "security", "Security"
        DIRECTORY = "directory", "Directory and licensing"
        IMPORT = "import", "Import"

    class Availability(models.TextChoices):
        PLANNED = "planned", "Planned"
        AVAILABLE = "available", "Available"

    code = models.CharField(max_length=40, primary_key=True)
    name = models.CharField(max_length=100)
    kind = models.CharField(max_length=20, choices=Kind.choices)
    availability = models.CharField(max_length=20, choices=Availability.choices)
    description = models.CharField(max_length=300, blank=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class IntegrationInstance(models.Model):
    """One configured connection to a source. External IDs are scoped to it."""

    class Status(models.TextChoices):
        CONFIGURED = "configured", "Configured"
        AVAILABLE = "available", "Available"
        DEGRADED = "degraded", "Degraded"
        DISCONNECTED = "disconnected", "Disconnected"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    source = models.ForeignKey(DiscoverySource, on_delete=models.PROTECT, related_name="instances")
    name = models.CharField(max_length=100, unique=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.CONFIGURED)
    is_enabled = models.BooleanField(default=True)
    base_url = models.CharField(max_length=300, blank=True)
    # Site for new-device candidates and IP context; candidates are scoped by it.
    default_site = models.ForeignKey(Site, on_delete=models.PROTECT, related_name="+")
    default_vrf = models.CharField(max_length=64, blank=True)
    stale_after_hours = models.PositiveIntegerField(
        default=48, validators=[MinValueValidator(1), MaxValueValidator(720)]
    )
    # Policy switch (docs/03 rule 2): link verified manufacturer+serial matches
    # without review. Off by default.
    auto_link_strong_matches = models.BooleanField(default=False)
    last_attempt_at = models.DateTimeField(null=True, blank=True)
    last_success_at = models.DateTimeField(null=True, blank=True)
    last_error = models.CharField(max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    modified_at = models.DateTimeField(auto_now=True)
    version = models.PositiveIntegerField(default=1)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

    @property
    def source_key(self) -> str:
        """Prefix stored in AssetInterface/IP/Hostname.source_ref for rows from this instance."""
        return f"{self.pk}:"


class SyncRun(models.Model):
    class Mode(models.TextChoices):
        FULL = "full", "Full"
        INCREMENTAL = "incremental", "Incremental"

    class Status(models.TextChoices):
        RUNNING = "running", "Running"
        SUCCEEDED = "succeeded", "Succeeded"
        PARTIAL = "partial", "Partial"
        FAILED = "failed", "Failed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    instance = models.ForeignKey(IntegrationInstance, on_delete=models.PROTECT, related_name="runs")
    mode = models.CharField(max_length=20, choices=Mode.choices)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.RUNNING)
    triggered_by = models.CharField(max_length=150)
    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    records_received = models.PositiveIntegerField(default=0)
    observations_created = models.PositiveIntegerField(default=0)
    observations_unchanged = models.PositiveIntegerField(default=0)
    links_refreshed = models.PositiveIntegerField(default=0)
    links_marked_stale = models.PositiveIntegerField(default=0)
    candidates_opened = models.PositiveIntegerField(default=0)
    candidates_updated = models.PositiveIntegerField(default=0)
    assets_updated = models.PositiveIntegerField(default=0)
    conflicts_opened = models.PositiveIntegerField(default=0)
    errors = models.PositiveIntegerField(default=0)
    error_samples = models.JSONField(default=list, blank=True)
    checkpoint = models.CharField(max_length=200, blank=True)
    error_message = models.CharField(max_length=500, blank=True)

    class Meta:
        ordering = ["-started_at"]
        indexes = [models.Index(fields=["instance", "started_at"])]


class FieldAuthorityPolicy(models.Model):
    """Singleton (pk=1): which source wins per technical field when sources disagree.
    Manual locks always win over every source."""

    id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    precedence = models.JSONField(default=dict)
    version = models.PositiveIntegerField(default=1)
    modified_at = models.DateTimeField(auto_now=True)
    modified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )

    @classmethod
    def load(cls) -> "FieldAuthorityPolicy":
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    def rank(self, field: str, source_code: str) -> int:
        order = self.precedence.get(field, [])
        return order.index(source_code) if source_code in order else len(order)
