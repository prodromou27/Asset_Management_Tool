from django.db.models import Q
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema, extend_schema_field
from rest_framework import serializers
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts import catalog
from apps.accounts.permissions import HasPermission
from apps.assets.selectors import visible_assets
from apps.assets.serializers import RefSerializer

from .models import NeighborEvidence

MAX_ROWS = 500


class NeighborEvidenceSerializer(serializers.ModelSerializer):
    instance = serializers.CharField(source="instance.name", read_only=True)
    direction = serializers.SerializerMethodField()
    local_asset = serializers.SerializerMethodField()
    remote_asset = serializers.SerializerMethodField()
    is_physical_link_confirmed = serializers.SerializerMethodField()

    class Meta:
        model = NeighborEvidence
        fields = [
            "id",
            "instance",
            "kind",
            "direction",
            "local_external_id",
            "local_port",
            "local_asset",
            "remote_mac",
            "remote_external_id",
            "remote_hostname",
            "remote_port",
            "remote_platform",
            "remote_asset",
            "vlan",
            "is_active",
            "first_seen_at",
            "last_seen_at",
            "is_physical_link_confirmed",
        ]
        read_only_fields = fields

    def _asset_ref(self, instance_id, external_id):
        ref = self.context["asset_by_link"].get((instance_id, external_id))
        return {"id": ref[0], "name": ref[1]} if ref else None

    def get_direction(self, obj) -> str:
        """local: seen on this asset's ports. remote: this asset seen on another device."""
        return (
            "local"
            if (obj.instance_id, obj.local_external_id) in self.context["own_links"]
            else "remote"
        )

    @extend_schema_field(RefSerializer(allow_null=True))
    def get_local_asset(self, obj):
        return self._asset_ref(obj.instance_id, obj.local_external_id)

    @extend_schema_field(RefSerializer(allow_null=True))
    def get_remote_asset(self, obj):
        return (
            self._asset_ref(obj.instance_id, obj.remote_external_id)
            if obj.remote_external_id
            else None
        )

    def get_is_physical_link_confirmed(self, obj) -> bool:
        return False  # Evidence only; never a confirmed cable (docs/15 A24).


class AssetNetworkEvidenceView(APIView):
    permission_classes = [HasPermission(catalog.DISCOVERY_VIEW)]

    @extend_schema(responses=NeighborEvidenceSerializer(many=True))
    def get(self, request, pk):
        from apps.reconciliation.models import SourceLink

        visible = visible_assets(request.user)
        asset = get_object_or_404(visible, pk=pk)
        own = set(
            SourceLink.objects.filter(asset=asset)
            .exclude(status=SourceLink.Status.UNLINKED)
            .values_list("instance_id", "external_id")
        )
        macs = [m for m in asset.interfaces.values_list("mac_address", flat=True) if m]
        condition = Q(pk__in=[])
        for instance_id, external_id in own:
            condition |= Q(instance_id=instance_id, local_external_id=external_id)
            condition |= Q(instance_id=instance_id, remote_external_id=external_id)
        if macs:
            condition |= Q(kind=NeighborEvidence.Kind.FDB, remote_mac__in=macs)
        rows = list(
            NeighborEvidence.objects.filter(condition)
            .select_related("instance")
            .order_by("-is_active", "local_external_id", "local_port")[:MAX_ROWS]
        )
        # Map referenced devices to assets the user may see; others stay unnamed.
        keys = {(r.instance_id, r.local_external_id) for r in rows} | {
            (r.instance_id, r.remote_external_id) for r in rows if r.remote_external_id
        }
        link_q = Q(pk__in=[])
        for instance_id, external_id in keys:
            link_q |= Q(instance_id=instance_id, external_id=external_id)
        asset_by_link = {
            (link.instance_id, link.external_id): (link.asset_id, link.asset.name)
            for link in SourceLink.objects.filter(
                link_q, asset__in=visible.values("pk")
            ).select_related("asset")
        }
        context = {"own_links": own, "asset_by_link": asset_by_link}
        return Response(NeighborEvidenceSerializer(rows, many=True, context=context).data)
