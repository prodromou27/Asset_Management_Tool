import uuid

from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.core.validators import MaxValueValidator, MinValueValidator, RegexValidator
from django.db import models
from django.db.models.functions import Lower
from django.utils import timezone
from django.utils.crypto import salted_hmac

USERNAME_VALIDATOR = RegexValidator(
    r"^[a-z0-9][a-z0-9._-]{2,149}$",
    "Use 3-150 lowercase letters, digits, dots, hyphens or underscores.",
)


class Permission(models.Model):
    code = models.CharField(max_length=100, primary_key=True)
    description = models.CharField(max_length=255)

    class Meta:
        ordering = ["code"]

    def __str__(self):
        return self.code


class Role(models.Model):
    code = models.CharField(max_length=50, primary_key=True)
    name = models.CharField(max_length=100, unique=True)
    description = models.CharField(max_length=255, blank=True)
    is_system = models.BooleanField(default=True)
    permissions = models.ManyToManyField(Permission, related_name="roles", blank=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class UserManager(BaseUserManager):
    def create_user(self, username, password, **extra):
        extra["email"] = extra.get("email", "").strip().lower()
        user = self.model(username=username.strip().lower(), **extra)
        user.set_password(password)
        user.password_changed_at = timezone.now()
        user.full_clean(exclude=["password"])
        user.save()
        return user


class User(AbstractBaseUser):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    username = models.CharField(max_length=150, unique=True, validators=[USERNAME_VALIDATOR])
    email = models.EmailField(max_length=254, blank=True)
    display_name = models.CharField(max_length=150)
    roles = models.ManyToManyField(Role, related_name="users", blank=True)
    # Site scope: True = every site; otherwise only sites granted via UserSiteGrant.
    all_sites = models.BooleanField(default=False)

    is_active = models.BooleanField(default=True)
    must_change_password = models.BooleanField(default=False)
    password_changed_at = models.DateTimeField(null=True, blank=True)
    failed_login_count = models.PositiveIntegerField(default=0)
    last_failed_login_at = models.DateTimeField(null=True, blank=True)
    locked_until = models.DateTimeField(null=True, blank=True)
    session_epoch = models.PositiveIntegerField(default=0)
    entra_tenant_id = models.UUIDField(null=True, blank=True)
    entra_object_id = models.UUIDField(null=True, blank=True)
    emergency_access_until = models.DateTimeField(null=True, blank=True)

    disabled_at = models.DateTimeField(null=True, blank=True)
    disabled_reason = models.CharField(max_length=500, blank=True)
    disabled_by = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    created_by = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    modified_at = models.DateTimeField(auto_now=True)
    version = models.PositiveIntegerField(default=1)

    objects = UserManager()

    USERNAME_FIELD = "username"
    EMAIL_FIELD = "email"
    REQUIRED_FIELDS = ["display_name"]

    class Meta:
        ordering = ["username"]
        constraints = [
            models.UniqueConstraint(
                fields=["entra_tenant_id", "entra_object_id"], name="accounts_entra_identity_unique"
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(entra_tenant_id__isnull=True, entra_object_id__isnull=True)
                    | models.Q(entra_tenant_id__isnull=False, entra_object_id__isnull=False)
                ),
                name="accounts_entra_identity_pair",
            ),
            models.UniqueConstraint(
                Lower("email"),
                condition=~models.Q(email=""),
                name="accounts_user_email_ci_unique",
            ),
        ]

    def __str__(self):
        return self.username

    def _get_session_auth_hash(self, secret=None):
        # Includes session_epoch so bumping it revokes every existing session.
        return salted_hmac(
            "apps.accounts.User.get_session_auth_hash",
            f"{self.password}:{self.session_epoch}",
            secret=secret,
            algorithm="sha256",
        ).hexdigest()

    @property
    def is_locked(self) -> bool:
        return self.locked_until is not None and self.locked_until > timezone.now()

    def permission_codes(self) -> set[str]:
        # Cached per instance; each request loads a fresh user, so grants still
        # take effect on the next request.
        if not self.is_active:
            return set()
        cached = getattr(self, "_permission_cache", None)
        if cached is None:
            cached = set(
                Permission.objects.filter(roles__users=self)
                .values_list("code", flat=True)
                .distinct()
            )
            self._permission_cache = cached
        return cached

    def has_permission(self, code: str) -> bool:
        return code in self.permission_codes()


class GeneralSettings(models.Model):
    """Organization display policy; UTC storage and domain retention remain unchanged."""

    id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    organization_name = models.CharField(max_length=100, default="ITAM")
    timezone = models.CharField(max_length=64, default="Asia/Nicosia")
    date_format = models.CharField(
        max_length=20,
        choices=[
            ("day_month_year", "Day month year"),
            ("month_day_year", "Month day year"),
            ("iso", "ISO 8601"),
        ],
        default="day_month_year",
    )
    language = models.CharField(max_length=5, choices=[("en", "English")], default="en")
    support_contact = models.EmailField(blank=True)
    version = models.PositiveIntegerField(default=1)
    modified_at = models.DateTimeField(auto_now=True)
    modified_by = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )

    class Meta:
        constraints = [
            models.CheckConstraint(condition=models.Q(id=1), name="general_settings_singleton")
        ]

    @classmethod
    def load(cls):
        return cls.objects.get_or_create(pk=1)[0]


class OidcAttempt(models.Model):
    """One-use browser-bound receipt. PKCE/nonce are held by Authlib's short-lived cache."""

    state_digest = models.CharField(max_length=64, primary_key=True)
    browser_digest = models.CharField(max_length=64)
    policy_digest = models.CharField(max_length=64)
    expires_at = models.DateTimeField(db_index=True)


class SecuritySettings(models.Model):
    """Singleton (pk=1) of admin-configurable authentication policy."""

    id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    session_idle_timeout_minutes = models.PositiveIntegerField(
        default=30, validators=[MinValueValidator(5), MaxValueValidator(480)]
    )
    session_absolute_timeout_hours = models.PositiveIntegerField(
        default=12, validators=[MinValueValidator(1), MaxValueValidator(72)]
    )
    lockout_threshold = models.PositiveIntegerField(
        default=5, validators=[MinValueValidator(3), MaxValueValidator(20)]
    )
    lockout_duration_minutes = models.PositiveIntegerField(
        default=15, validators=[MinValueValidator(1), MaxValueValidator(1440)]
    )
    password_min_length = models.PositiveIntegerField(
        default=12, validators=[MinValueValidator(12), MaxValueValidator(128)]
    )
    version = models.PositiveIntegerField(default=1)
    modified_at = models.DateTimeField(auto_now=True)
    modified_by = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )

    class Meta:
        verbose_name_plural = "security settings"

    @classmethod
    def load(cls) -> "SecuritySettings":
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj
