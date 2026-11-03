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
        # Adapter implemented and contract-tested on sanitized fixtures, not yet
        # validated against a live installation (docs/15 A21).
        BETA = "beta", "Beta (fixture-tested)"
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

    class AuthScheme(models.TextChoices):
        BEARER = "bearer", "Authorization: Bearer"
        X_AUTH_TOKEN = "x_auth_token", "X-Auth-Token header"
        AUTHORIZATION = "authorization", "Authorization: <token>"

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

    # --- Connection (adapter-backed sources) ---------------------------------
    # Reference to a secret, never the secret: "env:NAME" or "file:name" under
    # ITAM_SECRETS_DIR. Resolved only inside the worker/API process at call time.
    credential_ref = models.CharField(max_length=200, blank=True)
    auth_scheme = models.CharField(
        max_length=20, choices=AuthScheme.choices, default=AuthScheme.BEARER
    )
    ca_bundle_ref = models.CharField(max_length=200, blank=True)
    timeout_seconds = models.PositiveSmallIntegerField(
        default=30, validators=[MinValueValidator(5), MaxValueValidator(120)]
    )
    max_retries = models.PositiveSmallIntegerField(
        default=3, validators=[MinValueValidator(0), MaxValueValidator(6)]
    )
    requests_per_second = models.PositiveSmallIntegerField(
        default=5, validators=[MinValueValidator(1), MaxValueValidator(20)]
    )
    sync_interval_minutes = models.PositiveIntegerField(
        default=360, validators=[MinValueValidator(15), MaxValueValidator(10080)]
    )
    evidence_interval_hours = models.PositiveIntegerField(
        default=24, validators=[MinValueValidator(1), MaxValueValidator(168)]
    )
    enrichment_max_age_hours = models.PositiveIntegerField(
        default=24, validators=[MinValueValidator(1), MaxValueValidator(720)]
    )
    source_timezone = models.CharField(max_length=64, default="UTC")
    last_evidence_at = models.DateTimeField(null=True, blank=True)

    # --- Live access gate ------------------------------------------------------
    # No request reaches the source until an admin records approval (who, why)
    # AND the deployment allows live integrations (ITAM_ALLOW_LIVE_INTEGRATIONS).
    live_access_approved = models.BooleanField(default=False)
    live_access_approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    live_access_approved_at = models.DateTimeField(null=True, blank=True)
    live_access_reason = models.CharField(max_length=500, blank=True)

    last_test_at = models.DateTimeField(null=True, blank=True)
    last_test_ok = models.BooleanField(null=True, blank=True)
    last_test_message = models.CharField(max_length=500, blank=True)
    source_software_version = models.CharField(max_length=100, blank=True)
    capabilities = models.JSONField(default=dict, blank=True)
    consecutive_failures = models.PositiveIntegerField(default=0)

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
        QUEUED = "queued", "Queued"
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
    warnings = models.PositiveIntegerField(default=0)
    warning_samples = models.JSONField(default=list, blank=True)
    checkpoint = models.CharField(max_length=200, blank=True)
    error_message = models.CharField(max_length=500, blank=True)
    # Progress for long adapter runs (docs/02 job semantics).
    phase = models.CharField(max_length=40, blank=True)
    devices_total = models.PositiveIntegerField(default=0)
    devices_processed = models.PositiveIntegerField(default=0)
    devices_enriched = models.PositiveIntegerField(default=0)
    evidence_rows = models.PositiveIntegerField(default=0)
    api_requests = models.PositiveIntegerField(default=0)
    heartbeat_at = models.DateTimeField(null=True, blank=True)

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
