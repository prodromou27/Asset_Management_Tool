"""License inventory API (docs/04: /licenses/subscriptions, /licenses/allocations).

Tenant-wide data (not site-scoped), readable with ``licenses.view``. Quantities are
reported as the tenant states them, next to ITAM's own distinct assigned-user count, and
labelled as inventory: not a billing agreement and not license compliance (docs/06).
"""

import uuid
from datetime import timedelta

from django.db.models import Prefetch, Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_field
from rest_framework import generics, serializers
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts import catalog
from apps.accounts.permissions import HasPermission
from config.api import ItemsCursorPagination

from .models import DirectoryGroup, LicenseAllocation, LicenseSku, SubscriptionSnapshot

LicensePermission = HasPermission(catalog.LICENSES_VIEW)
MAX_SNAPSHOTS = 100
NEWEST_FIRST = Prefetch("snapshots", queryset=SubscriptionSnapshot.objects.order_by("-taken_at"))


class LicenseSourceSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField()
    last_success_at = serializers.DateTimeField(allow_null=True)
    stale_after_hours = serializers.IntegerField()


class SnapshotSerializer(serializers.ModelSerializer):
    available_units = serializers.SerializerMethodField()

    class Meta:
        model = SubscriptionSnapshot
        fields = [
            "id",
            "taken_at",
            "last_confirmed_at",
            "capability_status",
            "enabled_units",
            "warning_units",
            "suspended_units",
            "locked_out_units",
            "consumed_units",
            "available_units",
            "assigned_users",
            "direct_users",
            "group_users",
        ]
        read_only_fields = fields

    def get_available_units(self, obj) -> int | None:
        """Enabled (purchased, active) minus consumed units, as the tenant reports them."""
        if obj.enabled_units is None or obj.consumed_units is None:
            return None
        return obj.enabled_units - obj.consumed_units


class SubscriptionSerializer(serializers.ModelSerializer):
    instance = LicenseSourceSerializer(read_only=True)
    latest = serializers.SerializerMethodField()
    freshness = serializers.SerializerMethodField()

    class Meta:
        model = LicenseSku
        fields = [
            "id",
            "instance",
            "tenant_id",
            "sku_id",
            "sku_part_number",
            "applies_to",
            "capability_status",
            "subscribed",
            "first_seen_at",
            "last_seen_at",
            "missing_since",
            "freshness",
            "latest",
        ]
        read_only_fields = fields

    @extend_schema_field(SnapshotSerializer(allow_null=True))
    def get_latest(self, obj):
        # Uses the prefetched, newest-first snapshots (one query for the whole list).
        snapshots = list(obj.snapshots.all())
        return SnapshotSerializer(snapshots[0]).data if snapshots else None

    def get_freshness(self, obj) -> str:
        """fresh | stale: stale when the integration has not succeeded within its
        threshold or the SKU was missing from the last complete listing."""
        last = obj.instance.last_success_at
        threshold = timedelta(hours=obj.instance.stale_after_hours)
        if obj.missing_since or last is None or timezone.now() - last > threshold:
            return "stale"
        return "fresh"


class SubscriptionDetailSerializer(SubscriptionSerializer):
    service_plans = serializers.ListField(child=serializers.CharField(), read_only=True)
    snapshots = serializers.SerializerMethodField()

    class Meta(SubscriptionSerializer.Meta):
        fields = [*SubscriptionSerializer.Meta.fields, "service_plans", "snapshots"]
        read_only_fields = fields

    @extend_schema_field(SnapshotSerializer(many=True))
    def get_snapshots(self, obj):
        rows = obj.snapshots.order_by("-taken_at")[:MAX_SNAPSHOTS]
        return SnapshotSerializer(rows, many=True).data


class DirectoryUserRefSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    object_id = serializers.CharField()
    user_principal_name = serializers.CharField()
    display_name = serializers.CharField()
    account_enabled = serializers.BooleanField(allow_null=True)


class SkuRefSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    sku_id = serializers.CharField()
    sku_part_number = serializers.CharField()


class GroupRefSerializer(serializers.Serializer):
    id = serializers.CharField()
    display_name = serializers.CharField(allow_null=True)


class AllocationSerializer(serializers.ModelSerializer):
    user = DirectoryUserRefSerializer(read_only=True)
    sku = SkuRefSerializer(read_only=True)
    method = serializers.ChoiceField(
        choices=["direct", "group", "direct_and_group"], read_only=True
    )
    group_ids = serializers.ListField(child=serializers.CharField(), read_only=True)
    groups = serializers.SerializerMethodField()
    paths = serializers.ListField(child=serializers.DictField(), read_only=True)

    class Meta:
        model = LicenseAllocation
        fields = [
            "id",
            "sku",
            "user",
            "method",
            "assigned_directly",
            "group_ids",
            "groups",
            "state",
            "paths",
            "first_seen_at",
            "last_seen_at",
            "changed_at",
            "ended_at",
        ]
        read_only_fields = fields

    @extend_schema_field(GroupRefSerializer(many=True))
    def get_groups(self, obj):
        """Assigning groups with display names when known (optional permission)."""
        names = self.context.get("group_names", {})
        return [
            {"id": gid, "display_name": names.get((obj.instance_id, gid))} for gid in obj.group_ids
        ]


class SubscriptionListView(APIView):
    permission_classes = [LicensePermission]

    @extend_schema(responses=SubscriptionSerializer(many=True))
    def get(self, request):
        rows = (
            LicenseSku.objects.select_related("instance")
            .prefetch_related(NEWEST_FIRST)
            .order_by("instance__name", "sku_part_number", "sku_id")
        )
        return Response(SubscriptionSerializer(rows, many=True).data)


class SubscriptionDetailView(APIView):
    permission_classes = [LicensePermission]

    @extend_schema(responses=SubscriptionDetailSerializer)
    def get(self, request, pk):
        sku = get_object_or_404(
            LicenseSku.objects.select_related("instance").prefetch_related(NEWEST_FIRST), pk=pk
        )
        return Response(SubscriptionDetailSerializer(sku).data)


class AllocationPagination(ItemsCursorPagination):
    ordering = ("-first_seen_at", "-id")


class AllocationListView(generics.ListAPIView):
    serializer_class = AllocationSerializer
    pagination_class = AllocationPagination
    permission_classes = [LicensePermission]

    @extend_schema(
        parameters=[
            OpenApiParameter("sku", str, description="License SKU (row) ID"),
            OpenApiParameter("q", str, description="User principal name or display name"),
            OpenApiParameter("method", str, enum=["direct", "group", "direct_and_group"]),
            OpenApiParameter("include_ended", bool, description="Include ended allocations"),
        ]
    )
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["group_names"] = {
            (instance_id, object_id): name
            for instance_id, object_id, name in DirectoryGroup.objects.values_list(
                "instance_id", "object_id", "display_name"
            )
        }
        return context

    def get_queryset(self):
        params = self.request.query_params
        rows = LicenseAllocation.objects.select_related("sku", "user")
        if params.get("include_ended") not in ("true", "1"):
            rows = rows.filter(ended_at__isnull=True)
        if sku := params.get("sku"):
            try:
                rows = rows.filter(sku_id=uuid.UUID(sku))
            except ValueError:
                return rows.none()
        if q := params.get("q", "").strip():
            rows = rows.filter(
                Q(user__user_principal_name__icontains=q) | Q(user__display_name__icontains=q)
            )
        method = params.get("method")
        if method == "direct":
            rows = rows.filter(assigned_directly=True, group_ids=[])
        elif method == "group":
            rows = rows.filter(assigned_directly=False)
        elif method == "direct_and_group":
            rows = rows.filter(assigned_directly=True).exclude(group_ids=[])
        return rows
