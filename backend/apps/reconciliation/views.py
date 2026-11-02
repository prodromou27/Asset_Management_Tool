from uuid import UUID

from django.db.models import Exists, OuterRef, Q
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import generics, serializers
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts import catalog
from apps.accounts.permissions import HasPermission
from apps.assets.models import TECHNICAL_FIELDS, FieldLock, FieldProvenance
from apps.assets.selectors import visible_assets
from apps.assets.serializers import ReasonSerializer
from apps.observations.models import Observation
from apps.organizations import scope
from config.api import ApiError, ItemsCursorPagination

from . import services
from .models import AssetMerge, FieldConflict, ReconciliationCandidate, SourceLink
from .serializers import (
    ApproveSerializer,
    AssetEvidenceSerializer,
    AssetMergeSerializer,
    CandidateSerializer,
    FieldConflictSerializer,
    LockSerializer,
    MergeRequestSerializer,
    ObservationDetailSerializer,
    ObservationSummarySerializer,
    ResolveConflictSerializer,
    SourceLinkSerializer,
)

IF_MATCH = OpenApiParameter("If-Match", str, OpenApiParameter.HEADER, required=True)


def _is_uuid(value) -> bool:
    try:
        UUID(str(value))
    except ValueError:
        return False
    return True


def _if_match(request):
    raw = request.headers.get("If-Match")
    if raw is None:
        return None
    try:
        return int(raw.strip('"W/ '))
    except ValueError:
        return -1


# --- Scoped querysets ---------------------------------------------------------------------


def visible_candidates(user):
    qs = ReconciliationCandidate.objects.select_related(
        "instance",
        "site",
        "observation",
        "suggested_category",
        "proposed_asset",
        "decided_by",
        "resulting_asset",
    )
    return scope.restrict(qs, user, field="site")


def visible_observations(user):
    """An observation is visible if its instance's default site is in scope, or the
    device it describes is linked to an asset the user can see."""
    site_ids = scope.accessible_site_ids(user)
    if site_ids is scope.ALL:
        return Observation.objects.select_related("instance")
    linked = SourceLink.objects.filter(
        instance_id=OuterRef("instance_id"),
        external_id=OuterRef("external_id"),
        asset__site__in=site_ids,
    )
    return Observation.objects.select_related("instance").filter(
        Q(instance__default_site__in=site_ids) | Q(Exists(linked))
    )


def visible_conflicts(user):
    return scope.restrict(
        FieldConflict.objects.select_related("asset", "instance", "observation", "resolved_by"),
        user,
        field="asset__site",
    )


# --- Candidates ------------------------------------------------------------------------------


class CandidatePagination(ItemsCursorPagination):
    ordering = ("-modified_at", "-id")


@extend_schema(
    parameters=[
        OpenApiParameter(
            "status",
            str,
            description=(
                "Default: open and held. Or one of open, held, linked, created, "
                "rejected, superseded, all."
            ),
        ),
        OpenApiParameter("rule", str, enum=list(ReconciliationCandidate.Rule.values)),
        OpenApiParameter("instance", str),
    ]
)
class CandidateListView(generics.ListAPIView):
    serializer_class = CandidateSerializer
    pagination_class = CandidatePagination
    permission_classes = [HasPermission(catalog.DISCOVERY_VIEW)]

    def get_queryset(self):
        qs = visible_candidates(self.request.user)
        params = self.request.query_params
        wanted = params.get("status", "")
        if wanted == "":
            qs = qs.filter(status__in=ReconciliationCandidate.OPEN_STATES)
        elif wanted != "all":
            qs = (
                qs.filter(status=wanted)
                if wanted in ReconciliationCandidate.Status.values
                else qs.none()
            )
        if rule := params.get("rule"):
            qs = qs.filter(rule=rule) if rule in ReconciliationCandidate.Rule.values else qs.none()
        if instance := params.get("instance"):
            qs = qs.filter(instance_id=instance) if _is_uuid(instance) else qs.none()
        return qs


class CandidateDetailView(APIView):
    permission_classes = [HasPermission(catalog.DISCOVERY_VIEW)]

    @extend_schema(responses=CandidateSerializer)
    def get(self, request, pk):
        candidate = get_object_or_404(visible_candidates(request.user), pk=pk)
        return Response(
            CandidateSerializer(candidate, context={"request": request}).data,
            headers={"ETag": f'"{candidate.version}"'},
        )


class _DecisionView(APIView):
    permission_classes = [HasPermission(catalog.RECONCILIATION_DECIDE)]

    def candidate(self, request, pk):
        return get_object_or_404(visible_candidates(request.user), pk=pk)

    def respond(self, request, candidate):
        candidate = visible_candidates(request.user).get(pk=candidate.pk)
        return Response(
            CandidateSerializer(candidate, context={"request": request}).data,
            headers={"ETag": f'"{candidate.version}"'},
        )


class ApproveCandidateView(_DecisionView):
    @extend_schema(request=ApproveSerializer, responses=CandidateSerializer, parameters=[IF_MATCH])
    def post(self, request, pk):
        candidate = self.candidate(request, pk)
        data = ApproveSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        values = data.validated_data
        reason = values["reason"].strip()
        if values["action"] == "link":
            asset = visible_assets(request.user).filter(pk=values["asset"]).first()
            if asset is None:
                raise serializers.ValidationError({"asset": ["Asset not found."]})
            candidate = services.approve_link(request, candidate, asset, reason, _if_match(request))
        else:
            if catalog.ASSETS_CREATE not in request.user.permission_codes():
                raise ApiError(
                    "PERMISSION_DENIED", "Creating assets needs the asset create permission.", 403
                )
            candidate = services.approve_create(
                request, candidate, values, reason, _if_match(request)
            )
        return self.respond(request, candidate)


class RejectCandidateView(_DecisionView):
    @extend_schema(request=ReasonSerializer, responses=CandidateSerializer, parameters=[IF_MATCH])
    def post(self, request, pk):
        candidate = self.candidate(request, pk)
        data = ReasonSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        return self.respond(
            request,
            services.reject(
                request, candidate, data.validated_data["reason"].strip(), _if_match(request)
            ),
        )


class HoldCandidateView(_DecisionView):
    @extend_schema(request=ReasonSerializer, responses=CandidateSerializer, parameters=[IF_MATCH])
    def post(self, request, pk):
        candidate = self.candidate(request, pk)
        data = ReasonSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        return self.respond(
            request,
            services.hold(
                request, candidate, data.validated_data["reason"].strip(), _if_match(request)
            ),
        )


# --- Observations ---------------------------------------------------------------------------


class ObservationPagination(ItemsCursorPagination):
    ordering = ("-received_at", "-id")


@extend_schema(parameters=[OpenApiParameter("instance", str), OpenApiParameter("external_id", str)])
class ObservationListView(generics.ListAPIView):
    serializer_class = ObservationSummarySerializer
    pagination_class = ObservationPagination
    permission_classes = [HasPermission(catalog.DISCOVERY_VIEW)]

    def get_queryset(self):
        qs = visible_observations(self.request.user)
        params = self.request.query_params
        if instance := params.get("instance"):
            qs = qs.filter(instance_id=instance) if _is_uuid(instance) else qs.none()
        if external_id := params.get("external_id"):
            qs = qs.filter(external_id=external_id)
        return qs


class ObservationDetailView(APIView):
    permission_classes = [HasPermission(catalog.DISCOVERY_VIEW)]

    @extend_schema(responses=ObservationDetailSerializer)
    def get(self, request, pk):
        observation = get_object_or_404(visible_observations(request.user), pk=pk)
        return Response(ObservationDetailSerializer(observation).data)


class AssetObservationListView(generics.ListAPIView):
    serializer_class = ObservationDetailSerializer
    pagination_class = ObservationPagination
    permission_classes = [HasPermission(catalog.DISCOVERY_VIEW)]

    def get_queryset(self):
        asset = get_object_or_404(visible_assets(self.request.user), pk=self.kwargs["pk"])
        pairs = SourceLink.objects.filter(asset=asset).values_list("instance_id", "external_id")
        condition = Q(pk__in=[])
        for instance_id, external_id in pairs:
            condition |= Q(instance_id=instance_id, external_id=external_id)
        return Observation.objects.select_related("instance").filter(condition)


# --- Evidence, locks, conflicts, links, merges ----------------------------------------


def evidence_for(asset) -> dict:
    # Unlinked links no longer reference the asset; they appear in asset history.
    links = list(
        SourceLink.objects.filter(asset=asset).select_related(
            "instance", "last_observation", "linked_by"
        )
    )
    provenance = {
        p.field: p
        for p in FieldProvenance.objects.filter(asset=asset).select_related(
            "instance", "recorded_by"
        )
    }
    locks = {
        lock.field: lock
        for lock in FieldLock.objects.filter(asset=asset).select_related("locked_by")
    }
    conflicts = list(
        FieldConflict.objects.filter(asset=asset, status=FieldConflict.Status.OPEN).select_related(
            "asset", "instance", "observation"
        )
    )
    rows = []
    for field in TECHNICAL_FIELDS:
        value = getattr(asset, field) or ""
        prov = provenance.get(field)
        lock = locks.get(field)
        sources = []
        for link in links:
            if link.last_observation is None:
                continue
            observed = link.last_observation.normalized.get(field)
            sources.append(
                {
                    "instance": link.instance,
                    "external_id": link.external_id,
                    "value": observed,
                    "observed_at": link.last_observation.observed_at,
                    "link_status": link.status,
                    "differs": observed not in (None, "") and observed != value,
                }
            )
        rows.append(
            {
                "field": field,
                "value": value,
                "provenance": None
                if prov is None
                else {
                    "kind": prov.kind,
                    "instance": prov.instance,
                    "observed_at": prov.observed_at,
                    "recorded_at": prov.recorded_at,
                    "recorded_by": prov.recorded_by.username if prov.recorded_by else None,
                },
                "lock": None
                if lock is None
                else {
                    "locked_by": lock.locked_by.username if lock.locked_by else None,
                    "locked_at": lock.locked_at,
                    "reason": lock.reason,
                },
                "sources": sources,
                "open_conflicts": [c for c in conflicts if c.field == field],
            }
        )
    merges = AssetMerge.objects.filter(Q(survivor=asset) | Q(merged=asset)).select_related(
        "survivor", "merged", "performed_by", "reverted_by"
    )
    return {"field_evidence": rows, "links": links, "merges": list(merges)}


class AssetEvidenceView(APIView):
    permission_classes = [HasPermission(catalog.DISCOVERY_VIEW)]

    @extend_schema(responses=AssetEvidenceSerializer)
    def get(self, request, pk):
        asset = get_object_or_404(visible_assets(request.user), pk=pk)
        return Response(AssetEvidenceSerializer(evidence_for(asset)).data)


class FieldLockView(APIView):
    permission_classes = [HasPermission(catalog.ASSETS_EDIT_TECHNICAL)]

    @extend_schema(request=LockSerializer, responses=AssetEvidenceSerializer)
    def post(self, request, pk):
        asset = get_object_or_404(visible_assets(request.user), pk=pk)
        data = LockSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        services.lock_field(
            request, asset, data.validated_data["field"], data.validated_data["reason"].strip()
        )
        return Response(AssetEvidenceSerializer(evidence_for(asset)).data)


class FieldUnlockView(APIView):
    permission_classes = [HasPermission(catalog.ASSETS_EDIT_TECHNICAL)]

    @extend_schema(request=LockSerializer, responses=AssetEvidenceSerializer)
    def post(self, request, pk):
        asset = get_object_or_404(visible_assets(request.user), pk=pk)
        data = LockSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        services.unlock_field(
            request, asset, data.validated_data["field"], data.validated_data["reason"].strip()
        )
        return Response(AssetEvidenceSerializer(evidence_for(asset)).data)


class ConflictPagination(ItemsCursorPagination):
    ordering = ("-modified_at", "-id")


@extend_schema(
    parameters=[OpenApiParameter("status", str, enum=["open", "accepted", "dismissed", "all"])]
)
class ConflictListView(generics.ListAPIView):
    serializer_class = FieldConflictSerializer
    pagination_class = ConflictPagination
    permission_classes = [HasPermission(catalog.DISCOVERY_VIEW)]

    def get_queryset(self):
        qs = visible_conflicts(self.request.user)
        wanted = self.request.query_params.get("status", "open")
        if wanted != "all":
            qs = qs.filter(status=wanted) if wanted in FieldConflict.Status.values else qs.none()
        return qs


class ResolveConflictView(APIView):
    permission_classes = [HasPermission(catalog.ASSETS_EDIT_TECHNICAL)]

    @extend_schema(request=ResolveConflictSerializer, responses=FieldConflictSerializer)
    def post(self, request, pk):
        conflict = get_object_or_404(visible_conflicts(request.user), pk=pk)
        data = ResolveConflictSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        conflict = services.resolve_conflict(
            request,
            conflict,
            data.validated_data["resolution"],
            data.validated_data["reason"].strip(),
        )
        return Response(
            FieldConflictSerializer(visible_conflicts(request.user).get(pk=conflict.pk)).data
        )


class UnlinkView(APIView):
    permission_classes = [HasPermission(catalog.RECONCILIATION_DECIDE)]

    @extend_schema(request=ReasonSerializer, responses=SourceLinkSerializer)
    def post(self, request, pk):
        link = get_object_or_404(
            SourceLink.objects.filter(asset__in=visible_assets(request.user)).select_related(
                "instance"
            ),
            pk=pk,
        )
        data = ReasonSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        link = services.unlink(request, link, data.validated_data["reason"].strip())
        return Response(SourceLinkSerializer(link).data)


class MergeView(APIView):
    permission_classes = [HasPermission(catalog.ASSETS_MERGE)]

    @extend_schema(
        request=MergeRequestSerializer, responses=AssetMergeSerializer, parameters=[IF_MATCH]
    )
    def post(self, request, pk):
        assets = visible_assets(request.user)
        survivor = get_object_or_404(assets, pk=pk)
        data = MergeRequestSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        merged = assets.filter(pk=data.validated_data["source_asset"]).first()
        if merged is None:
            raise serializers.ValidationError({"source_asset": ["Asset not found."]})
        record = services.merge(
            request, survivor, merged, data.validated_data["reason"].strip(), _if_match(request)
        )
        return Response(AssetMergeSerializer(record).data)


class RevertMergeView(APIView):
    permission_classes = [HasPermission(catalog.ASSETS_MERGE)]

    @extend_schema(request=ReasonSerializer, responses=AssetMergeSerializer)
    def post(self, request, pk):
        visible = visible_assets(request.user).values("pk")
        record = get_object_or_404(
            AssetMerge.objects.filter(survivor__in=visible, merged__in=visible), pk=pk
        )
        data = ReasonSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        record = services.revert_merge(request, record, data.validated_data["reason"].strip())
        return Response(AssetMergeSerializer(record).data)
