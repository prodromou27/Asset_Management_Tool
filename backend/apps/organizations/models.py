import uuid

from django.conf import settings
from django.core.validators import RegexValidator
from django.db import models
from django.db.models.functions import Lower

SITE_CODE_VALIDATOR = RegexValidator(
    r"^[A-Z0-9][A-Z0-9_-]{0,31}$",
    "Use 1-32 uppercase letters, digits, hyphens or underscores.",
)


class Site(models.Model):
    """Organizational site. Parent sites (e.g. a region) grant access to children."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    code = models.CharField(max_length=32, unique=True, validators=[SITE_CODE_VALIDATOR])
    name = models.CharField(max_length=150)
    parent = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.PROTECT, related_name="children"
    )
    description = models.CharField(max_length=500, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    modified_at = models.DateTimeField(auto_now=True)
    version = models.PositiveIntegerField(default=1)

    class Meta:
        ordering = ["code"]

    def __str__(self):
        return self.code


class Location(models.Model):
    """Building/floor/room/rack inside one site. Never spans sites."""

    class Kind(models.TextChoices):
        BUILDING = "building", "Building"
        FLOOR = "floor", "Floor"
        ROOM = "room", "Room"
        RACK = "rack", "Rack"
        OTHER = "other", "Other"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    site = models.ForeignKey(Site, on_delete=models.PROTECT, related_name="locations")
    parent = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.PROTECT, related_name="children"
    )
    name = models.CharField(max_length=150)
    kind = models.CharField(max_length=20, choices=Kind.choices, default=Kind.ROOM)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    modified_at = models.DateTimeField(auto_now=True)
    version = models.PositiveIntegerField(default=1)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                "site",
                "parent",
                Lower("name"),
                condition=models.Q(parent__isnull=False),
                name="organizations_location_name_unique_in_parent",
            ),
            models.UniqueConstraint(
                "site",
                Lower("name"),
                condition=models.Q(parent__isnull=True),
                name="organizations_location_name_unique_at_root",
            ),
        ]

    def __str__(self):
        return self.name


class Department(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=150)
    code = models.CharField(max_length=32, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    modified_at = models.DateTimeField(auto_now=True)
    version = models.PositiveIntegerField(default=1)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(Lower("name"), name="organizations_department_name_ci_unique")
        ]

    def __str__(self):
        return self.name


class UserSiteGrant(models.Model):
    """Grants a user access to a site and all of its descendant sites."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="site_grants"
    )
    site = models.ForeignKey(Site, on_delete=models.PROTECT, related_name="user_grants")
    granted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="+",
    )
    granted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint("user", "site", name="organizations_usersitegrant_unique")
        ]
