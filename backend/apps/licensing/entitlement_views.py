"""License products, entitlements and allocations API (Task 016b, docs/04
/licenses/products, /licenses/entitlements).

Reading needs ``licenses.view``; changes need ``licenses.manage``. Entitlements are
organisation-wide. Allocations to assets are listed only for assets in the reader's sites
(totals still count every allocation, as a number). Allocating to an asset needs the asset
to be in the caller's sites.
"""

import uuid
from datetime import timedelta

from django.db.models import Count, Q
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_field
from rest_framework import generics, serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts import catalog
from apps.accounts.permissions import HasPermission
from apps.assets.selectors import visible_assets
from apps.assets.serializers import ReasonSerializer
from apps.lifecycle.services import today_utc
from apps.software.models import SoftwareProduct
from apps.software.selectors import visible_installations
from config.api import ItemsCursorPagination

from . import entitlements as services
from .models import EntitlementAllocation, LicenseEntitlement, LicenseProduct

View = HasPermission(catalog.LICENSES_VIEW)
Manage = HasPermission(catalog.LICENSES_VIEW, catalog.LICENSES_MANAGE)


def _if_match(request):
    raw = request.headers.get("If-Match")
    if raw is None:
        return None
    try:
        return int(raw.strip('"W/ '))
    except ValueError:
        return -1


IF_MATCH = OpenApiParameter("If-Match", str, OpenApiParameter.HEADER, required=True)


def _etag(obj) -> dict:
    return {"ETag": f'"{obj.version}"'}


# --- Serializers ------------------------------------------------------------------------------


class LicenseSoftwareRefSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    publisher = serializers.CharField()
    name = serializers.CharField()


class LicenseProductSerializer(serializers.ModelSerializer):
    software_product = serializers.SerializerMethodField()
    purchased = serializers.SerializerMethodField(
        help_text="Units of entitlements in term (not retired, started, not ended)"
    )
    allocated = serializers.SerializerMethodField(
        help_text="Units allocated from entitlements in term (all sites)"
    )
    available = serializers.SerializerMethodField(
        help_text="Purchased minus allocated; negative when more is allocated than purchased"
    )
    entitlements_in_term = serializers.SerializerMethodField()
    observed_assets = serializers.SerializerMethodField(
        help_text="Assets in your sites with the linked software installed; null when not linked"
    )

    class Meta:
        model = LicenseProduct
        fields = [
            "id",
            "publisher",
            "name",
            "sku",
            "metric",
            "software_product",
            "note",
            "is_active",
            "purchased",
            "allocated",
            "available",
            "entitlements_in_term",
            "observed_assets",
            "version",
            "modified_at",
        ]
        read_only_fields = fields

    def _totals(self, obj) -> services.Totals:
        return self.context["totals"].get(obj.pk) or services.Totals()

    @extend_schema_field(LicenseSoftwareRefSerializer(allow_null=True))
    def get_software_product(self, obj):
        p = obj.software_product
        return {"id": p.pk, "publisher": p.publisher, "name": p.name} if p else None

    def get_purchased(self, obj) -> int:
        return self._totals(obj).purchased

    def get_allocated(self, obj) -> int:
        return self._totals(obj).allocated

    def get_available(self, obj) -> int:
        return self._totals(obj).available

    def get_entitlements_in_term(self, obj) -> int:
        return self._totals(obj).entitlements_in_term

    def get_observed_assets(self, obj) -> int | None:
        if obj.software_product_id is None:
            return None
        return self.context["observed"].get(obj.software_product_id, 0)


class LicenseProductWriteSerializer(serializers.Serializer):
    publisher = serializers.CharField(max_length=200, allow_blank=True, required=False)
    name = serializers.CharField(max_length=200)
    sku = serializers.CharField(max_length=120, allow_blank=True, required=False)
    metric = serializers.ChoiceField(choices=LicenseProduct.Metric.choices, required=False)
    software_product = serializers.PrimaryKeyRelatedField(
        queryset=SoftwareProduct.objects.all(), allow_null=True, required=False
    )
    note = serializers.CharField(max_length=2000, allow_blank=True, required=False)
    is_active = serializers.BooleanField(required=False)

    def validate(self, attrs):
        for f in ("publisher", "name", "sku"):
            if f in attrs:
                attrs[f] = " ".join(attrs[f].split())
        if "name" in attrs and not attrs["name"]:
            raise serializers.ValidationError({"name": ["Required."]})
        return attrs


class LicenseProductRefSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    label = serializers.CharField()
    metric = serializers.CharField()


class LicenseEntitlementSerializer(serializers.ModelSerializer):
    product = serializers.SerializerMethodField()
    status = serializers.SerializerMethodField()
    allocated = serializers.SerializerMethodField(help_text="Units in open allocations")
    available = serializers.SerializerMethodField(help_text="Quantity minus allocated")
    created_by = serializers.SlugRelatedField(
        read_only=True, allow_null=True, slug_field="username"
    )
    retired_by = serializers.SlugRelatedField(
        read_only=True, allow_null=True, slug_field="username"
    )

    class Meta:
        model = LicenseEntitlement
        fields = [
            "id",
            "product",
            "reference",
            "quantity",
            "starts_on",
            "ends_on",
            "supplier",
            "owner",
            "note",
            "source",
            "status",
            "allocated",
            "available",
            "retired_at",
            "retired_by",
            "retired_reason",
            "version",
            "created_by",
            "created_at",
            "modified_at",
        ]
        read_only_fields = fields

    @extend_schema_field(LicenseProductRefSerializer)
    def get_product(self, obj):
        return {"id": obj.product_id, "label": str(obj.product), "metric": obj.product.metric}

    @extend_schema_field(
        serializers.ChoiceField(choices=["active", "not_started", "expired", "retired"])
    )
    def get_status(self, obj) -> str:
        return obj.status(self.context.get("today") or today_utc())

    def get_allocated(self, obj) -> int:
        return self.context.get("allocated", {}).get(obj.pk, 0)

    def get_available(self, obj) -> int:
        return obj.quantity - self.get_allocated(obj)


class LicenseEntitlementWriteSerializer(serializers.Serializer):
    product = serializers.PrimaryKeyRelatedField(
        queryset=LicenseProduct.objects.all(), required=False
    )
    reference = serializers.CharField(max_length=120)
    quantity = serializers.IntegerField(min_value=1, max_value=10_000_000)
    starts_on = serializers.DateField(allow_null=True, required=False)
    ends_on = serializers.DateField(allow_null=True, required=False)
    supplier = serializers.CharField(max_length=200, allow_blank=True, required=False)
    owner = serializers.CharField(max_length=200, allow_blank=True, required=False)
    note = serializers.CharField(max_length=2000, allow_blank=True, required=False)
    reason = serializers.CharField(max_length=500, allow_blank=True, required=False)

    def validate_reference(self, value):
        value = " ".join(value.split())
        if not value:
            raise serializers.ValidationError("Required.")
        return value


class LicenseAssetRefSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField()
    site_code = serializers.CharField()


class LicenseEntitlementRefSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    reference = serializers.CharField()
    product_id = serializers.UUIDField()
    product_label = serializers.CharField()


class LicenseEntitlementAllocationSerializer(serializers.ModelSerializer):
    entitlement = serializers.SerializerMethodField()
    target = serializers.CharField(read_only=True)
    asset = serializers.SerializerMethodField()
    allocated_by = serializers.SlugRelatedField(
        read_only=True, allow_null=True, slug_field="username"
    )
    ended_by = serializers.SlugRelatedField(read_only=True, allow_null=True, slug_field="username")

    class Meta:
        model = EntitlementAllocation
        fields = [
            "id",
            "entitlement",
            "target",
            "asset",
            "user_name",
            "units",
            "note",
            "allocated_at",
            "allocated_by",
            "ended_at",
            "ended_by",
            "ended_reason",
        ]
        read_only_fields = fields

    @extend_schema_field(LicenseEntitlementRefSerializer)
    def get_entitlement(self, obj):
        e = obj.entitlement
        return {
            "id": e.pk,
            "reference": e.reference,
            "product_id": e.product_id,
            "product_label": str(e.product),
        }

    @extend_schema_field(LicenseAssetRefSerializer(allow_null=True))
    def get_asset(self, obj):
        a = obj.asset
        return {"id": a.pk, "name": a.name, "site_code": a.site.code} if a else None


class LicenseAllocateSerializer(serializers.Serializer):
    asset = serializers.UUIDField(required=False, allow_null=True)
    user_name = serializers.CharField(max_length=320, allow_blank=True, required=False)
    units = serializers.IntegerField(min_value=1, max_value=1_000_000, required=False)
    note = serializers.CharField(max_length=500, allow_blank=True, required=False)


class LicenseProductDetailSerializer(LicenseProductSerializer):
    entitlements = LicenseEntitlementSerializer(many=True, read_only=True)

    class Meta(LicenseProductSerializer.Meta):
        fields = [*LicenseProductSerializer.Meta.fields, "entitlements"]
        read_only_fields = fields


# --- Helpers ----------------------------------------------------------------------------------


def _observed(user, software_ids) -> dict:
    """Distinct assets in the user's sites with any version of each software product."""
    ids = [i for i in software_ids if i]
    if not ids:
        return {}
    rows = (
        visible_installations(user)
        .filter(version__product_id__in=ids)
        .values("version__product_id")
        .annotate(n=Count("resolved_asset_id", distinct=True))
    )
    return {r["version__product_id"]: r["n"] for r in rows}


def _product_context(user, products) -> dict:
    products = list(products)
    return {
        "totals": services.totals_for([p.pk for p in products]),
        "observed": _observed(user, {p.software_product_id for p in products}),
    }


def _entitlement_context(entitlements) -> dict:
    return {
        "today": today_utc(),
        "allocated": services.allocated_units([e.pk for e in entitlements]),
    }


def _product_detail(request, product, headers=None):
    product = LicenseProduct.objects.select_related("software_product").get(pk=product.pk)
    ents = list(
        product.entitlements.select_related("product", "created_by", "retired_by").order_by(
            "retired_at", "-ends_on", "reference"
        )
    )
    data = LicenseProductSerializer(product, context=_product_context(request.user, [product])).data
    data["entitlements"] = LicenseEntitlementSerializer(
        ents, many=True, context=_entitlement_context(ents)
    ).data
    return Response(data, headers=headers or _etag(product))


def _uuid(value):
    try:
        return uuid.UUID(str(value))
    except ValueError:
        return None


# --- Products ---------------------------------------------------------------------------------


class ProductPagination(ItemsCursorPagination):
    ordering = ("name", "publisher", "id")


class LicenseProductListView(generics.ListCreateAPIView):
    serializer_class = LicenseProductSerializer
    pagination_class = ProductPagination

    def get_permissions(self):
        return [(Manage if self.request.method == "POST" else View)()]

    @extend_schema(
        parameters=[
            OpenApiParameter("q", str, description="Publisher, name or SKU"),
            OpenApiParameter("include_inactive", bool),
        ]
    )
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

    def get_queryset(self):
        params = self.request.query_params
        qs = LicenseProduct.objects.select_related("software_product")
        if params.get("include_inactive") not in ("true", "1"):
            qs = qs.filter(is_active=True)
        if q := params.get("q", "").strip()[:100]:
            qs = qs.filter(Q(name__icontains=q) | Q(publisher__icontains=q) | Q(sku__icontains=q))
        return qs

    def list(self, request, *args, **kwargs):
        page = self.paginate_queryset(self.get_queryset())
        data = LicenseProductSerializer(
            page, many=True, context=_product_context(request.user, page)
        ).data
        return self.get_paginated_response(data)

    @extend_schema(
        request=LicenseProductWriteSerializer, responses={201: LicenseProductDetailSerializer}
    )
    def post(self, request, *args, **kwargs):
        data = LicenseProductWriteSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        product = services.create_product(request, data.validated_data)
        response = _product_detail(request, product)
        response.status_code = status.HTTP_201_CREATED
        return response


class LicenseProductDetailView(APIView):
    def get_permissions(self):
        return [(Manage if self.request.method == "PATCH" else View)()]

    @extend_schema(responses=LicenseProductDetailSerializer)
    def get(self, request, pk):
        return _product_detail(request, get_object_or_404(LicenseProduct, pk=pk))

    @extend_schema(
        request=LicenseProductWriteSerializer,
        responses=LicenseProductDetailSerializer,
        parameters=[IF_MATCH],
    )
    def patch(self, request, pk):
        product = get_object_or_404(LicenseProduct, pk=pk)
        data = LicenseProductWriteSerializer(data=request.data, partial=True)
        data.is_valid(raise_exception=True)
        product = services.update_product(request, product, data.validated_data, _if_match(request))
        return _product_detail(request, product)


# --- Entitlements -----------------------------------------------------------------------------


class EntitlementPagination(ItemsCursorPagination):
    ordering = ("-created_at", "-id")


STATUS_FILTERS = ("active", "not_started", "expired", "retired", "ending")


class LicenseEntitlementListView(generics.ListCreateAPIView):
    serializer_class = LicenseEntitlementSerializer
    pagination_class = EntitlementPagination

    def get_permissions(self):
        return [(Manage if self.request.method == "POST" else View)()]

    @extend_schema(
        parameters=[
            OpenApiParameter("product", str, description="License product ID"),
            OpenApiParameter("q", str, description="Reference, product, supplier or owner"),
            OpenApiParameter(
                "status",
                str,
                enum=list(STATUS_FILTERS),
                description="ending: in term and ending within 90 days",
            ),
        ]
    )
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

    def get_queryset(self):
        params = self.request.query_params
        today = today_utc()
        qs = LicenseEntitlement.objects.select_related("product", "created_by", "retired_by")
        if product := params.get("product"):
            qs = qs.filter(product_id=_uuid(product)) if _uuid(product) else qs.none()
        if q := params.get("q", "").strip()[:100]:
            qs = qs.filter(
                Q(reference__icontains=q)
                | Q(product__name__icontains=q)
                | Q(product__publisher__icontains=q)
                | Q(supplier__icontains=q)
                | Q(owner__icontains=q)
            )
        state = params.get("status")
        if state == "retired":
            qs = qs.filter(retired_at__isnull=False)
        elif state == "active":
            qs = qs.filter(services.in_term_q(today))
        elif state == "ending":
            qs = qs.filter(services.in_term_q(today), ends_on__lte=today + timedelta(days=90))
        elif state == "expired":
            qs = qs.filter(retired_at__isnull=True, ends_on__lt=today)
        elif state == "not_started":
            qs = qs.filter(retired_at__isnull=True, starts_on__gt=today)
        return qs

    def list(self, request, *args, **kwargs):
        page = self.paginate_queryset(self.get_queryset())
        data = LicenseEntitlementSerializer(
            page, many=True, context=_entitlement_context(page)
        ).data
        return self.get_paginated_response(data)

    @extend_schema(
        request=LicenseEntitlementWriteSerializer, responses={201: LicenseEntitlementSerializer}
    )
    def post(self, request, *args, **kwargs):
        data = LicenseEntitlementWriteSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        values = dict(data.validated_data)
        product = values.pop("product", None)
        if product is None:
            raise serializers.ValidationError({"product": ["Required."]})
        values.pop("reason", None)
        entitlement = services.create_entitlement(request, product, values)
        return _entitlement_response(entitlement, status.HTTP_201_CREATED)


def _entitlement_response(entitlement, http_status=status.HTTP_200_OK):
    entitlement = LicenseEntitlement.objects.select_related(
        "product", "created_by", "retired_by"
    ).get(pk=entitlement.pk)
    data = LicenseEntitlementSerializer(
        entitlement, context=_entitlement_context([entitlement])
    ).data
    return Response(data, status=http_status, headers=_etag(entitlement))


class LicenseEntitlementDetailView(APIView):
    def get_permissions(self):
        return [(Manage if self.request.method == "PATCH" else View)()]

    @extend_schema(responses=LicenseEntitlementSerializer)
    def get(self, request, pk):
        return _entitlement_response(get_object_or_404(LicenseEntitlement, pk=pk))

    @extend_schema(
        request=LicenseEntitlementWriteSerializer,
        responses=LicenseEntitlementSerializer,
        parameters=[IF_MATCH],
    )
    def patch(self, request, pk):
        entitlement = get_object_or_404(LicenseEntitlement, pk=pk)
        data = LicenseEntitlementWriteSerializer(data=request.data, partial=True)
        data.is_valid(raise_exception=True)
        values = dict(data.validated_data)
        values.pop("product", None)  # an entitlement stays with its product
        entitlement = services.update_entitlement(request, entitlement, values, _if_match(request))
        return _entitlement_response(entitlement)


class LicenseEntitlementRetireView(APIView):
    permission_classes = [Manage]

    @extend_schema(
        request=ReasonSerializer, responses=LicenseEntitlementSerializer, parameters=[IF_MATCH]
    )
    def post(self, request, pk):
        entitlement = get_object_or_404(LicenseEntitlement, pk=pk)
        data = ReasonSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        entitlement = services.retire_entitlement(
            request, entitlement, data.validated_data["reason"], _if_match(request)
        )
        return _entitlement_response(entitlement)


# --- Allocations ------------------------------------------------------------------------------


class AllocationPagination(ItemsCursorPagination):
    ordering = ("-allocated_at", "-id")


class LicenseEntitlementAllocationListView(generics.ListAPIView):
    serializer_class = LicenseEntitlementAllocationSerializer
    pagination_class = AllocationPagination
    permission_classes = [View]

    @extend_schema(
        parameters=[
            OpenApiParameter("entitlement", str),
            OpenApiParameter("product", str, description="License product ID"),
            OpenApiParameter("asset", str),
            OpenApiParameter("target", str, enum=["asset", "user"]),
            OpenApiParameter("q", str, description="Asset name, user, product or reference"),
            OpenApiParameter("include_ended", bool),
        ]
    )
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

    def get_queryset(self):
        params = self.request.query_params
        rows = services.visible_allocations(self.request.user)
        if params.get("include_ended") not in ("true", "1"):
            rows = rows.filter(ended_at__isnull=True)
        for name, field in (
            ("entitlement", "entitlement_id"),
            ("product", "entitlement__product_id"),
            ("asset", "asset_id"),
        ):
            if value := params.get(name):
                ident = _uuid(value)
                rows = rows.filter(**{field: ident}) if ident else rows.none()
        if params.get("target") == "asset":
            rows = rows.filter(asset__isnull=False)
        elif params.get("target") == "user":
            rows = rows.filter(asset__isnull=True)
        if q := params.get("q", "").strip()[:100]:
            rows = rows.filter(
                Q(asset__name__icontains=q)
                | Q(user_name__icontains=q)
                | Q(entitlement__reference__icontains=q)
                | Q(entitlement__product__name__icontains=q)
            )
        return rows


class LicenseAllocateView(APIView):
    permission_classes = [Manage]

    @extend_schema(
        request=LicenseAllocateSerializer, responses={201: LicenseEntitlementAllocationSerializer}
    )
    def post(self, request, pk):
        entitlement = get_object_or_404(LicenseEntitlement.objects.select_related("product"), pk=pk)
        data = LicenseAllocateSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        values = dict(data.validated_data)
        if values.get("asset"):
            values["asset"] = get_object_or_404(
                visible_assets(request.user).filter(archived_at__isnull=True), pk=values["asset"]
            )
        row = services.allocate(request, entitlement, values)
        row = services.visible_allocations(request.user).get(pk=row.pk)
        return Response(
            LicenseEntitlementAllocationSerializer(row).data, status=status.HTTP_201_CREATED
        )


class LicenseAllocationEndView(APIView):
    permission_classes = [Manage]

    @extend_schema(request=ReasonSerializer, responses=LicenseEntitlementAllocationSerializer)
    def post(self, request, pk):
        row = get_object_or_404(services.visible_allocations(request.user), pk=pk)
        data = ReasonSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        services.end_allocation(request, row, data.validated_data["reason"])
        row = services.visible_allocations(request.user).get(pk=row.pk)
        return Response(LicenseEntitlementAllocationSerializer(row).data)
