"""Lifecycle API (docs/04 "EOL": /lifecycle/findings, /products, /sources,
/matches/{id}/approve, /exceptions; asset detail: /assets/{id}/lifecycle).

Reading needs ``lifecycle.view``; catalogue entry needs ``lifecycle.manage`` (dates stay
unverified); verification, match decisions, exceptions and reassessment need
``lifecycle.approve``. Everything about assets (findings, matches, exceptions, affected
assets, counts) is filtered by ``visible_assets`` so site scope is never widened.
"""

from django.conf import settings
from django.db.models import Count, OuterRef, Q, Subquery
from django.db.models.functions import Coalesce
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import generics
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts import catalog
from apps.accounts.permissions import HasPermission
from apps.assets.selectors import visible_assets
from apps.assets.serializers import ReasonSerializer
from config.api import ApiError, ItemsCursorPagination

from . import services
from .models import (
    AssetLifecycleMatch,
    LifecycleAlias,
    LifecycleAssessment,
    LifecycleAssessmentHistory,
    LifecycleException,
    LifecycleMilestone,
    LifecycleProduct,
    LifecycleSource,
    VendorAlias,
)
from .serializers import (
    AssetLifecycleSerializer,
    LifecycleAliasSerializer,
    LifecycleAssessmentSerializer,
    LifecycleExceptionSerializer,
    LifecycleExceptionWriteSerializer,
    LifecycleMatchApproveSerializer,
    LifecycleMatchRejectSerializer,
    LifecycleMatchSerializer,
    LifecycleMilestoneReviewSerializer,
    LifecycleMilestoneSerializer,
    LifecycleMilestoneUpdateSerializer,
    LifecycleMilestoneWriteSerializer,
    LifecyclePolicySerializer,
    LifecycleProductDetailSerializer,
    LifecycleProductSerializer,
    LifecycleProductUpdateSerializer,
    LifecycleProductWriteSerializer,
    LifecycleRevisionSerializer,
    LifecycleSourceSerializer,
    LifecycleStatementSerializer,
    LifecycleSummaryRowSerializer,
    VendorAliasSerializer,
)

IF_MATCH = OpenApiParameter("If-Match", str, OpenApiParameter.HEADER, required=True)
View = HasPermission(catalog.LIFECYCLE_VIEW)
Manage = HasPermission(catalog.LIFECYCLE_VIEW, catalog.LIFECYCLE_MANAGE)
Approve = HasPermission(catalog.LIFECYCLE_VIEW, catalog.LIFECYCLE_APPROVE)
AssetView = HasPermission(catalog.ASSETS_VIEW, catalog.LIFECYCLE_VIEW)


def _if_match(request):
    raw = request.headers.get("If-Match")
    if raw is None:
        return None
    try:
        return int(raw.strip('"W/ '))
    except ValueError:
        return -1


def _etag(obj) -> dict:
    return {"ETag": f'"{obj.version}"'}


def _visible_ids(user):
    return visible_assets(user).filter(archived_at__isnull=True).values("pk")


def products_for(user):
    visible = _visible_ids(user)
    matched = (
        AssetLifecycleMatch.objects.filter(
            product=OuterRef("pk"), state=AssetLifecycleMatch.State.MATCHED, asset__in=visible
        )
        .order_by()
        .values("product")
        .annotate(n=Count("pk"))
        .values("n")
    )
    return LifecycleProduct.objects.annotate(
        milestones_verified=Count(
            "milestones", filter=Q(milestones__verification="verified"), distinct=True
        ),
        milestones_pending=Count(
            "milestones", filter=Q(milestones__verification="pending"), distinct=True
        ),
        alias_count=Count("aliases", distinct=True),
        matched_assets=Coalesce(Subquery(matched), 0),
    )


def _product_detail(request, pk):
    return get_object_or_404(
        products_for(request.user)
        .select_related("statement_source", "statement_verified_by", "created_by", "modified_by")
        .prefetch_related("aliases__created_by", "milestones__source", "milestones__reviewed_by"),
        pk=pk,
    )


def _respond_product(request, pk, status=200):
    product = _product_detail(request, pk)
    return Response(
        LifecycleProductDetailSerializer(product).data, status=status, headers=_etag(product)
    )


# --- Catalogue ---------------------------------------------------------------------------------


class ProductPagination(ItemsCursorPagination):
    ordering = ("vendor_key", "name_key", "release_key", "id")


class ProductListCreateView(generics.ListAPIView):
    serializer_class = LifecycleProductSerializer
    pagination_class = ProductPagination

    def get_permissions(self):
        return [(Manage if self.request.method == "POST" else View)()]

    @extend_schema(
        parameters=[
            OpenApiParameter("kind", str),
            OpenApiParameter("vendor", str),
            OpenApiParameter("q", str),
            OpenApiParameter("needs_review", bool, description="Has dates awaiting verification"),
        ]
    )
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

    def get_queryset(self):
        qs = products_for(self.request.user)
        params = self.request.query_params
        if kind := params.get("kind"):
            qs = qs.filter(kind=kind)
        if vendor := params.get("vendor", "").strip():
            qs = qs.filter(vendor__iexact=vendor)
        if q := params.get("q", "").strip()[:100]:
            qs = qs.filter(
                Q(name__icontains=q)
                | Q(vendor__icontains=q)
                | Q(release__icontains=q)
                | Q(family__icontains=q)
                | Q(aliases__value__icontains=q)
            ).distinct()
        if params.get("needs_review") == "true":
            qs = qs.filter(milestones_pending__gt=0)
        return qs

    @extend_schema(
        request=LifecycleProductWriteSerializer, responses={201: LifecycleProductDetailSerializer}
    )
    def post(self, request):
        data = LifecycleProductWriteSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        product = services.create_product(request, data.validated_data)
        return _respond_product(request, product.pk, status=201)


class ProductDetailView(APIView):
    def get_permissions(self):
        return [(Manage if self.request.method == "PATCH" else View)()]

    @extend_schema(responses=LifecycleProductDetailSerializer)
    def get(self, request, pk):
        return _respond_product(request, pk)

    @extend_schema(
        request=LifecycleProductUpdateSerializer,
        responses=LifecycleProductDetailSerializer,
        parameters=[IF_MATCH],
    )
    def patch(self, request, pk):
        product = get_object_or_404(LifecycleProduct, pk=pk)
        data = LifecycleProductUpdateSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        services.update_product(request, product, data.validated_data, _if_match(request))
        return _respond_product(request, pk)


class ProductStatementView(APIView):
    permission_classes = [Approve]

    @extend_schema(
        request=LifecycleStatementSerializer,
        responses=LifecycleProductDetailSerializer,
        parameters=[IF_MATCH],
    )
    def post(self, request, pk):
        product = get_object_or_404(LifecycleProduct, pk=pk)
        data = LifecycleStatementSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        v = data.validated_data
        services.set_statement(
            request,
            product,
            v["support_statement"],
            v.get("statement_source"),
            v["verify"],
            _if_match(request),
        )
        return _respond_product(request, pk)


class ProductAliasView(APIView):
    permission_classes = [Manage]

    @extend_schema(
        request=LifecycleAliasSerializer, responses={201: LifecycleProductDetailSerializer}
    )
    def post(self, request, pk):
        product = get_object_or_404(LifecycleProduct, pk=pk)
        data = LifecycleAliasSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        services.add_alias(request, product, data.validated_data)
        return _respond_product(request, pk, status=201)


class AliasRemoveView(APIView):
    permission_classes = [Manage]

    @extend_schema(request=ReasonSerializer, responses=LifecycleProductDetailSerializer)
    def post(self, request, pk):
        alias = get_object_or_404(LifecycleAlias, pk=pk)
        data = ReasonSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        product_id = alias.product_id
        services.remove_alias(request, alias, data.validated_data["reason"])
        return _respond_product(request, product_id)


class ProductMilestoneView(APIView):
    permission_classes = [Manage]

    @extend_schema(
        request=LifecycleMilestoneWriteSerializer, responses={201: LifecycleProductDetailSerializer}
    )
    def post(self, request, pk):
        product = get_object_or_404(LifecycleProduct, pk=pk)
        data = LifecycleMilestoneWriteSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        services.add_milestone(request, product, data.validated_data)
        return _respond_product(request, pk, status=201)


class MilestoneDetailView(APIView):
    permission_classes = [Manage]

    @extend_schema(
        request=LifecycleMilestoneUpdateSerializer,
        responses=LifecycleMilestoneSerializer,
        parameters=[IF_MATCH],
    )
    def patch(self, request, pk):
        milestone = get_object_or_404(LifecycleMilestone, pk=pk)
        data = LifecycleMilestoneUpdateSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        milestone = services.update_milestone(
            request, milestone, data.validated_data, _if_match(request)
        )
        return Response(LifecycleMilestoneSerializer(milestone).data, headers=_etag(milestone))


class MilestoneReviewView(APIView):
    permission_classes = [Approve]

    @extend_schema(
        request=LifecycleMilestoneReviewSerializer,
        responses=LifecycleMilestoneSerializer,
        parameters=[IF_MATCH],
    )
    def post(self, request, pk):
        milestone = get_object_or_404(LifecycleMilestone, pk=pk)
        data = LifecycleMilestoneReviewSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        milestone = services.review_milestone(
            request,
            milestone,
            data.validated_data["decision"],
            data.validated_data["note"],
            _if_match(request),
        )
        return Response(LifecycleMilestoneSerializer(milestone).data, headers=_etag(milestone))


class ProductRevisionsView(generics.ListAPIView):
    serializer_class = LifecycleRevisionSerializer
    permission_classes = [View]
    pagination_class = None

    def get_queryset(self):
        product = get_object_or_404(LifecycleProduct, pk=self.kwargs["pk"])
        return product.revisions.select_related("actor")


class AssessmentPagination(ItemsCursorPagination):
    ordering = ("milestone_date", "id")


class ProductAssetsView(generics.ListAPIView):
    """Assessments of assets matched to this product, in the caller's sites only."""

    serializer_class = LifecycleAssessmentSerializer
    pagination_class = AssessmentPagination
    permission_classes = [AssetView]

    def get_queryset(self):
        product = get_object_or_404(LifecycleProduct, pk=self.kwargs["pk"])
        return _assessments(self.request.user).filter(product=product)


class ProductReassessView(APIView):
    permission_classes = [Approve]

    @extend_schema(request=None, responses={202: None})
    def post(self, request, pk):
        product = get_object_or_404(LifecycleProduct, pk=pk)
        services.request_reassessment(request, "product", product.pk)
        services._queue(product.pk)
        return Response(status=202)


class SourceListCreateView(generics.ListAPIView):
    serializer_class = LifecycleSourceSerializer
    pagination_class = None

    def get_permissions(self):
        return [(Manage if self.request.method == "POST" else View)()]

    def get_queryset(self):
        qs = LifecycleSource.objects.select_related("created_by")
        if q := self.request.query_params.get("q", "").strip()[:100]:
            qs = qs.filter(Q(title__icontains=q) | Q(publisher__icontains=q) | Q(url__icontains=q))
        return qs[:500]

    @extend_schema(request=LifecycleSourceSerializer, responses={201: LifecycleSourceSerializer})
    def post(self, request):
        data = LifecycleSourceSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        source = services.create_source(request, data.validated_data)
        return Response(LifecycleSourceSerializer(source).data, status=201, headers=_etag(source))


class SourceDetailView(APIView):
    def get_permissions(self):
        return [(Manage if self.request.method == "PATCH" else View)()]

    @extend_schema(responses=LifecycleSourceSerializer)
    def get(self, request, pk):
        source = get_object_or_404(LifecycleSource, pk=pk)
        return Response(LifecycleSourceSerializer(source).data, headers=_etag(source))

    @extend_schema(
        request=LifecycleSourceSerializer,
        responses=LifecycleSourceSerializer,
        parameters=[IF_MATCH],
    )
    def patch(self, request, pk):
        source = get_object_or_404(LifecycleSource, pk=pk)
        data = LifecycleSourceSerializer(source, data=request.data, partial=True)
        data.is_valid(raise_exception=True)
        source = services.update_source(request, source, data.validated_data, _if_match(request))
        return Response(LifecycleSourceSerializer(source).data, headers=_etag(source))


class VendorAliasListCreateView(generics.ListAPIView):
    serializer_class = VendorAliasSerializer
    pagination_class = None

    def get_permissions(self):
        return [(Manage if self.request.method == "POST" else View)()]

    def get_queryset(self):
        return VendorAlias.objects.select_related("created_by")

    @extend_schema(request=VendorAliasSerializer, responses={201: VendorAliasSerializer})
    def post(self, request):
        data = VendorAliasSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        obj = services.add_vendor_alias(
            request, data.validated_data["alias"], data.validated_data["vendor"]
        )
        return Response(VendorAliasSerializer(obj).data, status=201)


class VendorAliasRemoveView(APIView):
    permission_classes = [Manage]

    @extend_schema(request=ReasonSerializer, responses={204: None})
    def post(self, request, pk):
        obj = get_object_or_404(VendorAlias, pk=pk)
        data = ReasonSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        services.remove_vendor_alias(request, obj, data.validated_data["reason"])
        return Response(status=204)


# --- Findings, review queue, exceptions -----------------------------------------------------------


def _assessments(user):
    return LifecycleAssessment.objects.filter(asset__in=_visible_ids(user)).select_related(
        "asset__site", "product", "exception__approved_by"
    )


class FindingListView(generics.ListAPIView):
    serializer_class = LifecycleAssessmentSerializer
    pagination_class = AssessmentPagination
    permission_classes = [AssetView]

    @extend_schema(
        parameters=[
            OpenApiParameter("dimension", str),
            OpenApiParameter("status", str, description="Effective status"),
            OpenApiParameter("site", str),
            OpenApiParameter("vendor", str),
            OpenApiParameter("q", str, description="Asset name"),
            OpenApiParameter("exception", bool),
        ]
    )
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

    def get_queryset(self):
        from apps.organizations import scope

        qs = _assessments(self.request.user)
        params = self.request.query_params
        if dimension := params.get("dimension"):
            qs = qs.filter(dimension=dimension)
        if status := params.get("status"):
            qs = qs.filter(effective_status__in=status.split(","))
        if site := params.get("site"):
            try:
                qs = qs.filter(asset__site_id__in=scope.descendants({site}))
            except Exception:  # noqa: BLE001 - malformed ID: no rows
                return qs.none()
        if vendor := params.get("vendor", "").strip():
            qs = qs.filter(product__vendor__iexact=vendor)
        if q := params.get("q", "").strip()[:100]:
            qs = qs.filter(asset__name__icontains=q)
        if params.get("exception") == "true":
            qs = qs.filter(exception__isnull=False)
        return qs


class SummaryView(APIView):
    permission_classes = [AssetView]

    @extend_schema(responses=LifecycleSummaryRowSerializer(many=True))
    def get(self, request):
        rows = (
            _assessments(request.user)
            .order_by()
            .values("dimension", "effective_status")
            .annotate(count=Count("pk"))
        )
        return Response(LifecycleSummaryRowSerializer(rows, many=True).data)


class PolicyView(APIView):
    permission_classes = [View]

    @extend_schema(responses=LifecyclePolicySerializer)
    def get(self, request):
        return Response(
            LifecyclePolicySerializer(
                {
                    "warning_days": services.thresholds(),
                    "count_extended_support": settings.ITAM_LIFECYCLE_COUNT_EXTENDED_SUPPORT,
                    "max_exception_days": settings.ITAM_LIFECYCLE_MAX_EXCEPTION_DAYS,
                    "today": services.today_utc(),
                }
            ).data
        )


class MatchPagination(ItemsCursorPagination):
    ordering = ("-modified_at", "id")


def _matches(user):
    return AssetLifecycleMatch.objects.filter(asset__in=_visible_ids(user)).select_related(
        "asset__site", "product", "reviewed_by"
    )


class MatchListView(generics.ListAPIView):
    serializer_class = LifecycleMatchSerializer
    pagination_class = MatchPagination
    permission_classes = [AssetView]

    @extend_schema(
        parameters=[
            OpenApiParameter("state", str, description="Default: candidate"),
            OpenApiParameter("dimension", str),
            OpenApiParameter("q", str),
        ]
    )
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

    def get_queryset(self):
        params = self.request.query_params
        qs = _matches(self.request.user).filter(state=params.get("state", "candidate"))
        if dimension := params.get("dimension"):
            qs = qs.filter(dimension=dimension)
        if q := params.get("q", "").strip()[:100]:
            qs = qs.filter(
                Q(asset__name__icontains=q)
                | Q(asset__model__icontains=q)
                | Q(asset__os_name__icontains=q)
            )
        return qs


class _MatchAction(APIView):
    permission_classes = [Approve, AssetView]

    def match(self, request, pk):
        return get_object_or_404(_matches(request.user), pk=pk)

    def respond(self, request, match):
        match = _matches(request.user).get(pk=match.pk)
        return Response(LifecycleMatchSerializer(match).data, headers=_etag(match))


class MatchApproveView(_MatchAction):
    @extend_schema(
        request=LifecycleMatchApproveSerializer,
        responses=LifecycleMatchSerializer,
        parameters=[IF_MATCH],
    )
    def post(self, request, pk):
        match = self.match(request, pk)
        data = LifecycleMatchApproveSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        v = data.validated_data
        match = services.approve_match(
            request, match, v["product"], v["remember_alias"], v["note"], _if_match(request)
        )
        return self.respond(request, match)


class MatchRejectView(_MatchAction):
    @extend_schema(
        request=LifecycleMatchRejectSerializer,
        responses=LifecycleMatchSerializer,
        parameters=[IF_MATCH],
    )
    def post(self, request, pk):
        match = self.match(request, pk)
        data = LifecycleMatchRejectSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        v = data.validated_data
        match = services.reject_match(
            request, match, [str(p) for p in v["products"]], v["note"], _if_match(request)
        )
        return self.respond(request, match)


class ExceptionPagination(ItemsCursorPagination):
    ordering = ("expires_on", "id")


class ExceptionListView(generics.ListAPIView):
    serializer_class = LifecycleExceptionSerializer
    pagination_class = ExceptionPagination
    permission_classes = [AssetView]

    @extend_schema(parameters=[OpenApiParameter("active", bool)])
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

    def get_queryset(self):
        qs = LifecycleException.objects.filter(
            asset__in=_visible_ids(self.request.user)
        ).select_related("asset__site", "approved_by", "revoked_by")
        if self.request.query_params.get("active") == "true":
            qs = qs.filter(revoked_at__isnull=True, expires_on__gte=services.today_utc())
        return qs


class ExceptionRevokeView(APIView):
    permission_classes = [Approve, AssetView]

    @extend_schema(
        request=ReasonSerializer, responses=LifecycleExceptionSerializer, parameters=[IF_MATCH]
    )
    def post(self, request, pk):
        exc = get_object_or_404(
            LifecycleException.objects.filter(asset__in=_visible_ids(request.user)), pk=pk
        )
        data = ReasonSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        exc = services.revoke_exception(
            request, exc, data.validated_data["reason"], _if_match(request)
        )
        return Response(LifecycleExceptionSerializer(exc).data, headers=_etag(exc))


class ReassessAllView(APIView):
    permission_classes = [Approve]

    @extend_schema(request=None, responses={202: None})
    def post(self, request):
        services.request_reassessment(request, "all")
        services._queue(None)
        return Response(status=202)


# --- Asset detail -------------------------------------------------------------------------------


class AssetLifecycleView(APIView):
    permission_classes = [AssetView]

    def asset(self, request, pk):
        return get_object_or_404(visible_assets(request.user), pk=pk)

    @extend_schema(responses=AssetLifecycleSerializer)
    def get(self, request, pk):
        asset = self.asset(request, pk)
        assessments = list(
            LifecycleAssessment.objects.filter(asset=asset)
            .select_related("asset__site", "product", "exception__approved_by")
            .order_by("dimension")
        )
        milestone_ids = {i for a in assessments for i in a.milestone_ids}
        return Response(
            AssetLifecycleSerializer(
                {
                    "assessments": assessments,
                    "matches": AssetLifecycleMatch.objects.filter(asset=asset)
                    .select_related("asset__site", "product", "reviewed_by")
                    .order_by("dimension"),
                    "exceptions": LifecycleException.objects.filter(asset=asset).select_related(
                        "asset__site", "approved_by", "revoked_by"
                    ),
                    "history": LifecycleAssessmentHistory.objects.filter(asset=asset)[:50],
                    "evidence": LifecycleMilestone.objects.filter(pk__in=milestone_ids)
                    .select_related("source", "reviewed_by", "created_by")
                    .order_by("date"),
                }
            ).data
        )


class AssetReassessView(AssetLifecycleView):
    permission_classes = [AssetView]

    @extend_schema(request=None, responses=AssetLifecycleSerializer)
    def post(self, request, pk):
        asset = self.asset(request, pk)
        if not (
            {catalog.LIFECYCLE_MANAGE, catalog.LIFECYCLE_APPROVE} & request.user.permission_codes()
        ):
            raise ApiError("PERMISSION_DENIED", "You do not have permission to reassess.", 403)
        services.request_reassessment(request, "asset", asset.pk)
        services.reassess_assets([asset.pk])
        return self.get(request, pk)


class AssetExceptionCreateView(APIView):
    permission_classes = [Approve, AssetView]

    @extend_schema(
        request=LifecycleExceptionWriteSerializer, responses={201: LifecycleExceptionSerializer}
    )
    def post(self, request, pk):
        asset = get_object_or_404(visible_assets(request.user), pk=pk)
        data = LifecycleExceptionWriteSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        exc = services.create_exception(request, asset, data.validated_data)
        exc = LifecycleException.objects.select_related("asset__site", "approved_by").get(pk=exc.pk)
        return Response(LifecycleExceptionSerializer(exc).data, status=201, headers=_etag(exc))
