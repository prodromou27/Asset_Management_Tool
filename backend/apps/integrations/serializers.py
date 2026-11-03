from datetime import timedelta
from urllib.parse import urlparse
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.conf import settings
from django.utils import timezone
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.assets.models import TECHNICAL_FIELDS
from apps.assets.serializers import SiteRefSerializer
from apps.organizations.models import Site

from . import secrets, sync
from .models import DiscoverySource, FieldAuthorityPolicy, IntegrationInstance, SyncRun


class DiscoverySourceSerializer(serializers.ModelSerializer):
    instance_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = DiscoverySource
        fields = ["code", "name", "kind", "availability", "description", "instance_count"]
        read_only_fields = fields


class SyncRunSummarySerializer(serializers.ModelSerializer):
    class Meta:
        model = SyncRun
        fields = [
            "id",
            "mode",
            "status",
            "phase",
            "started_at",
            "finished_at",
            "records_received",
            "devices_total",
            "devices_processed",
            "links_refreshed",
            "candidates_opened",
            "errors",
            "warnings",
            "error_message",
        ]
        read_only_fields = fields


class IntegrationInstanceSerializer(serializers.ModelSerializer):
    source = DiscoverySourceSerializer(read_only=True)
    default_site = SiteRefSerializer(read_only=True)
    active_links = serializers.IntegerField(read_only=True)
    stale_links = serializers.IntegerField(read_only=True)
    open_candidates = serializers.IntegerField(read_only=True)
    freshness = serializers.SerializerMethodField()
    credential_status = serializers.SerializerMethodField()
    has_adapter = serializers.SerializerMethodField()
    live_integrations_enabled = serializers.SerializerMethodField()
    live_access_approved_by = serializers.SlugRelatedField(
        read_only=True, allow_null=True, slug_field="username"
    )
    capabilities = serializers.DictField(child=serializers.BooleanField(), read_only=True)
    next_sync_at = serializers.SerializerMethodField()
    last_run = serializers.SerializerMethodField()

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
            "credential_ref",
            "credential_status",
            "auth_scheme",
            "ca_bundle_ref",
            "timeout_seconds",
            "max_retries",
            "requests_per_second",
            "sync_interval_minutes",
            "evidence_interval_hours",
            "enrichment_max_age_hours",
            "source_timezone",
            "last_evidence_at",
            "has_adapter",
            "live_integrations_enabled",
            "live_access_approved",
            "live_access_approved_by",
            "live_access_approved_at",
            "live_access_reason",
            "last_test_at",
            "last_test_ok",
            "last_test_message",
            "source_software_version",
            "capabilities",
            "consecutive_failures",
            "next_sync_at",
            "last_run",
            "created_at",
            "modified_at",
            "version",
        ]
        read_only_fields = fields

    def get_credential_status(self, obj) -> str:
        """not_set | invalid | missing | configured. The secret itself is never returned."""
        return secrets.status(obj.credential_ref)

    def get_has_adapter(self, obj) -> bool:
        return sync.has_adapter(obj)

    def get_live_integrations_enabled(self, obj) -> bool:
        return bool(getattr(settings, "ITAM_ALLOW_LIVE_INTEGRATIONS", False))

    def get_next_sync_at(self, obj) -> str | None:
        if not (sync.has_adapter(obj) and obj.is_enabled and obj.live_access_approved):
            return None
        if obj.last_attempt_at is None:
            return timezone.now().isoformat()
        return (obj.last_attempt_at + timedelta(minutes=obj.sync_interval_minutes)).isoformat()

    @extend_schema_field(SyncRunSummarySerializer(allow_null=True))
    def get_last_run(self, obj):
        run = obj.runs.order_by("-started_at").first()
        return SyncRunSummarySerializer(run).data if run else None

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
    credential_ref = serializers.CharField(max_length=200, allow_blank=True, required=False)
    auth_scheme = serializers.ChoiceField(
        choices=IntegrationInstance.AuthScheme.choices, required=False
    )
    ca_bundle_ref = serializers.CharField(max_length=200, allow_blank=True, required=False)
    timeout_seconds = serializers.IntegerField(min_value=5, max_value=120, required=False)
    max_retries = serializers.IntegerField(min_value=0, max_value=6, required=False)
    requests_per_second = serializers.IntegerField(min_value=1, max_value=20, required=False)
    sync_interval_minutes = serializers.IntegerField(min_value=15, max_value=10080, required=False)
    evidence_interval_hours = serializers.IntegerField(min_value=1, max_value=168, required=False)
    enrichment_max_age_hours = serializers.IntegerField(min_value=1, max_value=720, required=False)
    source_timezone = serializers.CharField(max_length=64, required=False)

    def validate_credential_ref(self, value):
        try:
            return secrets.validate_ref(value)
        except secrets.SecretError as exc:
            raise serializers.ValidationError(str(exc)) from exc

    def validate_ca_bundle_ref(self, value):
        value = value.strip()
        if value and not value.startswith("file:"):
            raise serializers.ValidationError("A CA bundle must be a file: reference.")
        return self.validate_credential_ref(value)

    def validate_source_timezone(self, value):
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise serializers.ValidationError(
                "Use an IANA time zone such as UTC or Europe/Nicosia."
            ) from exc
        return value

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
    warning_samples = serializers.ListField(child=serializers.DictField(), read_only=True)

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
            "warnings",
            "warning_samples",
            "error_message",
            "phase",
            "devices_total",
            "devices_processed",
            "devices_enriched",
            "evidence_rows",
            "api_requests",
            "heartbeat_at",
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


class SyncRequestSerializer(serializers.Serializer):
    mode = serializers.ChoiceField(choices=SyncRun.Mode.choices, default=SyncRun.Mode.FULL)


class LiveAccessSerializer(serializers.Serializer):
    approved = serializers.BooleanField()
    reason = serializers.CharField(min_length=5, max_length=500)


class ConnectionTestSerializer(serializers.Serializer):
    ok = serializers.BooleanField()
    message = serializers.CharField()
    version = serializers.CharField(allow_blank=True)
    capabilities = serializers.DictField(child=serializers.BooleanField())
