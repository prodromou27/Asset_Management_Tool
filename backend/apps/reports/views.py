from django.db import transaction
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import serializers
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import HasPermission
from apps.audit import services as audit
from config.api import require_if_match

from . import services
from .models import DigestSchedule


class ReportColumnSerializer(serializers.Serializer):
    key = serializers.CharField()
    label = serializers.CharField()


class ReportSerializer(serializers.Serializer):
    report = serializers.CharField()
    label = serializers.CharField()
    note = serializers.CharField()
    generated_at = serializers.DateTimeField()
    count = serializers.IntegerField()
    columns = ReportColumnSerializer(many=True)
    rows = serializers.ListField(child=serializers.DictField(child=serializers.JSONField()))
    offset = serializers.IntegerField()
    limit = serializers.IntegerField()


class PageSerializer(serializers.Serializer):
    offset = serializers.IntegerField(min_value=0, max_value=100000, default=0)
    limit = serializers.IntegerField(min_value=1, max_value=100, default=50)


class ReportView(APIView):
    permission_classes = [HasPermission("reports.view")]

    @extend_schema(parameters=[services.ReportFilters, PageSerializer], responses=ReportSerializer)
    def get(self, request, kind):
        values = request.query_params.dict()
        page = PageSerializer(
            data={key: values.pop(key) for key in ("offset", "limit") if key in values}
        )
        page.is_valid(raise_exception=True)
        data = services.preview(request.user, kind, values, **page.validated_data)
        return Response(ReportSerializer(data).data, headers={"Cache-Control": "no-store"})


class ScheduleSerializer(serializers.ModelSerializer):
    hour_utc = serializers.IntegerField(min_value=0, max_value=23)
    weekday = serializers.IntegerField(min_value=0, max_value=6)
    filters = serializers.DictField(child=serializers.CharField(), required=False)

    class Meta:
        model = DigestSchedule
        fields = [
            "id",
            "report",
            "filters",
            "enabled",
            "hour_utc",
            "cadence",
            "weekday",
            "version",
            "created_at",
            "modified_at",
        ]
        read_only_fields = ["id", "version", "created_at", "modified_at"]

    def validate(self, attrs):
        unknown = set(self.initial_data) - {
            "report",
            "filters",
            "enabled",
            "hour_utc",
            "cadence",
            "weekday",
        }
        if unknown:
            raise serializers.ValidationError(
                "Only your own report, filters and schedule can be changed."
            )
        if self.instance and attrs == {"enabled": False}:
            return attrs
        kind = attrs.get("report", self.instance.report if self.instance else "")
        filters = attrs.get("filters", self.instance.filters if self.instance else {})
        attrs["filters"] = services.clean_filters(self.context["request"].user, kind, filters)
        if (
            attrs.get("enabled", self.instance.enabled if self.instance else False)
            and not self.context["request"].user.email
        ):
            raise serializers.ValidationError(
                "Your account needs an administrator-configured email address."
            )
        return attrs


class ScheduleListView(APIView):
    permission_classes = [HasPermission("reports.view", "reports.schedule")]

    @extend_schema(responses=ScheduleSerializer(many=True))
    def get(self, request):
        return Response(
            ScheduleSerializer(
                DigestSchedule.objects.filter(owner=request.user).order_by("created_at"), many=True
            ).data
        )

    @extend_schema(request=ScheduleSerializer, responses={201: ScheduleSerializer})
    def post(self, request):
        if DigestSchedule.objects.filter(owner=request.user).count() >= 20:
            raise serializers.ValidationError("At most 20 schedules per account.")
        data = ScheduleSerializer(data=request.data, context={"request": request})
        data.is_valid(raise_exception=True)
        with transaction.atomic():
            obj = data.save(owner=request.user)
            audit.record(
                action="reports.schedule_create",
                actor=request.user,
                request=request,
                object_type="report_schedule",
                object_id=obj.pk,
                after=dict(data.data),
            )
        return Response(ScheduleSerializer(obj).data, status=201)


class ScheduleDetailView(APIView):
    permission_classes = [HasPermission("reports.view", "reports.schedule")]

    @extend_schema(responses=ScheduleSerializer)
    def get(self, request, pk):
        obj = get_object_or_404(DigestSchedule, pk=pk, owner=request.user)
        return Response(ScheduleSerializer(obj).data)

    @extend_schema(
        request=ScheduleSerializer,
        responses=ScheduleSerializer,
        parameters=[OpenApiParameter("If-Match", str, OpenApiParameter.HEADER, required=True)],
    )
    def patch(self, request, pk):
        with transaction.atomic():
            obj = get_object_or_404(
                DigestSchedule.objects.select_for_update(), pk=pk, owner=request.user
            )
            require_if_match(request, obj.version)
            before = dict(ScheduleSerializer(obj).data)
            data = ScheduleSerializer(
                obj, data=request.data, partial=True, context={"request": request}
            )
            data.is_valid(raise_exception=True)
            obj = data.save(version=obj.version + 1)
            audit.record(
                action="reports.schedule_update",
                actor=request.user,
                request=request,
                object_type="report_schedule",
                object_id=obj.pk,
                before=before,
                after=dict(data.data),
            )
        return Response(ScheduleSerializer(obj).data)
