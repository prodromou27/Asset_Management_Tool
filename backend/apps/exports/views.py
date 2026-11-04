"""Export API (docs/04: POST /exports, GET /exports/{id}).

Needs ``exports.run`` plus the family's view permission. Users see their own export jobs;
holders of ``audit.view`` see every job's metadata (never the file). Only the creator can
download, and only until the job expires.
"""

from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework import generics, serializers
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts import catalog
from apps.accounts.permissions import HasPermission
from config.api import ItemsCursorPagination

from . import services
from .families import FAMILIES
from .models import ExportJob

Run = HasPermission(catalog.EXPORTS_RUN)


def visible_jobs(user):
    qs = ExportJob.objects.select_related("created_by").defer("file_encrypted")
    if catalog.AUDIT_VIEW in user.permission_codes():
        return qs
    return qs.filter(created_by=user)


# --- Serializers ------------------------------------------------------------------------------


class ExportColumnSerializer(serializers.Serializer):
    key = serializers.CharField()
    label = serializers.CharField()
    personal = serializers.BooleanField()
    allowed = serializers.BooleanField()


class ExportRelatedSerializer(serializers.Serializer):
    key = serializers.CharField()
    label = serializers.CharField()


class ExportFamilySerializer(serializers.Serializer):
    code = serializers.CharField()
    label = serializers.CharField()
    description = serializers.CharField()
    allowed = serializers.BooleanField()
    filter_keys = serializers.ListField(child=serializers.CharField())
    columns = ExportColumnSerializer(many=True)
    related = ExportRelatedSerializer(many=True)
    personal_data_allowed = serializers.BooleanField()


class ExportJobSerializer(serializers.ModelSerializer):
    created_by = serializers.SlugRelatedField(read_only=True, slug_field="username")
    filters = serializers.DictField(child=serializers.CharField(), read_only=True)
    columns = serializers.ListField(child=serializers.CharField(), read_only=True)
    related = serializers.ListField(child=serializers.CharField(), read_only=True)
    related_counts = serializers.DictField(child=serializers.IntegerField(), read_only=True)
    masked_columns = serializers.ListField(child=serializers.CharField(), read_only=True)
    selected_count = serializers.SerializerMethodField()
    downloadable = serializers.SerializerMethodField()

    class Meta:
        model = ExportJob
        fields = [
            "id",
            "family",
            "file_format",
            "scope",
            "filters",
            "selected_count",
            "columns",
            "related",
            "status",
            "row_count",
            "related_counts",
            "masked_columns",
            "filename",
            "size_bytes",
            "checksum",
            "error_message",
            "created_by",
            "created_at",
            "completed_at",
            "expires_at",
            "download_count",
            "last_downloaded_at",
            "downloadable",
        ]
        read_only_fields = fields

    def get_selected_count(self, obj) -> int:
        return len(obj.ids)

    def get_downloadable(self, obj) -> bool:
        request = self.context.get("request")
        return bool(
            request
            and obj.created_by_id == request.user.pk
            and obj.status == ExportJob.Status.COMPLETED
            and obj.purged_at is None
        )


class ExportCreateSerializer(serializers.Serializer):
    family = serializers.ChoiceField(choices=list(FAMILIES))
    format = serializers.ChoiceField(choices=ExportJob.Format.choices)
    scope = serializers.ChoiceField(choices=ExportJob.Scope.choices)
    filters = serializers.DictField(
        child=serializers.CharField(allow_blank=True), required=False, default=dict
    )
    ids = serializers.ListField(child=serializers.UUIDField(), required=False, default=list)
    columns = serializers.ListField(
        child=serializers.CharField(max_length=60), required=False, default=list, max_length=200
    )
    related = serializers.ListField(
        child=serializers.CharField(max_length=40), required=False, default=list, max_length=20
    )


# --- Views ------------------------------------------------------------------------------------


class ExportFamilyListView(APIView):
    permission_classes = [Run]

    @extend_schema(responses=ExportFamilySerializer(many=True))
    def get(self, request):
        granted = request.user.permission_codes()
        data = [
            services.describe(family, request.user)
            for family in FAMILIES.values()
            if family.permission in granted
        ]
        return Response(ExportFamilySerializer(data, many=True).data)


class ExportPagination(ItemsCursorPagination):
    ordering = ("-created_at", "-id")


class ExportListCreateView(generics.ListAPIView):
    serializer_class = ExportJobSerializer
    pagination_class = ExportPagination
    permission_classes = [Run]

    def get_queryset(self):
        qs = visible_jobs(self.request.user)
        if family := self.request.query_params.get("family"):
            qs = qs.filter(family=family)
        if self.request.query_params.get("mine") == "true":
            qs = qs.filter(created_by=self.request.user)
        return qs

    @extend_schema(request=ExportCreateSerializer, responses={202: ExportJobSerializer})
    def post(self, request):
        data = ExportCreateSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        job = services.create_job(request, data.validated_data)
        job = ExportJob.objects.select_related("created_by").get(pk=job.pk)
        return Response(ExportJobSerializer(job, context={"request": request}).data, status=202)


class ExportDetailView(APIView):
    permission_classes = [Run]

    @extend_schema(responses=ExportJobSerializer)
    def get(self, request, pk):
        job = get_object_or_404(visible_jobs(request.user), pk=pk)
        return Response(ExportJobSerializer(job, context={"request": request}).data)


class ExportDownloadView(APIView):
    permission_classes = [Run]

    @extend_schema(responses={(200, "application/octet-stream"): OpenApiTypes.BINARY})
    def get(self, request, pk):
        job = get_object_or_404(ExportJob.objects.select_related("created_by"), pk=pk)
        if job.created_by_id != request.user.pk and catalog.AUDIT_VIEW not in (
            request.user.permission_codes()
        ):
            # Do not reveal other users' jobs to non-auditors.
            return HttpResponse(status=404)
        body, job = services.download(request, job)
        response = HttpResponse(body, content_type=job.content_type)
        response["Content-Disposition"] = f'attachment; filename="{job.filename}"'
        response["Content-Length"] = str(len(body))
        response["Cache-Control"] = "no-store"
        response["X-Content-Type-Options"] = "nosniff"
        return response
