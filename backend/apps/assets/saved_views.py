"""Saved inventory views (docs/01 "save view", docs/07 AssetTable saved views).

A view stores only filter parameters, column choices and ordering. It is applied
by the list endpoint, which always starts from visible_assets(user); a shared view
therefore shows each viewer only the assets in their own sites.
"""

from django.db import transaction
from django.db.models import F, Q
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts import catalog
from apps.accounts.permissions import HasPermission
from apps.audit import services as audit
from apps.organizations.services import check_version
from config.api import ApiError

from .models import SavedView
from .selectors import FILTER_KEYS, ORDERING

ASSET_COLUMNS = (
    "name",
    "category",
    "manufacturer_model",
    "serial",
    "primary_ip",
    "site",
    "owner",
    "business_status",
    "observation_status",
    "support_status",
    "last_seen",
    "sources",
    "modified",
)
IF_MATCH = OpenApiParameter("If-Match", str, OpenApiParameter.HEADER, required=True)


class SavedViewSerializer(serializers.ModelSerializer):
    owner = serializers.SlugRelatedField(read_only=True, slug_field="username")
    is_mine = serializers.SerializerMethodField()
    filters = serializers.DictField(child=serializers.CharField(), read_only=True)
    columns = serializers.ListField(child=serializers.CharField(), read_only=True)

    class Meta:
        model = SavedView
        fields = [
            "id",
            "resource",
            "name",
            "is_shared",
            "filters",
            "columns",
            "ordering",
            "owner",
            "is_mine",
            "created_at",
            "modified_at",
            "version",
        ]
        read_only_fields = fields

    def get_is_mine(self, obj) -> bool:
        return obj.owner_id == self.context["request"].user.pk


class SavedViewWriteSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=100)
    is_shared = serializers.BooleanField(required=False)
    filters = serializers.DictField(
        child=serializers.CharField(max_length=200, allow_blank=True), required=False
    )
    columns = serializers.ListField(
        child=serializers.ChoiceField(choices=ASSET_COLUMNS),
        required=False,
        max_length=len(ASSET_COLUMNS),
    )
    ordering = serializers.ChoiceField(choices=["", *ORDERING], required=False)

    def validate_name(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError("Enter a name.")
        return value

    def validate_filters(self, value):
        unknown = sorted(set(value) - set(FILTER_KEYS))
        if unknown:
            raise serializers.ValidationError(f"Unknown filter(s): {', '.join(unknown)}.")
        return {k: v for k, v in value.items() if v != ""}

    def validate_columns(self, value):
        if len(set(value)) != len(value):
            raise serializers.ValidationError("List each column once.")
        if "name" not in value:
            raise serializers.ValidationError("The name column cannot be hidden.")
        return value


def _if_match(request) -> int | None:
    raw = request.headers.get("If-Match")
    if raw is None:
        return None
    try:
        return int(raw.strip('"W/ '))
    except ValueError:
        return -1


def _visible(user):
    return SavedView.objects.select_related("owner").filter(
        Q(owner=user) | Q(is_shared=True), resource=SavedView.Resource.ASSETS
    )


def _check_share(request, data) -> None:
    if data.get("is_shared") and catalog.ASSETS_EDIT not in request.user.permission_codes():
        raise ApiError(
            "PERMISSION_DENIED",
            "Sharing views needs the asset edit permission.",
            status.HTTP_403_FORBIDDEN,
        )


def _check_unique(user, name, exclude=None) -> None:
    clash = SavedView.objects.filter(
        owner=user, resource=SavedView.Resource.ASSETS, name__iexact=name
    )
    if exclude is not None:
        clash = clash.exclude(pk=exclude.pk)
    if clash.exists():
        raise serializers.ValidationError({"name": ["You already have a view with this name."]})


def _snapshot(view) -> dict:
    return {
        "name": view.name,
        "is_shared": view.is_shared,
        "filters": view.filters,
        "columns": view.columns,
        "ordering": view.ordering,
    }


class SavedViewListCreateView(APIView):
    permission_classes = [HasPermission(catalog.ASSETS_VIEW)]

    @extend_schema(responses=SavedViewSerializer(many=True))
    def get(self, request):
        views = _visible(request.user).order_by("-is_shared", "name")
        return Response(SavedViewSerializer(views, many=True, context={"request": request}).data)

    @extend_schema(request=SavedViewWriteSerializer, responses={201: SavedViewSerializer})
    def post(self, request):
        data = SavedViewWriteSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        values = data.validated_data
        _check_share(request, values)
        _check_unique(request.user, values["name"])
        with transaction.atomic():
            view = SavedView.objects.create(owner=request.user, **values)
            audit.record(
                action="saved_views.create",
                actor=request.user,
                request=request,
                object_type="saved_view",
                object_id=view.pk,
                object_label=view.name,
                after=_snapshot(view),
            )
        return Response(
            SavedViewSerializer(view, context={"request": request}).data,
            status=status.HTTP_201_CREATED,
        )


class SavedViewDetailView(APIView):
    permission_classes = [HasPermission(catalog.ASSETS_VIEW)]

    def _own(self, request, pk):
        view = get_object_or_404(_visible(request.user), pk=pk)
        if view.owner_id != request.user.pk:
            raise ApiError(
                "PERMISSION_DENIED",
                "Only the owner can change this view.",
                status.HTTP_403_FORBIDDEN,
            )
        return view

    @extend_schema(
        request=SavedViewWriteSerializer(partial=True),
        responses=SavedViewSerializer,
        parameters=[IF_MATCH],
    )
    def patch(self, request, pk):
        view = self._own(request, pk)
        data = SavedViewWriteSerializer(data=request.data, partial=True)
        data.is_valid(raise_exception=True)
        values = data.validated_data
        _check_share(request, values)
        if "name" in values:
            _check_unique(request.user, values["name"], exclude=view)
        with transaction.atomic():
            view = SavedView.objects.select_for_update().get(pk=view.pk)
            check_version(view, _if_match(request))
            before = _snapshot(view)
            for key, value in values.items():
                setattr(view, key, value)
            if _snapshot(view) != before:
                view.version = F("version") + 1
                view.save()
                view.refresh_from_db()
                audit.record(
                    action="saved_views.update",
                    actor=request.user,
                    request=request,
                    object_type="saved_view",
                    object_id=view.pk,
                    object_label=view.name,
                    before=before,
                    after=_snapshot(view),
                )
        return Response(SavedViewSerializer(view, context={"request": request}).data)

    @extend_schema(responses={204: None})
    def delete(self, request, pk):
        view = self._own(request, pk)
        with transaction.atomic():
            audit.record(
                action="saved_views.delete",
                actor=request.user,
                request=request,
                object_type="saved_view",
                object_id=view.pk,
                object_label=view.name,
                before=_snapshot(view),
            )
            view.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
