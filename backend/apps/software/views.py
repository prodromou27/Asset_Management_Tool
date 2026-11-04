"""Software API (docs/04: GET /software/products, /software/installations,
/assets/{id}/software).

Reading needs ``assets.view``; every count and list only covers assets in the caller's
sites (``visible_installations``). Manual entries need ``assets.edit`` on the asset;
lifecycle match decisions need ``lifecycle.approve``.
"""

from django.db.models import Count, IntegerField, OuterRef, Q, Subquery, Value
from django.db.models.functions import Coalesce
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import generics
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts import catalog
from apps.accounts.permissions import HasPermission
from apps.assets.models import Asset
from apps.assets.selectors import visible_assets
from apps.assets.serializers import ReasonSerializer
from apps.lifecycle.models import LifecycleProduct
from config.api import ApiError, ItemsCursorPagination

from . import selectors, services
from .models import SoftwareInstallation, SoftwareProduct, SoftwareVersion
from .serializers import (
    ManualSoftwareSerializer,
    SoftwareInstallationSerializer,
    SoftwareProductDetailSerializer,
    SoftwareProductSerializer,
    SoftwareVersionSerializer,
    VersionApproveSerializer,
    VersionRejectSerializer,
)

View = HasPermission(catalog.ASSETS_VIEW)
Approve = HasPermission(catalog.ASSETS_VIEW, catalog.LIFECYCLE_APPROVE)
ENDED = ("eos", "security_maintenance_ended")


def _count(visible, **filters):
    return Coalesce(
        Subquery(
            visible.filter(**filters)
            .order_by()
            .values("version__product" if "version__product" in filters else "version")
            .annotate(n=Count("pk"))
            .values("n")[:1],
            output_field=IntegerField(),
        ),
        Value(0),
    )


def products_for(user):
    visible = selectors.visible_installations(user)
    return SoftwareProduct.objects.annotate(
        version_count=Count("versions", distinct=True),
        installations=_count(visible, version__product=OuterRef("pk")),
        eos_versions=Count(
            "versions",
            filter=Q(versions__lifecycle_status__in=ENDED),
            distinct=True,
        ),
    )


def _asset_refs(asset_ids) -> dict:
    return {
        a["pk"]: {"id": a["pk"], "name": a["name"], "site_code": a["site__code"]}
        for a in Asset.objects.filter(pk__in=[i for i in asset_ids if i]).values(
            "pk", "name", "site__code"
        )
    }


class ProductPagination(ItemsCursorPagination):
    ordering = ("name_key", "publisher_key", "id")


class SoftwareProductListView(generics.ListAPIView):
    serializer_class = SoftwareProductSerializer
    pagination_class = ProductPagination
    permission_classes = [View]

    @extend_schema(
        parameters=[
            OpenApiParameter("q", str),
            OpenApiParameter("publisher", str),
            OpenApiParameter(
                "installed", bool, description="Only products installed in your sites"
            ),
            OpenApiParameter("lifecycle", str, description="ended | review"),
        ]
    )
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

    def get_queryset(self):
        qs = products_for(self.request.user)
        params = self.request.query_params
        if q := params.get("q", "").strip()[:100]:
            qs = qs.filter(Q(name__icontains=q) | Q(publisher__icontains=q))
        if publisher := params.get("publisher", "").strip():
            qs = qs.filter(publisher__iexact=publisher)
        if params.get("installed", "true") == "true":
            qs = qs.filter(installations__gt=0)
        if params.get("lifecycle") == "ended":
            qs = qs.filter(eos_versions__gt=0)
        elif params.get("lifecycle") == "review":
            qs = qs.filter(versions__lifecycle_state="candidate").distinct()
        return qs


def _versions_for(user, product):
    visible = selectors.visible_installations(user)
    return (
        product.versions.select_related("lifecycle_product", "lifecycle_reviewed_by")
        .annotate(install_count=_count(visible, version=OuterRef("pk")))
        .order_by("version_key")
    )


class SoftwareProductDetailView(APIView):
    permission_classes = [View]

    @extend_schema(responses=SoftwareProductDetailSerializer)
    def get(self, request, pk):
        product = get_object_or_404(products_for(request.user), pk=pk)
        data = SoftwareProductSerializer(product).data
        data["versions"] = SoftwareVersionSerializer(
            _versions_for(request.user, product), many=True
        ).data
        return Response(data)


class InstallationPagination(ItemsCursorPagination):
    ordering = ("-last_seen_at", "-id")


class SoftwareInstallationListView(generics.ListAPIView):
    serializer_class = SoftwareInstallationSerializer
    pagination_class = InstallationPagination
    permission_classes = [View]

    @extend_schema(
        parameters=[
            OpenApiParameter("product", int),
            OpenApiParameter("version", int),
            OpenApiParameter("q", str, description="Product or publisher"),
            OpenApiParameter("lifecycle_status", str),
        ]
    )
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

    def get_queryset(self):
        qs = selectors.visible_installations(self.request.user).select_related(
            "version__product", "instance", "created_by"
        )
        params = self.request.query_params
        try:
            if product := params.get("product"):
                qs = qs.filter(version__product_id=int(product))
            if version := params.get("version"):
                qs = qs.filter(version_id=int(version))
        except ValueError:
            return qs.none()
        if q := params.get("q", "").strip()[:100]:
            qs = qs.filter(
                Q(version__product__name__icontains=q) | Q(version__product__publisher__icontains=q)
            )
        if status := params.get("lifecycle_status"):
            qs = qs.filter(version__lifecycle_status__in=status.split(","))
        return qs

    def list(self, request, *args, **kwargs):
        page = self.paginate_queryset(self.filter_queryset(self.get_queryset()))
        assets = _asset_refs({getattr(r, "resolved_asset_id", None) for r in page})
        data = self.get_serializer(page, many=True, context={"assets": assets}).data
        return self.get_paginated_response(data)


class AssetSoftwareView(APIView):
    def get_permissions(self):
        if self.request.method == "POST":
            return [HasPermission(catalog.ASSETS_VIEW, catalog.ASSETS_EDIT)()]
        return [View()]

    @extend_schema(
        parameters=[OpenApiParameter("removed", bool, description="Include removed entries")],
        responses=SoftwareInstallationSerializer(many=True),
    )
    def get(self, request, pk):
        asset = get_object_or_404(visible_assets(request.user), pk=pk)
        include = request.query_params.get("removed") == "true"
        rows = (
            selectors.installations_for_asset(asset, include_removed=include)
            .select_related("version__product", "instance", "created_by")
            .order_by("version__product__name_key", "version__version_key")
        )
        assets = {asset.pk: {"id": asset.pk, "name": asset.name, "site_code": asset.site.code}}
        for row in rows:
            row.resolved_asset_id = asset.pk
        return Response(
            SoftwareInstallationSerializer(rows, many=True, context={"assets": assets}).data
        )

    @extend_schema(
        request=ManualSoftwareSerializer, responses={201: SoftwareInstallationSerializer}
    )
    def post(self, request, pk):
        asset = get_object_or_404(visible_assets(request.user), pk=pk)
        if asset.archived_at is not None:
            raise ApiError("ASSET_ARCHIVED", "Restore the asset before changing it.", 409)
        data = ManualSoftwareSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        row = services.add_manual(request, asset, data.validated_data)
        assets = {asset.pk: {"id": asset.pk, "name": asset.name, "site_code": asset.site.code}}
        return Response(
            SoftwareInstallationSerializer(row, context={"assets": assets}).data, status=201
        )


class InstallationRemoveView(APIView):
    permission_classes = [HasPermission(catalog.ASSETS_VIEW, catalog.ASSETS_EDIT)]

    @extend_schema(request=ReasonSerializer, responses=SoftwareInstallationSerializer)
    def post(self, request, pk):
        row = get_object_or_404(
            SoftwareInstallation.objects.select_related("asset", "version__product").filter(
                asset__in=visible_assets(request.user).values("pk")
            ),
            pk=pk,
        )
        data = ReasonSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        row = services.remove_manual(request, row, data.validated_data["reason"])
        return Response(SoftwareInstallationSerializer(row).data)


def _if_match(request):
    raw = request.headers.get("If-Match")
    if raw is None:
        return None
    try:
        return int(raw.strip('"W/ '))
    except ValueError:
        return -1


IF_MATCH = OpenApiParameter("If-Match", str, OpenApiParameter.HEADER, required=True)


def _version_response(request, v):
    v = _versions_for(request.user, v.product).get(pk=v.pk)
    return Response(SoftwareVersionSerializer(v).data, headers={"ETag": f'"{v.lifecycle_version}"'})


class VersionApproveView(APIView):
    permission_classes = [Approve]

    @extend_schema(
        request=VersionApproveSerializer, responses=SoftwareVersionSerializer, parameters=[IF_MATCH]
    )
    def post(self, request, pk):
        v = get_object_or_404(SoftwareVersion.objects.select_related("product"), pk=pk)
        data = VersionApproveSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        product = get_object_or_404(
            LifecycleProduct, pk=data.validated_data["product"], is_active=True
        )
        v = services.approve_version(
            request,
            v,
            product,
            data.validated_data["remember_alias"],
            data.validated_data["note"],
            _if_match(request),
        )
        return _version_response(request, v)


class VersionRejectView(APIView):
    permission_classes = [Approve]

    @extend_schema(
        request=VersionRejectSerializer, responses=SoftwareVersionSerializer, parameters=[IF_MATCH]
    )
    def post(self, request, pk):
        v = get_object_or_404(SoftwareVersion.objects.select_related("product"), pk=pk)
        data = VersionRejectSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        v = services.reject_version(request, v, data.validated_data["note"], _if_match(request))
        return _version_response(request, v)
