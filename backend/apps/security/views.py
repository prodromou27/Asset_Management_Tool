from datetime import timedelta

from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts import catalog
from apps.accounts.permissions import HasPermission
from apps.assets.selectors import visible_assets

from .models import EndpointSecurityState


class SecuritySourceRefSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField()
    source = serializers.CharField(source="source_id")


class EndpointSecurityStateSerializer(serializers.ModelSerializer):
    instance = SecuritySourceRefSerializer(read_only=True)
    link_status = serializers.SerializerMethodField()
    source_last_success_at = serializers.DateTimeField(
        source="instance.last_success_at", allow_null=True, read_only=True
    )
    freshness = serializers.SerializerMethodField()
    device_tags = serializers.ListField(child=serializers.CharField(), read_only=True)
    original = serializers.DictField(read_only=True)
    observation_id = serializers.UUIDField(allow_null=True, read_only=True)

    class Meta:
        model = EndpointSecurityState
        fields = [
            "id",
            "instance",
            "external_id",
            "link_status",
            "tenant_id",
            "entra_device_id",
            "computer_dns_name",
            "os_platform",
            "os_version",
            "onboarding_status",
            "health_status",
            "exposure_level",
            "risk_score",
            "device_tags",
            "machine_group",
            "first_seen_at",
            "last_seen_at",
            "last_synced_at",
            "source_last_success_at",
            "missing_since",
            "changed_at",
            "freshness",
            "observation_id",
            "original",
        ]
        read_only_fields = fields

    def get_link_status(self, obj) -> str:
        return self.context["links"][(obj.instance_id, obj.external_id)]

    def get_freshness(self, obj) -> str:
        """fresh | stale. Stale when the source has not synchronised successfully within
        its threshold, the machine was missing from the last complete listing, the link is
        stale, or the device has not reported to the source within the threshold."""
        threshold = timedelta(hours=obj.instance.stale_after_hours)
        now = timezone.now()
        source_ok = obj.instance.last_success_at and now - obj.instance.last_success_at <= threshold
        reported = obj.last_seen_at and now - obj.last_seen_at <= threshold
        if (
            not source_ok
            or not reported
            or obj.missing_since
            or self.get_link_status(obj) != "active"
        ):
            return "stale"
        return "fresh"


class AssetSecurityView(APIView):
    """Security observations of an asset's linked sources (Defender for Endpoint).
    Requires discovery.view and site access to the asset."""

    permission_classes = [HasPermission(catalog.DISCOVERY_VIEW)]

    @extend_schema(responses=EndpointSecurityStateSerializer(many=True))
    def get(self, request, pk):
        from apps.reconciliation.models import SourceLink

        asset = get_object_or_404(visible_assets(request.user), pk=pk)
        links = {
            (instance_id, external_id): status
            for instance_id, external_id, status in SourceLink.objects.filter(asset=asset)
            .exclude(status=SourceLink.Status.UNLINKED)
            .values_list("instance_id", "external_id", "status")
        }
        rows = [
            state
            for state in EndpointSecurityState.objects.filter(
                instance_id__in={key[0] for key in links},
                external_id__in={key[1] for key in links},
            ).select_related("instance")
            if (state.instance_id, state.external_id) in links
        ]
        rows.sort(key=lambda s: (s.instance.name, s.external_id))
        return Response(
            EndpointSecurityStateSerializer(rows, many=True, context={"links": links}).data
        )
