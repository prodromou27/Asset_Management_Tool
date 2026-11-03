from django.db import transaction
from django.db.models import Count, F, Q
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts import catalog
from apps.accounts.permissions import HasPermission, ReadAnyWritePermission
from apps.audit import services as audit
from apps.organizations.services import check_version
from config.api import ApiError, ItemsCursorPagination

from . import sync
from .models import DiscoverySource, FieldAuthorityPolicy, IntegrationInstance, SyncRun
from .serializers import (
    ConnectionTestSerializer,
    DiscoverySourceSerializer,
    FieldAuthorityPolicySerializer,
    IntegrationInstanceSerializer,
    IntegrationInstanceWriteSerializer,
    LiveAccessSerializer,
    SyncRequestSerializer,
    SyncRunSerializer,
)

IntegrationPermission = ReadAnyWritePermission(
    (catalog.DISCOVERY_VIEW, catalog.INTEGRATIONS_MANAGE), catalog.INTEGRATIONS_MANAGE
)
IF_MATCH = OpenApiParameter("If-Match", str, OpenApiParameter.HEADER, required=True)
SNAPSHOT_FIELDS = (
    "name",
    "status",
    "is_enabled",
    "base_url",
    "credential_ref",
    "auth_scheme",
    "ca_bundle_ref",
    "tenant_id",
    "client_id",
    "timeout_seconds",
    "max_retries",
    "requests_per_second",
    "sync_interval_minutes",
    "evidence_interval_hours",
    "enrichment_max_age_hours",
    "source_timezone",
    "default_vrf",
    "stale_after_hours",
    "auto_link_strong_matches",
)


def _if_match(request):
    raw = request.headers.get("If-Match")
    if raw is None:
        return None
    try:
        return int(raw.strip('"W/ '))
    except ValueError:
        return -1


def _instances():
    return IntegrationInstance.objects.select_related("source", "default_site").annotate(
        active_links=Count("links", filter=Q(links__status="active"), distinct=True),
        stale_links=Count("links", filter=Q(links__status="stale"), distinct=True),
        open_candidates=Count(
            "candidates", filter=Q(candidates__status__in=["open", "held"]), distinct=True
        ),
    )


def _snapshot(instance) -> dict:
    data = {field: getattr(instance, field) for field in SNAPSHOT_FIELDS}
    data["default_site"] = instance.default_site.code
    return data


class DiscoverySourceListView(APIView):
    permission_classes = [IntegrationPermission]

    @extend_schema(responses=DiscoverySourceSerializer(many=True))
    def get(self, request):
        sources = DiscoverySource.objects.annotate(instance_count=Count("instances"))
        return Response(DiscoverySourceSerializer(sources, many=True).data)


class IntegrationListCreateView(APIView):
    permission_classes = [IntegrationPermission]

    @extend_schema(responses=IntegrationInstanceSerializer(many=True))
    def get(self, request):
        return Response(IntegrationInstanceSerializer(_instances(), many=True).data)

    @extend_schema(
        request=IntegrationInstanceWriteSerializer, responses={201: IntegrationInstanceSerializer}
    )
    def post(self, request):
        data = IntegrationInstanceWriteSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        with transaction.atomic():
            instance = IntegrationInstance.objects.create(**data.validated_data)
            audit.record(
                action="integrations.create",
                actor=request.user,
                request=request,
                object_type="integration",
                object_id=instance.pk,
                object_label=instance.name,
                after=_snapshot(instance),
            )
        return Response(
            IntegrationInstanceSerializer(_instances().get(pk=instance.pk)).data, status=201
        )


class IntegrationDetailView(APIView):
    permission_classes = [IntegrationPermission]

    @extend_schema(responses=IntegrationInstanceSerializer)
    def get(self, request, pk):
        instance = get_object_or_404(_instances(), pk=pk)
        return Response(
            IntegrationInstanceSerializer(instance).data, headers={"ETag": f'"{instance.version}"'}
        )

    @extend_schema(
        request=IntegrationInstanceWriteSerializer(partial=True),
        responses=IntegrationInstanceSerializer,
        parameters=[IF_MATCH],
    )
    def patch(self, request, pk):
        instance = get_object_or_404(IntegrationInstance, pk=pk)
        data = IntegrationInstanceWriteSerializer(instance, data=request.data, partial=True)
        data.is_valid(raise_exception=True)
        with transaction.atomic():
            instance = IntegrationInstance.objects.select_for_update().get(pk=pk)
            check_version(instance, _if_match(request))
            before = _snapshot(instance)
            for key, value in data.validated_data.items():
                setattr(instance, key, value)
            after = _snapshot(instance)
            if after != before:
                instance.version = F("version") + 1
                instance.save()
                audit.record(
                    action="integrations.update",
                    actor=request.user,
                    request=request,
                    object_type="integration",
                    object_id=instance.pk,
                    object_label=instance.name,
                    before=before,
                    after=after,
                )
        instance = _instances().get(pk=pk)
        return Response(
            IntegrationInstanceSerializer(instance).data, headers={"ETag": f'"{instance.version}"'}
        )


class RunPagination(ItemsCursorPagination):
    ordering = ("-started_at", "-id")


class SyncRunListView(generics.ListAPIView):
    serializer_class = SyncRunSerializer
    pagination_class = RunPagination
    permission_classes = [IntegrationPermission]

    def get_queryset(self):
        instance = get_object_or_404(IntegrationInstance, pk=self.kwargs["pk"])
        return SyncRun.objects.filter(instance=instance)


class FieldAuthorityView(APIView):
    permission_classes = [IntegrationPermission]

    @extend_schema(responses=FieldAuthorityPolicySerializer)
    def get(self, request):
        policy = FieldAuthorityPolicy.load()
        return Response(
            FieldAuthorityPolicySerializer(policy).data, headers={"ETag": f'"{policy.version}"'}
        )

    @extend_schema(
        request=FieldAuthorityPolicySerializer,
        responses=FieldAuthorityPolicySerializer,
        parameters=[IF_MATCH],
    )
    def patch(self, request):
        data = FieldAuthorityPolicySerializer(data=request.data, partial=True)
        data.is_valid(raise_exception=True)
        with transaction.atomic():
            policy = FieldAuthorityPolicy.objects.select_for_update().get(
                pk=FieldAuthorityPolicy.load().pk
            )
            check_version(policy, _if_match(request))
            before = dict(policy.precedence)
            policy.precedence = {**policy.precedence, **data.validated_data.get("precedence", {})}
            if policy.precedence != before:
                policy.version = F("version") + 1
                policy.modified_by = request.user
                policy.save()
                policy.refresh_from_db()
                audit.record(
                    action="integrations.field_authority",
                    actor=request.user,
                    request=request,
                    object_type="settings",
                    object_id="field_authority",
                    object_label="Field authority",
                    before=before,
                    after=policy.precedence,
                )
        return Response(
            FieldAuthorityPolicySerializer(policy).data,
            headers={"ETag": f'"{policy.version}"'},
            status=status.HTTP_200_OK,
        )


# --- Connector actions -------------------------------------------------------------------


def _refused(exc: sync.SyncRefused) -> ApiError:
    http = (
        status.HTTP_409_CONFLICT
        if exc.code == "SYNC_IN_PROGRESS"
        else status.HTTP_422_UNPROCESSABLE_ENTITY
    )
    return ApiError(exc.code, str(exc), http)


class TestConnectionView(APIView):
    """One read-only GET round-trip (system info, route listing, one device). Live
    access gates apply; the token is never returned or logged."""

    permission_classes = [HasPermission(catalog.INTEGRATIONS_MANAGE)]

    @extend_schema(request=None, responses=ConnectionTestSerializer)
    def post(self, request, pk):
        instance = get_object_or_404(IntegrationInstance, pk=pk)
        return Response(ConnectionTestSerializer(sync.test_connection(request, instance)).data)


class SyncNowView(APIView):
    permission_classes = [HasPermission(catalog.INTEGRATIONS_MANAGE)]

    @extend_schema(request=SyncRequestSerializer, responses={202: SyncRunSerializer})
    def post(self, request, pk):
        instance = get_object_or_404(IntegrationInstance, pk=pk)
        data = SyncRequestSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        try:
            run = sync.queue_sync(
                instance,
                mode=data.validated_data["mode"],
                triggered_by=f"user:{request.user.username}",
            )
        except sync.SyncRefused as exc:
            raise _refused(exc) from exc
        audit.record(
            action="integrations.sync_requested",
            actor=request.user,
            request=request,
            object_type="integration",
            object_id=instance.pk,
            object_label=instance.name,
            after={"run": str(run.pk), "mode": run.mode},
        )
        run.refresh_from_db()
        return Response(SyncRunSerializer(run).data, status=status.HTTP_202_ACCEPTED)


class LiveAccessView(APIView):
    """Record (or revoke) the administrator approval required before any live call."""

    permission_classes = [HasPermission(catalog.INTEGRATIONS_MANAGE)]

    @extend_schema(request=LiveAccessSerializer, responses=IntegrationInstanceSerializer)
    def post(self, request, pk):
        instance = get_object_or_404(IntegrationInstance, pk=pk)
        data = LiveAccessSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        if data.validated_data["approved"] and not sync.has_adapter(instance):
            raise ApiError(
                "NO_ADAPTER", "This source has no adapter.", status.HTTP_422_UNPROCESSABLE_ENTITY
            )
        sync.set_live_access(
            request, instance, data.validated_data["approved"], data.validated_data["reason"]
        )
        return Response(IntegrationInstanceSerializer(_instances().get(pk=pk)).data)
