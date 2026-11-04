from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.lifecycle.models import Status
from apps.lifecycle.serializers import LifecycleCandidateSerializer, LifecycleProductRefSerializer

from .models import SoftwareInstallation, SoftwareProduct, SoftwareVersion


class SoftwareProductSerializer(serializers.ModelSerializer):
    version_count = serializers.IntegerField(read_only=True)
    installations = serializers.IntegerField(read_only=True, help_text="In your sites")
    eos_versions = serializers.IntegerField(
        read_only=True, help_text="Versions past end of support or end of security updates"
    )

    class Meta:
        model = SoftwareProduct
        fields = ["id", "publisher", "name", "version_count", "installations", "eos_versions"]
        read_only_fields = fields


class SoftwareVersionSerializer(serializers.ModelSerializer):
    installations = serializers.IntegerField(
        source="install_count", read_only=True, help_text="In your sites"
    )
    lifecycle_product = LifecycleProductRefSerializer(read_only=True, allow_null=True)
    lifecycle_candidates = LifecycleCandidateSerializer(many=True, read_only=True)
    lifecycle_reasons = serializers.ListField(child=serializers.CharField(), read_only=True)
    lifecycle_status = serializers.ChoiceField(choices=Status.choices, read_only=True)
    lifecycle_reviewed_by = serializers.SlugRelatedField(
        read_only=True, allow_null=True, slug_field="username"
    )

    class Meta:
        model = SoftwareVersion
        fields = [
            "id",
            "version",
            "installations",
            "lifecycle_state",
            "lifecycle_method",
            "lifecycle_product",
            "lifecycle_candidates",
            "lifecycle_status",
            "lifecycle_milestone_type",
            "lifecycle_milestone_date",
            "lifecycle_days_remaining",
            "lifecycle_evidence_quality",
            "lifecycle_reasons",
            "lifecycle_reviewed_by",
            "lifecycle_reviewed_at",
            "lifecycle_assessed_at",
            "lifecycle_version",
        ]
        read_only_fields = fields


class SoftwareProductDetailSerializer(SoftwareProductSerializer):
    versions = SoftwareVersionSerializer(many=True, read_only=True)

    class Meta(SoftwareProductSerializer.Meta):
        fields = [*SoftwareProductSerializer.Meta.fields, "versions"]
        read_only_fields = fields


class InstallAssetSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField()
    site_code = serializers.CharField()


class SoftwareInstallationSerializer(serializers.ModelSerializer):
    product_id = serializers.IntegerField(source="version.product_id", read_only=True)
    publisher = serializers.CharField(source="version.product.publisher", read_only=True)
    name = serializers.CharField(source="version.product.name", read_only=True)
    version = serializers.CharField(source="version.version", read_only=True)
    version_id = serializers.IntegerField(read_only=True)
    lifecycle_status = serializers.ChoiceField(
        source="version.lifecycle_status", choices=Status.choices, read_only=True
    )
    source = serializers.SerializerMethodField()
    asset = serializers.SerializerMethodField()
    created_by = serializers.SlugRelatedField(
        read_only=True, allow_null=True, slug_field="username"
    )

    class Meta:
        model = SoftwareInstallation
        fields = [
            "id",
            "product_id",
            "publisher",
            "name",
            "version",
            "version_id",
            "lifecycle_status",
            "raw_publisher",
            "raw_name",
            "raw_version",
            "source",
            "external_id",
            "asset",
            "installed_on",
            "first_seen_at",
            "last_seen_at",
            "removed_at",
            "removed_reason",
            "created_by",
            "note",
        ]
        read_only_fields = fields

    def get_source(self, obj) -> str:
        return obj.instance.name if obj.instance_id else "Manual"

    @extend_schema_field(InstallAssetSerializer(allow_null=True))
    def get_asset(self, obj) -> dict | None:
        assets = self.context.get("assets") or {}
        asset_id = getattr(obj, "resolved_asset_id", None) or obj.asset_id
        return assets.get(asset_id)


class ManualSoftwareSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=300)
    publisher = serializers.CharField(max_length=200, required=False, allow_blank=True, default="")
    version = serializers.CharField(max_length=100, required=False, allow_blank=True, default="")
    installed_on = serializers.DateField(required=False, allow_null=True, default=None)
    note = serializers.CharField(max_length=500, required=False, allow_blank=True, default="")


class VersionApproveSerializer(serializers.Serializer):
    product = serializers.UUIDField()
    remember_alias = serializers.BooleanField(default=False)
    note = serializers.CharField(max_length=500, required=False, allow_blank=True, default="")


class VersionRejectSerializer(serializers.Serializer):
    note = serializers.CharField(min_length=5, max_length=500)
