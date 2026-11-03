from django.contrib.auth import get_user_model
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.organizations import scope
from apps.organizations.models import Department, Location, Site

from . import custom_fields as cf
from . import network
from .models import (
    Asset,
    AssetCategory,
    AssetHistoryEntry,
    AssetHostname,
    AssetInterface,
    AssetIPAddress,
    CustomFieldDefinition,
)
from .tree import CategoryTree

ASSET_TAG_PATTERN = r"^[A-Z0-9][A-Z0-9._/-]{0,63}$"


def _tree(context) -> CategoryTree:
    tree = context.get("tree")
    if tree is None:
        tree = context["tree"] = CategoryTree()
    return tree


# --- Reference summaries --------------------------------------------------------


class RefSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField()


class SiteRefSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    code = serializers.CharField()
    name = serializers.CharField()


class UserRefSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    username = serializers.CharField()
    display_name = serializers.CharField()


class CategoryRefSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField()
    path = serializers.CharField()


def _category_ref(obj, context):
    return {
        "id": obj.category_id,
        "name": obj.category.name,
        "path": _tree(context).path(obj.category_id),
    }


# --- Categories -----------------------------------------------------------------


class AssetCategorySerializer(serializers.ModelSerializer):
    parent = serializers.PrimaryKeyRelatedField(read_only=True, allow_null=True)
    path = serializers.SerializerMethodField()
    depth = serializers.SerializerMethodField()

    class Meta:
        model = AssetCategory
        fields = [
            "id",
            "code",
            "name",
            "parent",
            "path",
            "depth",
            "description",
            "is_active",
            "sort_order",
            "modified_at",
            "version",
        ]
        read_only_fields = fields

    def get_path(self, obj) -> str:
        return _tree(self.context).path(obj.pk)

    def get_depth(self, obj) -> int:
        return _tree(self.context).depth(obj.pk)


class AssetCategoryWriteSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=100)
    code = serializers.CharField(max_length=64, required=False)
    parent = serializers.PrimaryKeyRelatedField(
        queryset=AssetCategory.objects.all(), allow_null=True, required=False
    )
    description = serializers.CharField(max_length=500, allow_blank=True, required=False)
    is_active = serializers.BooleanField(required=False)
    sort_order = serializers.IntegerField(min_value=0, max_value=10000, required=False)

    def validate_code(self, value):
        if self.instance is not None:
            raise serializers.ValidationError("The code cannot be changed.")
        from .models import CATEGORY_CODE_VALIDATOR

        value = value.strip().lower()
        CATEGORY_CODE_VALIDATOR(value)
        if AssetCategory.objects.filter(code=value).exists():
            raise serializers.ValidationError("This code is already in use.")
        return value

    def validate(self, attrs):
        name = attrs.get("name", getattr(self.instance, "name", "")).strip()
        parent = attrs["parent"] if "parent" in attrs else getattr(self.instance, "parent", None)
        clash = AssetCategory.objects.filter(parent=parent, name__iexact=name)
        if self.instance is not None:
            clash = clash.exclude(pk=self.instance.pk)
        if clash.exists():
            raise serializers.ValidationError(
                {"name": ["A category with this name already exists at this level."]}
            )
        if "name" in attrs:
            attrs["name"] = name
        return attrs


class CustomFieldDefinitionSerializer(serializers.ModelSerializer):
    category = serializers.PrimaryKeyRelatedField(read_only=True)
    choices = serializers.ListField(child=serializers.CharField(), read_only=True)
    min_value = serializers.DecimalField(
        max_digits=20, decimal_places=6, allow_null=True, read_only=True
    )
    max_value = serializers.DecimalField(
        max_digits=20, decimal_places=6, allow_null=True, read_only=True
    )

    class Meta:
        model = CustomFieldDefinition
        fields = [
            "id",
            "category",
            "key",
            "label",
            "field_type",
            "required",
            "choices",
            "help_text",
            "min_value",
            "max_value",
            "max_length",
            "sort_order",
            "is_active",
            "version",
        ]
        read_only_fields = fields


class CustomFieldCreateSerializer(serializers.Serializer):
    key = serializers.RegexField(r"^[a-z][a-z0-9_]{0,49}$", max_length=50)
    label = serializers.CharField(max_length=100)
    field_type = serializers.ChoiceField(choices=CustomFieldDefinition.FieldType.choices)
    required = serializers.BooleanField(default=False)
    choices = serializers.ListField(
        child=serializers.CharField(max_length=100), required=False, default=list, max_length=200
    )
    help_text = serializers.CharField(max_length=300, allow_blank=True, required=False, default="")
    min_value = serializers.DecimalField(
        max_digits=20, decimal_places=6, allow_null=True, required=False
    )
    max_value = serializers.DecimalField(
        max_digits=20, decimal_places=6, allow_null=True, required=False
    )
    max_length = serializers.IntegerField(
        min_value=1, max_value=5000, allow_null=True, required=False
    )
    sort_order = serializers.IntegerField(min_value=0, max_value=10000, required=False, default=0)


class CustomFieldUpdateSerializer(serializers.Serializer):
    """Key and type are immutable so stored values stay valid."""

    label = serializers.CharField(max_length=100, required=False)
    required = serializers.BooleanField(required=False)
    choices = serializers.ListField(
        child=serializers.CharField(max_length=100), required=False, max_length=200
    )
    help_text = serializers.CharField(max_length=300, allow_blank=True, required=False)
    min_value = serializers.DecimalField(
        max_digits=20, decimal_places=6, allow_null=True, required=False
    )
    max_value = serializers.DecimalField(
        max_digits=20, decimal_places=6, allow_null=True, required=False
    )
    max_length = serializers.IntegerField(
        min_value=1, max_value=5000, allow_null=True, required=False
    )
    sort_order = serializers.IntegerField(min_value=0, max_value=10000, required=False)
    is_active = serializers.BooleanField(required=False)


# --- Network --------------------------------------------------------------------


class HostnameInputSerializer(serializers.Serializer):
    hostname = serializers.CharField(max_length=253)
    is_primary = serializers.BooleanField(default=False)

    def validate_hostname(self, value):
        try:
            return network.normalize_hostname(value)
        except ValueError as exc:
            raise serializers.ValidationError(str(exc)) from exc


class InterfaceInputSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=64)
    mac_address = serializers.CharField(max_length=32, allow_blank=True, required=False, default="")

    def validate_name(self, value):
        try:
            return network.validate_interface_name(value)
        except ValueError as exc:
            raise serializers.ValidationError(str(exc)) from exc

    def validate_mac_address(self, value):
        try:
            return network.normalize_mac(value)
        except ValueError as exc:
            raise serializers.ValidationError(str(exc)) from exc


class IPAddressInputSerializer(serializers.Serializer):
    address = serializers.CharField(max_length=64)
    interface_name = serializers.CharField(
        max_length=64, allow_blank=True, required=False, default=""
    )
    is_primary = serializers.BooleanField(default=False)

    def validate_address(self, value):
        try:
            return network.normalize_ip(value)
        except ValueError as exc:
            raise serializers.ValidationError(str(exc)) from exc


class _EvidenceFields(serializers.ModelSerializer):
    class Meta:
        fields = ["id", "source", "source_ref", "observed_at"]


class HostnameSerializer(_EvidenceFields):
    class Meta:
        model = AssetHostname
        fields = ["id", "hostname", "is_primary", "source", "source_ref", "observed_at"]
        read_only_fields = fields


class InterfaceSerializer(_EvidenceFields):
    class Meta:
        model = AssetInterface
        fields = ["id", "name", "mac_address", "source", "source_ref", "observed_at"]
        read_only_fields = fields


class IPAddressSerializer(_EvidenceFields):
    interface_name = serializers.CharField(
        source="interface.name", read_only=True, allow_null=True, default=None
    )

    class Meta:
        model = AssetIPAddress
        fields = [
            "id",
            "address",
            "interface_name",
            "is_primary",
            "source",
            "source_ref",
            "observed_at",
        ]
        read_only_fields = fields


# --- Assets ---------------------------------------------------------------------


class AssetListSerializer(serializers.ModelSerializer):
    category = serializers.SerializerMethodField()
    site = SiteRefSerializer(read_only=True)
    location = RefSerializer(read_only=True, allow_null=True)
    owner = UserRefSerializer(read_only=True, allow_null=True)
    primary_hostname = serializers.CharField(read_only=True, allow_null=True)
    primary_ip = serializers.CharField(read_only=True, allow_null=True)
    is_archived = serializers.BooleanField(read_only=True)
    last_seen_at = serializers.DateTimeField(read_only=True, allow_null=True)
    source_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = Asset
        fields = [
            "id",
            "name",
            "asset_tag",
            "category",
            "manufacturer",
            "model",
            "serial_number",
            "primary_hostname",
            "primary_ip",
            "site",
            "location",
            "owner",
            "business_status",
            "observation_status",
            "support_status",
            "is_archived",
            "last_seen_at",
            "source_count",
            "modified_at",
            "version",
        ]
        read_only_fields = fields

    @extend_schema_field(CategoryRefSerializer)
    def get_category(self, obj):
        return _category_ref(obj, self.context)


class AssetDetailSerializer(AssetListSerializer):
    department = RefSerializer(read_only=True, allow_null=True)
    hostnames = HostnameSerializer(many=True, read_only=True)
    interfaces = InterfaceSerializer(many=True, read_only=True)
    ip_addresses = IPAddressSerializer(many=True, read_only=True)
    custom_fields = serializers.DictField(read_only=True)
    missing_required_fields = serializers.SerializerMethodField()
    retained_custom_fields = serializers.SerializerMethodField()
    archived_by = serializers.SlugRelatedField(
        read_only=True, allow_null=True, slug_field="username"
    )
    created_by = serializers.SlugRelatedField(
        read_only=True, allow_null=True, slug_field="username"
    )
    modified_by = serializers.SlugRelatedField(
        read_only=True, allow_null=True, slug_field="username"
    )

    class Meta(AssetListSerializer.Meta):
        fields = [
            *AssetListSerializer.Meta.fields,
            "os_name",
            "os_version",
            "firmware_version",
            "department",
            "notes",
            "custom_fields",
            "missing_required_fields",
            "retained_custom_fields",
            "hostnames",
            "interfaces",
            "ip_addresses",
            "archived_at",
            "archived_by",
            "archive_reason",
            "created_at",
            "created_by",
            "modified_by",
        ]
        read_only_fields = fields

    def _definitions(self, obj):
        key = ("definitions", obj.category_id)
        if key not in self.context:
            self.context[key] = cf.applicable_definitions(obj.category_id, _tree(self.context))
        return self.context[key]

    def get_missing_required_fields(self, obj) -> list[str]:
        return cf.missing_required(self._definitions(obj), obj.custom_fields)

    def get_retained_custom_fields(self, obj) -> list[str]:
        return cf.retained_keys(self._definitions(obj), obj.custom_fields)


class AssetWriteSerializer(serializers.Serializer):
    """Create (all fields) and PATCH (partial; category excluded — use classification)."""

    name = serializers.CharField(max_length=200)
    asset_tag = serializers.CharField(
        max_length=64, allow_null=True, allow_blank=True, required=False
    )
    category = serializers.PrimaryKeyRelatedField(queryset=AssetCategory.objects.all())
    manufacturer = serializers.CharField(max_length=150, allow_blank=True, required=False)
    model = serializers.CharField(max_length=150, allow_blank=True, required=False)
    serial_number = serializers.CharField(max_length=150, allow_blank=True, required=False)
    os_name = serializers.CharField(max_length=150, allow_blank=True, required=False)
    os_version = serializers.CharField(max_length=100, allow_blank=True, required=False)
    firmware_version = serializers.CharField(max_length=100, allow_blank=True, required=False)
    site = serializers.PrimaryKeyRelatedField(queryset=Site.objects.none())
    location = serializers.PrimaryKeyRelatedField(
        queryset=Location.objects.none(), allow_null=True, required=False
    )
    department = serializers.PrimaryKeyRelatedField(
        queryset=Department.objects.all(), allow_null=True, required=False
    )
    owner = serializers.PrimaryKeyRelatedField(
        queryset=get_user_model().objects.all(), allow_null=True, required=False
    )
    business_status = serializers.ChoiceField(choices=Asset.BusinessStatus.choices, required=False)
    notes = serializers.CharField(max_length=10000, allow_blank=True, required=False)
    custom_fields = serializers.DictField(required=False)
    hostnames = HostnameInputSerializer(many=True, required=False, max_length=50)
    interfaces = InterfaceInputSerializer(many=True, required=False, max_length=100)
    ip_addresses = IPAddressInputSerializer(many=True, required=False, max_length=200)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request = self.context.get("request")
        if request is not None:
            # Out-of-scope and nonexistent sites/locations get the same "invalid"
            # error, so the API never confirms a site the user cannot see. Without a
            # request (schema generation) the querysets stay empty: fail closed.
            user = request.user
            self.fields["site"].queryset = scope.restrict(Site.objects.all(), user, field="pk")
            self.fields["location"].queryset = scope.restrict(
                Location.objects.all(), user, field="site"
            )
        if self.partial:
            self.fields.pop("category")

    def validate_asset_tag(self, value):
        if value is None or not value.strip():
            return None
        value = value.strip().upper()
        import re

        if not re.match(ASSET_TAG_PATTERN, value):
            raise serializers.ValidationError(
                "Use up to 64 letters, digits or . _ / - (stored in uppercase)."
            )
        clash = Asset.objects.filter(asset_tag=value)
        if self.instance is not None:
            clash = clash.exclude(pk=self.instance.pk)
        if clash.exists():
            raise serializers.ValidationError("This asset tag is already in use.")
        return value

    def validate_name(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError("Enter a name.")
        return value


class ClassificationPreviewSerializer(serializers.Serializer):
    category = serializers.PrimaryKeyRelatedField(queryset=AssetCategory.objects.all())
    custom_fields = serializers.DictField(required=False)


class ClassificationSerializer(ClassificationPreviewSerializer):
    reason = serializers.CharField(min_length=5, max_length=500)


class ClassificationImpactSerializer(serializers.Serializer):
    class FieldAdded(serializers.Serializer):
        key = serializers.CharField()
        label = serializers.CharField()
        required = serializers.BooleanField()

    from_category = serializers.CharField()
    to_category = serializers.CharField()
    fields_added = FieldAdded(many=True)
    fields_kept = serializers.ListField(child=serializers.CharField())
    values_retained_read_only = serializers.ListField(child=serializers.CharField())
    required_missing = serializers.ListField(child=serializers.CharField())


class ReasonSerializer(serializers.Serializer):
    reason = serializers.CharField(min_length=5, max_length=500)


class AssetHistorySerializer(serializers.ModelSerializer):
    changes = serializers.DictField(read_only=True)

    class Meta:
        model = AssetHistoryEntry
        fields = [
            "id",
            "occurred_at",
            "actor_label",
            "change_type",
            "changes",
            "reason",
            "version",
            "request_id",
        ]
        read_only_fields = fields
