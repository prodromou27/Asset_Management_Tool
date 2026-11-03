import uuid

from django.conf import settings
from django.core.validators import RegexValidator
from django.db import models
from django.db.models.functions import Lower

from apps.organizations.models import Department, Location, Site

CATEGORY_CODE_VALIDATOR = RegexValidator(
    r"^[a-z0-9][a-z0-9-]{0,63}$", "Use lowercase letters, digits and hyphens."
)
FIELD_KEY_VALIDATOR = RegexValidator(
    r"^[a-z][a-z0-9_]{0,49}$",
    "Start with a letter; use lowercase letters, digits and underscores (max 50).",
)


class AssetCategory(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    code = models.CharField(max_length=64, unique=True, validators=[CATEGORY_CODE_VALIDATOR])
    name = models.CharField(max_length=100)
    parent = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.PROTECT, related_name="children"
    )
    description = models.CharField(max_length=500, blank=True)
    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    modified_at = models.DateTimeField(auto_now=True)
    version = models.PositiveIntegerField(default=1)

    class Meta:
        ordering = ["sort_order", "name"]
        verbose_name_plural = "asset categories"
        constraints = [
            models.UniqueConstraint(
                "parent",
                Lower("name"),
                condition=models.Q(parent__isnull=False),
                name="assets_category_name_unique_in_parent",
            ),
            models.UniqueConstraint(
                Lower("name"),
                condition=models.Q(parent__isnull=True),
                name="assets_category_name_unique_at_root",
            ),
        ]

    def __str__(self):
        return self.name


class CustomFieldDefinition(models.Model):
    """Typed field for a category; also applies to all descendant categories."""

    class FieldType(models.TextChoices):
        TEXT = "text", "Text"
        LONG_TEXT = "long_text", "Long text"
        INTEGER = "integer", "Integer"
        DECIMAL = "decimal", "Decimal"
        BOOLEAN = "boolean", "Yes/No"
        DATE = "date", "Date"
        CHOICE = "choice", "Choice"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    category = models.ForeignKey(
        AssetCategory, on_delete=models.PROTECT, related_name="field_definitions"
    )
    key = models.CharField(max_length=50, validators=[FIELD_KEY_VALIDATOR])
    label = models.CharField(max_length=100)
    field_type = models.CharField(max_length=20, choices=FieldType.choices)
    required = models.BooleanField(default=False)
    choices = models.JSONField(default=list, blank=True)
    help_text = models.CharField(max_length=300, blank=True)
    min_value = models.DecimalField(max_digits=20, decimal_places=6, null=True, blank=True)
    max_value = models.DecimalField(max_digits=20, decimal_places=6, null=True, blank=True)
    max_length = models.PositiveIntegerField(null=True, blank=True)
    sort_order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    modified_at = models.DateTimeField(auto_now=True)
    version = models.PositiveIntegerField(default=1)

    class Meta:
        ordering = ["sort_order", "label"]
        constraints = [
            models.UniqueConstraint("category", "key", name="assets_fielddef_key_unique")
        ]

    def __str__(self):
        return f"{self.category.code}.{self.key}"


class Asset(models.Model):
    class BusinessStatus(models.TextChoices):
        ORDERED = "ordered", "Ordered"
        IN_STOCK = "in_stock", "In stock"
        DEPLOYED = "deployed", "Deployed"
        ASSIGNED = "assigned", "Assigned"
        IN_REPAIR = "in_repair", "In repair"
        RETIRED = "retired", "Retired"
        DISPOSED = "disposed", "Disposed"
        LOST = "lost", "Lost"

    class ObservationStatus(models.TextChoices):
        RECENTLY_SEEN = "recently_seen", "Recently seen"
        STALE = "stale", "Stale"
        UNREACHABLE = "unreachable", "Unreachable"
        NEVER_SCANNED = "never_scanned", "Never scanned"
        MANUAL_ONLY = "manual_only", "Manual only"

    class SupportStatus(models.TextChoices):
        SUPPORTED = "supported", "Supported"
        EOL_ANNOUNCED = "eol_announced", "EOL announced"
        EXPIRING = "expiring", "Expiring"
        SECURITY_MAINTENANCE_ENDED = "security_maintenance_ended", "Security maintenance ended"
        EOS = "eos", "End of support"
        UNKNOWN = "unknown", "Unknown"
        NOT_ANNOUNCED = "not_announced", "Not announced"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=200)
    asset_tag = models.CharField(max_length=64, null=True, blank=True)
    category = models.ForeignKey(AssetCategory, on_delete=models.PROTECT, related_name="assets")

    manufacturer = models.CharField(max_length=150, blank=True)
    model = models.CharField(max_length=150, blank=True)
    serial_number = models.CharField(max_length=150, blank=True)
    os_name = models.CharField(max_length=150, blank=True)
    os_version = models.CharField(max_length=100, blank=True)
    firmware_version = models.CharField(max_length=100, blank=True)

    site = models.ForeignKey(Site, on_delete=models.PROTECT, related_name="assets")
    location = models.ForeignKey(
        Location, null=True, blank=True, on_delete=models.PROTECT, related_name="assets"
    )
    department = models.ForeignKey(
        Department, null=True, blank=True, on_delete=models.PROTECT, related_name="assets"
    )
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="owned_assets",
    )

    business_status = models.CharField(
        max_length=20, choices=BusinessStatus.choices, default=BusinessStatus.IN_STOCK
    )
    # Set by discovery (Task 004+) and the EOL engine (Task 015); read-only via the API.
    observation_status = models.CharField(
        max_length=20, choices=ObservationStatus.choices, default=ObservationStatus.MANUAL_ONLY
    )
    support_status = models.CharField(
        max_length=30, choices=SupportStatus.choices, default=SupportStatus.UNKNOWN
    )

    notes = models.TextField(blank=True, max_length=10000)
    custom_fields = models.JSONField(default=dict, blank=True)

    archived_at = models.DateTimeField(null=True, blank=True)
    archived_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    archive_reason = models.CharField(max_length=500, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    modified_at = models.DateTimeField(auto_now=True)
    modified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    version = models.PositiveIntegerField(default=1)

    class Meta:
        ordering = ["-modified_at"]
        constraints = [
            models.UniqueConstraint(
                "asset_tag",
                condition=models.Q(asset_tag__isnull=False),
                name="assets_asset_tag_unique",
            )
        ]
        indexes = [
            models.Index(fields=["site", "category", "business_status"]),
            models.Index(fields=["manufacturer", "model"]),
            models.Index(fields=["serial_number"]),
            models.Index(fields=["archived_at"]),
            models.Index(fields=["modified_at"]),
        ]

    def __str__(self):
        return self.name

    @property
    def is_archived(self) -> bool:
        return self.archived_at is not None


# Fields a discovery source may populate. Everything else on Asset is business-owned
# and never written by discovery (docs/00, docs/05).
TECHNICAL_FIELDS = (
    "manufacturer",
    "model",
    "serial_number",
    "os_name",
    "os_version",
    "firmware_version",
)


class Source(models.TextChoices):
    """Where a network identifier came from. Only `manual` rows are editable via the API."""

    MANUAL = "manual", "Manual"
    LIBRENMS = "librenms", "LibreNMS"
    ENDPOINT_CENTRAL = "endpoint_central", "Endpoint Central"
    INTUNE = "intune", "Intune"
    DEFENDER = "defender", "Defender"
    IMPORT = "import", "Import"
    FIXTURE = "fixture", "Fixture import"


class _Evidence(models.Model):
    source = models.CharField(max_length=30, choices=Source.choices, default=Source.MANUAL)
    source_ref = models.CharField(max_length=200, blank=True)
    observed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        abstract = True


class AssetInterface(_Evidence):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    asset = models.ForeignKey(Asset, on_delete=models.CASCADE, related_name="interfaces")
    name = models.CharField(max_length=64)
    mac_address = models.CharField(max_length=17, blank=True)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                "asset", "source", "name", name="assets_interface_name_unique_per_source"
            )
        ]
        indexes = [models.Index(fields=["mac_address"])]


class AssetIPAddress(_Evidence):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    asset = models.ForeignKey(Asset, on_delete=models.CASCADE, related_name="ip_addresses")
    interface = models.ForeignKey(
        AssetInterface, null=True, blank=True, on_delete=models.SET_NULL, related_name="addresses"
    )
    address = models.GenericIPAddressField()
    is_primary = models.BooleanField(default=False)
    # IPs are only meaningful within a site/VRF (docs/03); never globally unique.
    site = models.ForeignKey(
        Site, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    vrf = models.CharField(max_length=64, blank=True)

    class Meta:
        ordering = ["-is_primary", "address"]
        constraints = [
            models.UniqueConstraint(
                "asset", "source", "address", name="assets_ip_unique_per_asset_source"
            )
        ]
        indexes = [models.Index(fields=["address"])]


class AssetHostname(_Evidence):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    asset = models.ForeignKey(Asset, on_delete=models.CASCADE, related_name="hostnames")
    hostname = models.CharField(max_length=253)
    is_primary = models.BooleanField(default=False)

    class Meta:
        ordering = ["-is_primary", "hostname"]
        constraints = [
            models.UniqueConstraint(
                "asset", "source", "hostname", name="assets_hostname_unique_per_asset_source"
            )
        ]
        indexes = [models.Index(fields=["hostname"])]


class AssetHistoryEntry(models.Model):
    """Append-only per-asset timeline. PostgreSQL trigger blocks UPDATE/DELETE."""

    class ChangeType(models.TextChoices):
        CREATED = "created", "Created"
        UPDATED = "updated", "Updated"
        REASSIGNED = "reassigned", "Reassigned"
        RECLASSIFIED = "reclassified", "Reclassified"
        ARCHIVED = "archived", "Archived"
        RESTORED = "restored", "Restored"
        DISCOVERED = "discovered", "Updated from source"
        LINKED = "linked", "Source linked"
        UNLINKED = "unlinked", "Source unlinked"
        MERGED = "merged", "Merged"
        UNMERGED = "unmerged", "Merge reverted"
        FIELD_LOCKED = "field_locked", "Field locked"
        FIELD_UNLOCKED = "field_unlocked", "Field unlocked"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    asset = models.ForeignKey(Asset, on_delete=models.PROTECT, related_name="history")
    occurred_at = models.DateTimeField(auto_now_add=True, db_index=True)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    actor_label = models.CharField(max_length=255)
    change_type = models.CharField(max_length=20, choices=ChangeType.choices)
    changes = models.JSONField(default=dict)
    reason = models.CharField(max_length=500, blank=True)
    version = models.PositiveIntegerField()
    request_id = models.CharField(max_length=64, blank=True)

    class Meta:
        ordering = ["-occurred_at"]
        indexes = [models.Index(fields=["asset", "occurred_at"])]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise RuntimeError("Asset history is append-only")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise RuntimeError("Asset history is append-only")


class FieldProvenance(models.Model):
    """Where the current value of one technical field came from."""

    class Kind(models.TextChoices):
        MANUAL = "manual", "Manual"
        DISCOVERY = "discovery", "Discovery"

    asset = models.ForeignKey(Asset, on_delete=models.CASCADE, related_name="field_provenance")
    field = models.CharField(max_length=40)
    kind = models.CharField(max_length=20, choices=Kind.choices)
    instance = models.ForeignKey(
        "integrations.IntegrationInstance",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="+",
    )
    observation = models.ForeignKey(
        "observations.Observation",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="+",
    )
    value = models.CharField(max_length=200, blank=True)
    observed_at = models.DateTimeField(null=True, blank=True)
    recorded_at = models.DateTimeField(auto_now=True)
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )

    class Meta:
        constraints = [
            models.UniqueConstraint("asset", "field", name="assets_field_provenance_unique")
        ]


class FieldLock(models.Model):
    """Manually approved value: discovery may not overwrite it, only raise a conflict."""

    asset = models.ForeignKey(Asset, on_delete=models.CASCADE, related_name="field_locks")
    field = models.CharField(max_length=40)
    locked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    locked_at = models.DateTimeField(auto_now_add=True)
    reason = models.CharField(max_length=300, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint("asset", "field", name="assets_field_lock_unique")]


class SavedView(models.Model):
    """A named inventory view: filters, visible columns and ordering. Filters are
    re-applied through visible_assets(), so a shared view never widens site scope."""

    class Resource(models.TextChoices):
        ASSETS = "assets", "Assets"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="saved_views"
    )
    resource = models.CharField(max_length=30, choices=Resource.choices, default=Resource.ASSETS)
    name = models.CharField(max_length=100)
    is_shared = models.BooleanField(default=False)
    filters = models.JSONField(default=dict, blank=True)
    columns = models.JSONField(default=list, blank=True)
    ordering = models.CharField(max_length=40, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    modified_at = models.DateTimeField(auto_now=True)
    version = models.PositiveIntegerField(default=1)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                "owner", "resource", Lower("name"), name="assets_savedview_name_unique_per_owner"
            )
        ]
