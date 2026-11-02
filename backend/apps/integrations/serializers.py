from urllib.parse import urlparse

from django.utils import timezone
from rest_framework import serializers

from apps.assets.models import TECHNICAL_FIELDS
from apps.assets.serializers import SiteRefSerializer
from apps.organizations.models import Site

from .models import DiscoverySource, FieldAuthorityPolicy, IntegrationInstance, SyncRun


class DiscoverySourceSerializer(serializers.ModelSerializer):
    instance_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = DiscoverySource
        fields = ["code", "name", "kind", "availability", "description", "instance_count"]
        read_only_fields = fields


class IntegrationInstanceSerializer(serializers.ModelSerializer):
    source = DiscoverySourceSerializer(read_only=True)
    default_site = SiteRefSerializer(read_only=True)
    active_links = serializers.IntegerField(read_only=True)
    stale_links = serializers.IntegerField(read_only=True)
    open_candidates = serializers.IntegerField(read_only=True)
    freshness = serializers.SerializerMethodField()

    class Meta:
        model = IntegrationInstance
        fields = [
            "id",
            "source",
            "name",
            "status",
            "is_enabled",
            "base_url",
            "default_site",
            "default_vrf",
            "stale_after_hours",
            "auto_link_strong_matches",
            "last_attempt_at",
            "last_success_at",
            "last_error",
            "active_links",
            "stale_links",
            "open_candidates",
            "freshness",
            "created_at",
            "modified_at",
            "version",
        ]
        read_only_fields = fields

    def get_freshness(self, obj) -> str:
        """never | fresh | stale, from the last successful run against the threshold."""
        if obj.last_success_at is None:
            return "never"
        age = timezone.now() - obj.last_success_at
        return "stale" if age.total_seconds() > obj.stale_after_hours * 3600 else "fresh"


class IntegrationInstanceWriteSerializer(serializers.Serializer):
    source = serializers.PrimaryKeyRelatedField(queryset=DiscoverySource.objects.all())
    name = serializers.CharField(max_length=100)
    default_site = serializers.PrimaryKeyRelatedField(queryset=Site.objects.filter(is_active=True))
    default_vrf = serializers.CharField(max_length=64, allow_blank=True, required=False)
    base_url = serializers.CharField(max_length=300, allow_blank=True, required=False)
    stale_after_hours = serializers.IntegerField(min_value=1, max_value=720, required=False)
    auto_link_strong_matches = serializers.BooleanField(required=False)
    is_enabled = serializers.BooleanField(required=False)
    # Available/Degraded are set only by real sync results, never by hand.
    status = serializers.ChoiceField(
        choices=[IntegrationInstance.Status.CONFIGURED, IntegrationInstance.Status.DISCONNECTED],
        required=False,
    )

    def validate_name(self, value):
        value = value.strip()
        clash = IntegrationInstance.objects.filter(name__iexact=value)
        if self.instance is not None:
            clash = clash.exclude(pk=self.instance.pk)
        if clash.exists():
            raise serializers.ValidationError("An integration with this name already exists.")
        return value

    def validate_base_url(self, value):
        value = value.strip()
        if not value:
            return value
        parsed = urlparse(value)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            raise serializers.ValidationError("Use an https:// URL without embedded credentials.")
        return value

    def validate_source(self, value):
        if self.instance is not None and value.pk != self.instance.source_id:
            raise serializers.ValidationError("The source type of an integration cannot change.")
        return value


class SyncRunSerializer(serializers.ModelSerializer):
    error_samples = serializers.ListField(child=serializers.DictField(), read_only=True)

    class Meta:
        model = SyncRun
        fields = [
            "id",
            "mode",
            "status",
            "triggered_by",
            "started_at",
            "finished_at",
            "records_received",
            "observations_created",
            "observations_unchanged",
            "links_refreshed",
            "links_marked_stale",
            "candidates_opened",
            "candidates_updated",
            "assets_updated",
            "conflicts_opened",
            "errors",
            "error_samples",
            "error_message",
        ]
        read_only_fields = fields


class FieldAuthorityPolicySerializer(serializers.ModelSerializer):
    precedence = serializers.DictField(child=serializers.ListField(child=serializers.CharField()))
    modified_by = serializers.SlugRelatedField(
        read_only=True, allow_null=True, slug_field="username"
    )

    class Meta:
        model = FieldAuthorityPolicy
        fields = ["precedence", "version", "modified_at", "modified_by"]
        read_only_fields = ["version", "modified_at", "modified_by"]

    def validate_precedence(self, value):
        known = set(DiscoverySource.objects.values_list("code", flat=True))
        errors = {}
        for field, order in value.items():
            if field not in TECHNICAL_FIELDS:
                errors[field] = ["Not a technical field."]
            elif len(set(order)) != len(order) or set(order) - known:
                errors[field] = ["List each known source code at most once."]
        if errors:
            raise serializers.ValidationError(errors)
        return value
