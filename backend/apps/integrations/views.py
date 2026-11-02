from django.db import transaction
from django.db.models import Count, F, Q
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts import catalog
from apps.accounts.permissions import ReadAnyWritePermission
from apps.audit import services as audit
from apps.organizations.services import check_version
from config.api import ItemsCursorPagination

from .models import DiscoverySource, FieldAuthorityPolicy, IntegrationInstance, SyncRun
from .serializers import (
    DiscoverySourceSerializer,
    FieldAuthorityPolicySerializer,
    IntegrationInstanceSerializer,
    IntegrationInstanceWriteSerializer,
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
