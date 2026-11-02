from django.shortcuts import get_object_or_404
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import generics, serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts import catalog
from apps.accounts.permissions import HasPermission, ReadAnyWritePermission
from config.api import ItemsCursorPagination

from . import custom_fields as cf
from . import selectors, services
from .models import AssetCategory, AssetHistoryEntry, CustomFieldDefinition
from .serializers import (
    AssetCategorySerializer,
    AssetCategoryWriteSerializer,
    AssetDetailSerializer,
    AssetHistorySerializer,
    AssetListSerializer,
    AssetWriteSerializer,
    ClassificationImpactSerializer,
    ClassificationPreviewSerializer,
    ClassificationSerializer,
    CustomFieldCreateSerializer,
    CustomFieldDefinitionSerializer,
    CustomFieldUpdateSerializer,
    ReasonSerializer,
)
from .tree import CategoryTree

IF_MATCH = OpenApiParameter("If-Match", str, OpenApiParameter.HEADER, required=True)


def _if_match(request) -> int | None:
    raw = request.headers.get("If-Match")
    if raw is None:
        return None
    try:
        return int(raw.strip('"W/ '))
    except ValueError:
        return -1


def _etag(obj) -> dict:
    return {"ETag": f'"{obj.version}"'}


# --- Assets -------------------------------------------------------------------


class AssetPagination(ItemsCursorPagination):
    ordering = selectors.ORDERING["-modified_at"]


@extend_schema(
    parameters=[
        OpenApiParameter(
            "q",
            str,
            description="Name, tag, serial, manufacturer, model, hostname, exact IP or MAC",
        ),
        OpenApiParameter("category", str, description="Category ID (includes subcategories)"),
        OpenApiParameter("site", str, description="Site ID (includes child sites)"),
        OpenApiParameter("location", str),
        OpenApiParameter("department", str),
        OpenApiParameter("owner", str),
        OpenApiParameter("manufacturer", str, description="Exact, case-insensitive"),
        OpenApiParameter("business_status", str),
        OpenApiParameter("observation_status", str),
        OpenApiParameter("support_status", str),
        OpenApiParameter("archived", str, enum=list(selectors.ARCHIVED_MODES)),
        OpenApiParameter("ordering", str, enum=list(selectors.ORDERING)),
    ]
)
class AssetListCreateView(generics.ListAPIView):
    serializer_class = AssetListSerializer
    pagination_class = AssetPagination
    permission_classes = [ReadAnyWritePermission((catalog.ASSETS_VIEW,), catalog.ASSETS_CREATE)]

    def get_serializer_context(self):
        return {**super().get_serializer_context(), "tree": self.tree}

    def get_queryset(self):
        self.tree = CategoryTree()
        qs = selectors.visible_assets(self.request.user)
        return selectors.apply_filters(qs, self.request.query_params, self.tree)

    def paginate_queryset(self, queryset):
        ordering = self.request.query_params.get("ordering", "-modified_at")
        self.paginator.ordering = selectors.ORDERING.get(
            ordering, selectors.ORDERING["-modified_at"]
        )
        return super().paginate_queryset(queryset)

    @extend_schema(request=AssetWriteSerializer, responses={201: AssetDetailSerializer})
    def post(self, request):
        data = AssetWriteSerializer(data=request.data, context={"request": request})
        data.is_valid(raise_exception=True)
        asset = services.create_asset(request, data.validated_data)
        asset = selectors.visible_assets(request.user).get(pk=asset.pk)
        return Response(
            AssetDetailSerializer(asset, context={"request": request}).data,
            status=status.HTTP_201_CREATED,
            headers=_etag(asset),
        )


class _AssetMixin:
    def get_asset(self, request, pk):
        return get_object_or_404(selectors.visible_assets(request.user), pk=pk)

    def detail(self, request, asset, **kwargs):
        asset = (
            selectors.visible_assets(request.user)
            .prefetch_related("hostnames", "interfaces", "ip_addresses__interface")
            .get(pk=asset.pk)
        )
        return Response(
            AssetDetailSerializer(asset, context={"request": request}).data,
            headers=_etag(asset),
            **kwargs,
        )


class AssetDetailView(_AssetMixin, APIView):
    permission_classes = [ReadAnyWritePermission((catalog.ASSETS_VIEW,), catalog.ASSETS_EDIT)]

    @extend_schema(responses=AssetDetailSerializer)
    def get(self, request, pk):
        return self.detail(request, self.get_asset(request, pk))

    @extend_schema(
        request=AssetWriteSerializer(partial=True),
        responses=AssetDetailSerializer,
        parameters=[IF_MATCH],
    )
    def patch(self, request, pk):
        asset = self.get_asset(request, pk)
        if "category" in request.data:
            raise serializers.ValidationError(
                {"category": ["Use the classification endpoint to change the category."]}
            )
        data = AssetWriteSerializer(
            asset, data=request.data, partial=True, context={"request": request}
        )
        data.is_valid(raise_exception=True)
        asset = services.update_asset(request, asset, data.validated_data, _if_match(request))
        return self.detail(request, asset)


class AssetClassificationPreviewView(_AssetMixin, APIView):
    permission_classes = [HasPermission(catalog.ASSETS_RECLASSIFY)]

    @extend_schema(
        request=ClassificationPreviewSerializer,
        responses=ClassificationImpactSerializer,
        description=(
            "Shows which custom fields a category change adds, keeps or retains. Changes nothing."
        ),
    )
    def post(self, request, pk):
        asset = self.get_asset(request, pk)
        data = ClassificationPreviewSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        values = data.validated_data
        impact = services.classification_impact(
            asset, values["category"], values.get("custom_fields")
        )
        return Response(ClassificationImpactSerializer(impact).data)


class AssetClassificationView(_AssetMixin, APIView):
    permission_classes = [HasPermission(catalog.ASSETS_RECLASSIFY)]

    @extend_schema(
        request=ClassificationSerializer, responses=AssetDetailSerializer, parameters=[IF_MATCH]
    )
    def post(self, request, pk):
        asset = self.get_asset(request, pk)
        data = ClassificationSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        values = data.validated_data
        asset = services.reclassify(
            request,
            asset,
            values["category"],
            values["reason"].strip(),
            values.get("custom_fields"),
            _if_match(request),
        )
        return self.detail(request, asset)


class AssetArchiveView(_AssetMixin, APIView):
    permission_classes = [HasPermission(catalog.ASSETS_ARCHIVE)]

    @extend_schema(request=ReasonSerializer, responses=AssetDetailSerializer, parameters=[IF_MATCH])
    def post(self, request, pk):
        asset = self.get_asset(request, pk)
        data = ReasonSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        asset = services.archive(
            request, asset, data.validated_data["reason"].strip(), _if_match(request)
        )
        return self.detail(request, asset)


class AssetRestoreView(_AssetMixin, APIView):
    permission_classes = [HasPermission(catalog.ASSETS_ARCHIVE)]

    @extend_schema(request=None, responses=AssetDetailSerializer, parameters=[IF_MATCH])
    def post(self, request, pk):
        asset = services.restore(request, self.get_asset(request, pk), _if_match(request))
        return self.detail(request, asset)


class HistoryPagination(ItemsCursorPagination):
    ordering = ("-occurred_at", "-id")


class AssetHistoryView(_AssetMixin, generics.ListAPIView):
    serializer_class = AssetHistorySerializer
    pagination_class = HistoryPagination
    permission_classes = [HasPermission(catalog.ASSETS_VIEW)]

    def get_queryset(self):
        asset = self.get_asset(self.request, self.kwargs["pk"])
        return AssetHistoryEntry.objects.filter(asset=asset)


# --- Categories and fields ----------------------------------------------------

CategoryPermission = ReadAnyWritePermission(
    (catalog.ASSETS_VIEW, catalog.CATEGORIES_MANAGE), catalog.CATEGORIES_MANAGE
)


class CategoryListCreateView(APIView):
    permission_classes = [CategoryPermission]

    @extend_schema(responses=AssetCategorySerializer(many=True))
    def get(self, request):
        tree = CategoryTree()
        ordered = []

        def walk(parent_id):
            children = sorted(
                (tree.by_id[c] for c in tree.children.get(parent_id, [])),
                key=lambda c: (c.sort_order, c.name.lower()),
            )
            for child in children:
                ordered.append(child)
                walk(child.pk)

        walk(None)
        return Response(AssetCategorySerializer(ordered, many=True, context={"tree": tree}).data)

    @extend_schema(request=AssetCategoryWriteSerializer, responses={201: AssetCategorySerializer})
    def post(self, request):
        data = AssetCategoryWriteSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        category = services.create_category(request, data.validated_data)
        return Response(
            AssetCategorySerializer(category, context={}).data, status=status.HTTP_201_CREATED
        )


class CategoryDetailView(APIView):
    permission_classes = [CategoryPermission]

    @extend_schema(responses=AssetCategorySerializer)
    def get(self, request, pk):
        category = get_object_or_404(AssetCategory, pk=pk)
        return Response(AssetCategorySerializer(category, context={}).data, headers=_etag(category))

    @extend_schema(
        request=AssetCategoryWriteSerializer(partial=True),
        responses=AssetCategorySerializer,
        parameters=[IF_MATCH],
    )
    def patch(self, request, pk):
        category = get_object_or_404(AssetCategory, pk=pk)
        data = AssetCategoryWriteSerializer(category, data=request.data, partial=True)
        data.is_valid(raise_exception=True)
        category = services.update_category(
            request, category, data.validated_data, _if_match(request)
        )
        return Response(AssetCategorySerializer(category, context={}).data, headers=_etag(category))


@extend_schema(
    parameters=[
        OpenApiParameter(
            "effective",
            bool,
            description="true: fields that apply to this category, including inherited ones",
        )
    ]
)
class CategoryFieldListCreateView(APIView):
    permission_classes = [CategoryPermission]

    @extend_schema(responses=CustomFieldDefinitionSerializer(many=True))
    def get(self, request, pk):
        category = get_object_or_404(AssetCategory, pk=pk)
        if request.query_params.get("effective") == "true":
            definitions = cf.applicable_definitions(category.pk)
        else:
            definitions = category.field_definitions.all()
        return Response(CustomFieldDefinitionSerializer(definitions, many=True).data)

    @extend_schema(
        request=CustomFieldCreateSerializer, responses={201: CustomFieldDefinitionSerializer}
    )
    def post(self, request, pk):
        category = get_object_or_404(AssetCategory, pk=pk)
        data = CustomFieldCreateSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        definition = services.create_field(request, category, data.validated_data)
        return Response(
            CustomFieldDefinitionSerializer(definition).data, status=status.HTTP_201_CREATED
        )


class CustomFieldDetailView(APIView):
    permission_classes = [CategoryPermission]

    @extend_schema(
        request=CustomFieldUpdateSerializer,
        responses=CustomFieldDefinitionSerializer,
        parameters=[IF_MATCH],
    )
    def patch(self, request, pk):
        definition = get_object_or_404(CustomFieldDefinition, pk=pk)
        data = CustomFieldUpdateSerializer(data=request.data, partial=True)
        data.is_valid(raise_exception=True)
        definition = services.update_field(
            request, definition, data.validated_data, _if_match(request)
        )
        return Response(CustomFieldDefinitionSerializer(definition).data, headers=_etag(definition))
