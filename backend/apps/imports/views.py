"""Import API (docs/04: GET /imports/templates, POST /imports, GET /imports/{id}/preview,
POST /imports/{id}/commit, GET /imports/{id}/errors).

Needs ``imports.run`` plus the family's own permission (for example ``sites.manage`` for
locations). Each user sees their own import jobs; holders of ``audit.view`` see all jobs
(read-only).
"""

import csv
import io

from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import generics, serializers
from rest_framework.parsers import MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts import catalog
from apps.accounts.permissions import HasPermission
from apps.assets.serializers import ReasonSerializer
from config.api import ItemsCursorPagination

from . import parsing, services
from .families import FAMILIES
from .models import ImportJob, ImportRow

IF_MATCH = OpenApiParameter("If-Match", str, OpenApiParameter.HEADER, required=True)
IDEMPOTENCY = OpenApiParameter("X-Idempotency-Key", str, OpenApiParameter.HEADER, required=True)
Run = HasPermission(catalog.IMPORTS_RUN)


def _if_match(request):
    raw = request.headers.get("If-Match")
    if raw is None:
        return None
    try:
        return int(raw.strip('"W/ '))
    except ValueError:
        return -1


def visible_jobs(user):
    qs = ImportJob.objects.select_related("created_by", "committed_by").defer("file_encrypted")
    if catalog.AUDIT_VIEW in user.permission_codes():
        return qs
    return qs.filter(created_by=user)


# --- Serializers ------------------------------------------------------------------------------


class ColumnSerializer(serializers.Serializer):
    name = serializers.CharField()
    label = serializers.CharField()
    required = serializers.ChoiceField(choices=["", "always", "create", "match"])
    help = serializers.CharField(allow_blank=True)
    example = serializers.CharField(allow_blank=True)


class TemplateSerializer(serializers.Serializer):
    code = serializers.CharField()
    label = serializers.CharField()
    version = serializers.IntegerField()
    description = serializers.CharField()
    match_help = serializers.CharField()
    columns = ColumnSerializer(many=True)
    custom_columns = serializers.BooleanField(source="allow_custom_columns")
    allowed = serializers.SerializerMethodField()

    def get_allowed(self, obj) -> bool:
        return not obj.permission or obj.permission in self.context["permissions"]


class JobSerializer(serializers.ModelSerializer):
    created_by = serializers.SlugRelatedField(read_only=True, slug_field="username")
    committed_by = serializers.SlugRelatedField(
        read_only=True, allow_null=True, slug_field="username"
    )
    headers = serializers.ListField(child=serializers.CharField(), read_only=True)
    mapping = serializers.DictField(child=serializers.CharField(allow_blank=True), read_only=True)
    totals = serializers.DictField(read_only=True)
    warnings = serializers.ListField(child=serializers.CharField(), read_only=True)
    file_retained = serializers.SerializerMethodField()

    class Meta:
        model = ImportJob
        fields = [
            "id",
            "family",
            "template_version",
            "status",
            "mode",
            "filename",
            "file_format",
            "size_bytes",
            "checksum",
            "encoding",
            "sheet",
            "headers",
            "mapping",
            "row_count",
            "totals",
            "warnings",
            "error_message",
            "progress",
            "file_retained",
            "purge_after",
            "created_by",
            "created_at",
            "previewed_at",
            "committed_by",
            "committed_at",
            "completed_at",
            "rolled_back_at",
            "version",
        ]
        read_only_fields = fields

    def get_file_retained(self, obj) -> bool:
        return obj.purged_at is None


class JobDetailSerializer(JobSerializer):
    sample = serializers.SerializerMethodField()

    class Meta(JobSerializer.Meta):
        fields = [*JobSerializer.Meta.fields, "sample"]
        read_only_fields = fields

    def get_sample(self, obj) -> list[list[str]]:
        if obj.purged_at is not None or obj.status not in ("uploaded", "previewed", "previewing"):
            return []
        try:
            return services.sample_rows(obj)
        except Exception:  # noqa: BLE001 - a sample is best-effort
            return []


class UploadSerializer(serializers.Serializer):
    family = serializers.ChoiceField(choices=list(FAMILIES))
    file = serializers.FileField()


class JobUpdateSerializer(serializers.Serializer):
    mapping = serializers.DictField(child=serializers.CharField(allow_blank=True), required=False)
    mode = serializers.ChoiceField(choices=ImportJob.Mode.choices, required=False)


class RowSerializer(serializers.ModelSerializer):
    messages = serializers.ListField(child=serializers.CharField(), read_only=True)
    values = serializers.DictField(read_only=True)
    changes = serializers.DictField(read_only=True)

    class Meta:
        model = ImportRow
        fields = [
            "row_number",
            "action",
            "key",
            "target_id",
            "target_label",
            "messages",
            "values",
            "changes",
            "result",
            "result_message",
        ]
        read_only_fields = fields

    def to_representation(self, obj):
        data = super().to_representation(obj)
        data["values"] = {k: parsing.escape_cell(v) for k, v in data["values"].items()}
        return data


# --- Views ------------------------------------------------------------------------------------


class TemplateListView(APIView):
    permission_classes = [Run]

    @extend_schema(responses=TemplateSerializer(many=True))
    def get(self, request):
        context = {"permissions": set(request.user.permission_codes())}
        return Response(TemplateSerializer(FAMILIES.values(), many=True, context=context).data)


class TemplateDownloadView(APIView):
    """CSV template: header row plus one example row (formula-escaped)."""

    permission_classes = [Run]

    @extend_schema(responses={(200, "text/csv"): OpenApiTypes.STR})
    def get(self, request, family):
        fam = FAMILIES.get(family)
        if fam is None:
            return HttpResponse(status=404)
        out = io.StringIO()
        writer = csv.writer(out)
        writer.writerow([c.name for c in fam.columns])
        writer.writerow([parsing.escape_cell(c.example) for c in fam.columns])
        response = HttpResponse("﻿" + out.getvalue(), content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = (
            f'attachment; filename="{fam.code}-import-template-v{fam.version}.csv"'
        )
        return response


class JobPagination(ItemsCursorPagination):
    ordering = ("-created_at", "-id")


class JobListCreateView(generics.ListAPIView):
    serializer_class = JobSerializer
    pagination_class = JobPagination
    permission_classes = [Run]
    parser_classes = [MultiPartParser]

    def get_queryset(self):
        qs = visible_jobs(self.request.user)
        if family := self.request.query_params.get("family"):
            qs = qs.filter(family=family)
        return qs

    @extend_schema(request=UploadSerializer, responses={201: JobDetailSerializer})
    def post(self, request):
        data = UploadSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        job = services.create_job(
            request, data.validated_data["family"], data.validated_data["file"]
        )
        return Response(
            JobDetailSerializer(job).data, status=201, headers={"ETag": f'"{job.version}"'}
        )


class _JobView(APIView):
    permission_classes = [Run]

    def job(self, request, pk):
        return get_object_or_404(visible_jobs(request.user), pk=pk)

    def own(self, request, pk):
        """Only the uploader changes a job."""
        return get_object_or_404(ImportJob.objects.filter(created_by=request.user), pk=pk)

    def respond(self, job, status=200):
        job = ImportJob.objects.get(pk=job.pk)
        return Response(
            JobDetailSerializer(job).data, status=status, headers={"ETag": f'"{job.version}"'}
        )


class JobDetailView(_JobView):
    @extend_schema(responses=JobDetailSerializer)
    def get(self, request, pk):
        return self.respond(self.job(request, pk))

    @extend_schema(
        request=JobUpdateSerializer, responses=JobDetailSerializer, parameters=[IF_MATCH]
    )
    def patch(self, request, pk):
        job = self.own(request, pk)
        data = JobUpdateSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        return self.respond(
            services.update_job(request, job, data.validated_data, _if_match(request))
        )


class JobPreviewView(_JobView):
    @extend_schema(request=None, responses={202: JobDetailSerializer}, parameters=[IF_MATCH])
    def post(self, request, pk):
        job = services.start_preview(request, self.own(request, pk), _if_match(request))
        return self.respond(job, status=202)


class JobCommitView(_JobView):
    @extend_schema(
        request=None, responses={202: JobDetailSerializer}, parameters=[IF_MATCH, IDEMPOTENCY]
    )
    def post(self, request, pk):
        job = services.start_commit(
            request,
            self.own(request, pk),
            request.headers.get("X-Idempotency-Key", "").strip(),
            _if_match(request),
        )
        return self.respond(job, status=202)


class JobRollbackView(_JobView):
    @extend_schema(request=ReasonSerializer, responses=JobDetailSerializer, parameters=[IF_MATCH])
    def post(self, request, pk):
        data = ReasonSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        job = services.rollback(
            request,
            self.own(request, pk),
            data.validated_data["reason"].strip(),
            _if_match(request),
        )
        return self.respond(job)


class RowPagination(ItemsCursorPagination):
    ordering = ("row_number", "id")
    page_size = 100


@extend_schema(
    parameters=[
        OpenApiParameter("action", str, enum=list(ImportRow.Action.values)),
        OpenApiParameter("result", str),
    ]
)
class JobRowsView(generics.ListAPIView):
    serializer_class = RowSerializer
    pagination_class = RowPagination
    permission_classes = [Run]

    def get_queryset(self):
        job = get_object_or_404(visible_jobs(self.request.user), pk=self.kwargs["pk"])
        rows = job.rows.all()
        if action := self.request.query_params.get("action"):
            rows = rows.filter(action=action)
        if (result := self.request.query_params.get("result")) is not None and result != "any":
            rows = rows.filter(Q(result=result))
        return rows


class JobErrorsView(_JobView):
    @extend_schema(responses={(200, "text/csv"): OpenApiTypes.STR})
    def get(self, request, pk):
        job = self.job(request, pk)
        response = HttpResponse(
            "﻿" + services.error_report(job), content_type="text/csv; charset=utf-8"
        )
        response["Content-Disposition"] = f'attachment; filename="import-{job.pk}-rows.csv"'
        return response
