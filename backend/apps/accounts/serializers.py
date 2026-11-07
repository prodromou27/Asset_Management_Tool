from django.core.exceptions import ValidationError as DjangoValidationError
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from .general import DisplayPreferencesSerializer
from .models import USERNAME_VALIDATOR, GeneralSettings, Permission, Role, SecuritySettings, User


class PermissionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Permission
        fields = ["code", "description"]
        read_only_fields = fields


class RoleSerializer(serializers.ModelSerializer):
    permissions = serializers.SlugRelatedField(many=True, read_only=True, slug_field="code")

    class Meta:
        model = Role
        fields = ["code", "name", "description", "is_system", "permissions"]
        read_only_fields = fields


class RoleSummarySerializer(serializers.ModelSerializer):
    class Meta:
        model = Role
        fields = ["code", "name"]


class SiteGrantSerializer(serializers.Serializer):
    id = serializers.UUIDField(source="site.id")
    code = serializers.CharField(source="site.code")
    name = serializers.CharField(source="site.name")


class UserSerializer(serializers.ModelSerializer):
    roles = RoleSummarySerializer(many=True, read_only=True)
    sites = SiteGrantSerializer(source="site_grants", many=True, read_only=True)
    is_locked = serializers.BooleanField(read_only=True)
    disabled_by = serializers.SlugRelatedField(
        read_only=True, allow_null=True, slug_field="username"
    )
    created_by = serializers.SlugRelatedField(
        read_only=True, allow_null=True, slug_field="username"
    )

    class Meta:
        model = User
        fields = [
            "id",
            "username",
            "display_name",
            "email",
            "entra_tenant_id",
            "entra_object_id",
            "roles",
            "all_sites",
            "sites",
            "is_active",
            "is_locked",
            "locked_until",
            "must_change_password",
            "last_login",
            "password_changed_at",
            "disabled_at",
            "disabled_by",
            "disabled_reason",
            "created_at",
            "created_by",
            "modified_at",
            "version",
        ]
        read_only_fields = fields


class UserCreateSerializer(serializers.Serializer):
    username = serializers.CharField(max_length=150)
    display_name = serializers.CharField(max_length=150)
    email = serializers.EmailField(max_length=254, required=False, allow_blank=True, default="")
    roles = serializers.ListField(child=serializers.CharField(max_length=50), allow_empty=False)
    password = serializers.CharField(write_only=True, trim_whitespace=False, max_length=128)

    def validate_username(self, value):
        value = value.strip().lower()
        try:
            USERNAME_VALIDATOR(value)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(exc.messages) from exc
        return value


class UserUpdateSerializer(serializers.Serializer):
    display_name = serializers.CharField(max_length=150, required=False)
    email = serializers.EmailField(max_length=254, required=False, allow_blank=True)
    roles = serializers.ListField(
        child=serializers.CharField(max_length=50), required=False, allow_empty=False
    )
    all_sites = serializers.BooleanField(required=False)
    site_ids = serializers.ListField(child=serializers.UUIDField(), required=False, max_length=500)


class DisableUserSerializer(serializers.Serializer):
    reason = serializers.CharField(min_length=5, max_length=500)


class ResetPasswordSerializer(serializers.Serializer):
    password = serializers.CharField(write_only=True, trim_whitespace=False, max_length=128)


class LoginSerializer(serializers.Serializer):
    username = serializers.CharField(max_length=150)
    password = serializers.CharField(trim_whitespace=False, max_length=128)


class ChangePasswordSerializer(serializers.Serializer):
    current_password = serializers.CharField(trim_whitespace=False, max_length=128)
    new_password = serializers.CharField(trim_whitespace=False, max_length=128)


class MeSerializer(serializers.ModelSerializer):
    must_change_password = serializers.SerializerMethodField()
    roles = RoleSummarySerializer(many=True, read_only=True)
    permissions = serializers.SerializerMethodField()
    display_preferences = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            "id",
            "username",
            "display_name",
            "email",
            "roles",
            "permissions",
            "all_sites",
            "must_change_password",
            "display_preferences",
        ]
        read_only_fields = fields

    def get_permissions(self, obj) -> list[str]:
        return sorted(obj.permission_codes())

    def get_must_change_password(self, obj) -> bool:
        request = self.context.get("request")
        return obj.must_change_password and not (
            request and request.session.get("itam_auth_method") == "entra"
        )

    @extend_schema_field(DisplayPreferencesSerializer)
    def get_display_preferences(self, obj):
        return DisplayPreferencesSerializer(GeneralSettings.load()).data


class SecuritySettingsSerializer(serializers.ModelSerializer):
    modified_by = serializers.SlugRelatedField(
        read_only=True, allow_null=True, slug_field="username"
    )

    class Meta:
        model = SecuritySettings
        fields = [
            "session_idle_timeout_minutes",
            "session_absolute_timeout_hours",
            "lockout_threshold",
            "lockout_duration_minutes",
            "password_min_length",
            "version",
            "modified_at",
            "modified_by",
        ]
        read_only_fields = ["version", "modified_at", "modified_by"]
        extra_kwargs = {
            field: {"required": True}
            for field in fields
            if field not in ("version", "modified_at", "modified_by")
        }


class AuthProviderSerializer(serializers.Serializer):
    id = serializers.CharField()
    kind = serializers.ChoiceField(choices=["local", "oidc"])
    label = serializers.CharField()
    status = serializers.ChoiceField(choices=["available", "planned"])


class UserLookupSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["id", "username", "display_name"]
        read_only_fields = fields
