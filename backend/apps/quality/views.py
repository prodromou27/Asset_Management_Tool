"""Data-quality queues API (Task 011).

Findings are visible for assets the user can see (site scope) with ``discovery.view``;
assigning, dismissing, reopening and refreshing need ``reconciliation.decide``.
"""

from uuid import UUID

from django.db.models import Count
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import generics, serializers
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts import catalog
from apps.accounts.permissions import HasPermission
from apps.assets.selectors import visible_assets
from apps.assets.serializers import ReasonSerializer, SiteRefSerializer, UserRefSerializer
from apps.reconciliation.triage import validate_assignee
from config.api import ItemsCursorPagination

from . import services
from .models import DataQualityFinding as Finding

IF_MATCH = OpenApiParameter("If-Match", str, OpenApiParameter.HEADER, required=True)


def _if_match(request):
    raw = request.headers.get("If-Match")
    if raw is None:
        return None
    try:
        return int(raw.strip('"W/ '))
    except ValueError:
        return -1


def _is_uuid(value) -> bool:
    try:
        UUID(str(value))
    except ValueError:
        return False
    return True


def visible_findings(user):
    return Finding.objects.select_related("asset__site", "assignee", "resolved_by").filter(
        asset__in=visible_assets(user).values("pk")
    )


class FindingAssetSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField()
    site = SiteRefSerializer()


class FindingSerializer(serializers.ModelSerializer):
    asset = FindingAssetSerializer(read_only=True)
    assignee = UserRefSerializer(read_only=True, allow_null=True)
    resolved_by = serializers.SlugRelatedField(
        read_only=True, allow_null=True, slug_field="username"
    )
    evidence = serializers.DictField(read_only=True)

    class Meta:
        model = Finding
        fields = [
            "id",
            "kind",
            "asset",
            "severity",
            "summary",
            "evidence",
            "status",
            "assignee",
            "assigned_at",
            "detected_at",
            "last_confirmed_at",
            "resolved_at",
            "resolved_by",
            "resolution_reason",
            "version",
        ]
        read_only_fields = fields


class FindingPagination(ItemsCursorPagination):
    ordering = ("-detected_at", "-id")


@extend_schema(
    parameters=[
        OpenApiParameter("kind", str, enum=list(Finding.Kind.values)),
        OpenApiParameter("status", str, description="Default open; or dismissed, resolved, all"),
        OpenApiParameter("severity", str, enum=list(Finding.Severity.values)),
        OpenApiParameter("site", str),
        OpenApiParameter("assignee", str, description="me, none or a user ID"),
    ]
)
class FindingListView(generics.ListAPIView):
    serializer_class = FindingSerializer
    pagination_class = FindingPagination
    permission_classes = [HasPermission(catalog.DISCOVERY_VIEW)]

    def get_queryset(self):
        qs = visible_findings(self.request.user)
        params = self.request.query_params
        wanted = params.get("status", "open")
        if wanted != "all":
            qs = qs.filter(status=wanted) if wanted in Finding.Status.values else qs.none()
        for key, choices in (("kind", Finding.Kind.values), ("severity", Finding.Severity.values)):
            if value := params.get(key):
                qs = qs.filter(**{key: value}) if value in choices else qs.none()
        if site := params.get("site"):
            qs = qs.filter(asset__site_id=site) if _is_uuid(site) else qs.none()
        assignee = params.get("assignee")
        if assignee == "me":
            qs = qs.filter(assignee=self.request.user)
        elif assignee == "none":
            qs = qs.filter(assignee__isnull=True)
        elif assignee:
            qs = qs.filter(assignee_id=assignee) if _is_uuid(assignee) else qs.none()
        return qs


class SummaryRowSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(choices=Finding.Kind.choices)
    open = serializers.IntegerField()
    high = serializers.IntegerField()


class FindingSummaryView(APIView):
    permission_classes = [HasPermission(catalog.DISCOVERY_VIEW)]

    @extend_schema(responses=SummaryRowSerializer(many=True))
    def get(self, request):
        rows = {
            (r["kind"], r["severity"]): r["n"]
            for r in visible_findings(request.user)
            .filter(status=Finding.Status.OPEN)
            .values("kind", "severity")
            .annotate(n=Count("pk"))
        }
        data = [
            {
                "kind": kind,
                "open": sum(n for (k, _), n in rows.items() if k == kind),
                "high": rows.get((kind, Finding.Severity.HIGH), 0),
            }
            for kind in Finding.Kind.values
        ]
        return Response(SummaryRowSerializer(data, many=True).data)


class _FindingAction(APIView):
    permission_classes = [HasPermission(catalog.RECONCILIATION_DECIDE)]

    def finding(self, request, pk):
        return get_object_or_404(visible_findings(request.user), pk=pk)

    def respond(self, request, finding):
        finding = visible_findings(request.user).get(pk=finding.pk)
        return Response(FindingSerializer(finding).data, headers={"ETag": f'"{finding.version}"'})


class FindingAssignSerializer(serializers.Serializer):
    assignee = serializers.UUIDField(allow_null=True)


class FindingAssignView(_FindingAction):
    @extend_schema(
        request=FindingAssignSerializer, responses=FindingSerializer, parameters=[IF_MATCH]
    )
    def post(self, request, pk):
        finding = self.finding(request, pk)
        data = FindingAssignSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        assignee = validate_assignee(data.validated_data["assignee"], [finding.asset.site_id])
        return self.respond(
            request, services.assign(request, finding, assignee, _if_match(request))
        )


class FindingDismissView(_FindingAction):
    @extend_schema(request=ReasonSerializer, responses=FindingSerializer, parameters=[IF_MATCH])
    def post(self, request, pk):
        finding = self.finding(request, pk)
        data = ReasonSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        return self.respond(
            request,
            services.dismiss(
                request, finding, data.validated_data["reason"].strip(), _if_match(request)
            ),
        )


class FindingReopenView(_FindingAction):
    @extend_schema(request=ReasonSerializer, responses=FindingSerializer, parameters=[IF_MATCH])
    def post(self, request, pk):
        finding = self.finding(request, pk)
        data = ReasonSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        return self.respond(
            request,
            services.reopen(
                request, finding, data.validated_data["reason"].strip(), _if_match(request)
            ),
        )


class RefreshResultSerializer(serializers.Serializer):
    opened = serializers.IntegerField()
    refreshed = serializers.IntegerField()
    resolved = serializers.IntegerField()


class FindingRefreshView(APIView):
    """Recompute findings now (also runs hourly from Celery beat)."""

    permission_classes = [HasPermission(catalog.RECONCILIATION_DECIDE)]

    @extend_schema(request=None, responses=RefreshResultSerializer)
    def post(self, request):
        return Response(RefreshResultSerializer(services.refresh()).data)
