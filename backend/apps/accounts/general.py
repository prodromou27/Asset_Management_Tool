"""Validated nonsecret organization settings using the existing RBAC/audit boundary."""

from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.db import transaction
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import serializers
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.audit import services as audit
from config.api import require_if_match

from .models import GeneralSettings
from .permissions import HasMethodPermission

DISPLAY_FIELDS = ("organization_name", "timezone", "date_format", "language", "support_contact")


class DisplayPreferencesSerializer(serializers.ModelSerializer):
    class Meta:
        model = GeneralSettings
        fields = DISPLAY_FIELDS
        read_only_fields = DISPLAY_FIELDS


class GeneralSettingsSerializer(DisplayPreferencesSerializer):
    modified_by = serializers.SlugRelatedField(
        read_only=True, allow_null=True, slug_field="username"
    )

    class Meta(DisplayPreferencesSerializer.Meta):
        fields = [*DISPLAY_FIELDS, "version", "modified_at", "modified_by"]
        read_only_fields = ["version", "modified_at", "modified_by"]
        extra_kwargs = {field: {"required": True} for field in DISPLAY_FIELDS}

    def validate_timezone(self, value):
        try:
            ZoneInfo(value)
        except (ValueError, ZoneInfoNotFoundError):
            raise serializers.ValidationError(
                "Enter a valid IANA timezone, for example Asia/Nicosia."
            ) from None
        return value

    def validate(self, attrs):
        unknown = set(self.initial_data) - set(DISPLAY_FIELDS)
        if unknown:
            raise serializers.ValidationError(
                {key: ["This setting cannot be changed here."] for key in sorted(unknown)}
            )
        return attrs


class GeneralSettingsView(APIView):
    permission_classes = [HasMethodPermission("settings.general.view", "settings.general.manage")]

    @extend_schema(responses=GeneralSettingsSerializer)
    def get(self, request):
        obj = GeneralSettings.load()
        return Response(GeneralSettingsSerializer(obj).data, headers={"ETag": f'"{obj.version}"'})

    @extend_schema(
        request=GeneralSettingsSerializer,
        responses=GeneralSettingsSerializer,
        parameters=[OpenApiParameter("If-Match", str, OpenApiParameter.HEADER, required=True)],
    )
    def patch(self, request):
        GeneralSettings.load()
        with transaction.atomic():
            obj = GeneralSettings.objects.select_for_update().get(pk=1)
            require_if_match(request, obj.version)
            data = GeneralSettingsSerializer(obj, data=request.data, partial=True)
            data.is_valid(raise_exception=True)
            before = DisplayPreferencesSerializer(obj).data
            for field, value in data.validated_data.items():
                setattr(obj, field, value)
            after = DisplayPreferencesSerializer(obj).data
            if before != after:
                obj.version += 1
                obj.modified_by = request.user
                obj.save()
                audit.record(
                    action="settings.general.update",
                    actor=request.user,
                    request=request,
                    object_type="settings",
                    object_id="general",
                    object_label="General settings",
                    before=dict(before),
                    after=dict(after),
                )
        return Response(GeneralSettingsSerializer(obj).data, headers={"ETag": f'"{obj.version}"'})
