from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import serializers
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import HasPermission
from apps.audit import services as audit
from config.api import require_if_match

from . import services
from .models import BackupJob, BackupPolicy, RestoreDrill


class BackupPolicySerializer(serializers.ModelSerializer):
    hour_utc = serializers.IntegerField(min_value=0, max_value=23)
    rpo_hours = serializers.IntegerField(min_value=1, max_value=168)
    rto_hours = serializers.IntegerField(min_value=1, max_value=168)
    keep_daily = serializers.IntegerField(min_value=1, max_value=365)
    keep_weekly = serializers.IntegerField(min_value=1, max_value=104)
    keep_monthly = serializers.IntegerField(min_value=1, max_value=120)

    class Meta:
        model = BackupPolicy
        fields = [
            "enabled",
            "hour_utc",
            "rpo_hours",
            "rto_hours",
            "keep_daily",
            "keep_weekly",
            "keep_monthly",
            "retention_enabled",
            "version",
            "modified_at",
        ]
        read_only_fields = ["version", "modified_at"]


class BackupJobSerializer(serializers.ModelSerializer):
    duration_seconds = serializers.SerializerMethodField()
    verification_result = serializers.SerializerMethodField()

    def get_duration_seconds(self, obj) -> float | None:
        if obj.started_at and obj.finished_at:
            return (obj.finished_at - obj.started_at).total_seconds()
        return None

    def get_verification_result(self, obj) -> str:
        return {"succeeded": "passed", "failed": "failed"}.get(obj.status, "pending")

    class Meta:
        model = BackupJob
        fields = [
            "id",
            "kind",
            "status",
            "target_label",
            "snapshot_id",
            "source",
            "created_by",
            "created_at",
            "started_at",
            "finished_at",
            "recovery_point",
            "size_bytes",
            "manifest",
            "error_message",
            "warning",
            "duration_seconds",
            "verification_result",
        ]
        read_only_fields = fields


class RestoreDrillSerializer(serializers.ModelSerializer):
    isolated = serializers.BooleanField(write_only=True)
    outbound_disabled = serializers.BooleanField(write_only=True)
    duration_seconds = serializers.SerializerMethodField()
    recovery_point = serializers.DateTimeField(
        source="backup.recovery_point", read_only=True, allow_null=True
    )
    recovery_point_age_seconds = serializers.SerializerMethodField()

    def get_duration_seconds(self, obj) -> float:
        return (obj.finished_at - obj.started_at).total_seconds()

    def get_recovery_point_age_seconds(self, obj) -> float | None:
        if obj.backup.recovery_point:
            return (obj.started_at - obj.backup.recovery_point).total_seconds()
        return None

    class Meta:
        model = RestoreDrill
        fields = [
            "id",
            "backup",
            "target_label",
            "started_at",
            "finished_at",
            "passed",
            "notes",
            "recorded_by",
            "recorded_at",
            "isolated",
            "outbound_disabled",
            "duration_seconds",
            "recovery_point",
            "recovery_point_age_seconds",
        ]
        read_only_fields = ["id", "recorded_by", "recorded_at"]

    def validate(self, attrs):
        if not attrs.pop("isolated", False) or not attrs.pop("outbound_disabled", False):
            raise serializers.ValidationError(
                "Confirm isolation and disabled outgoing integrations/mail."
            )
        backup = attrs["backup"]
        if backup.kind != "backup" or backup.status != "succeeded":
            raise serializers.ValidationError("Choose a successfully verified backup.")
        if attrs["finished_at"] < attrs["started_at"] or attrs["finished_at"] > timezone.now():
            raise serializers.ValidationError("Drill timestamps must be in order and in the past.")
        if backup.recovery_point and attrs["started_at"] < backup.recovery_point:
            raise serializers.ValidationError(
                "A restore drill cannot start before its backup recovery point."
            )
        return attrs


class BackupSummarySerializer(serializers.Serializer):
    execution_allowed = serializers.BooleanField()
    target_label = serializers.CharField()
    encryption = serializers.CharField()
    off_host = serializers.CharField()
    last_backup = BackupJobSerializer(allow_null=True)
    last_drill = RestoreDrillSerializer(allow_null=True)
    last_verification = BackupJobSerializer(allow_null=True)
    problems = serializers.ListField(child=serializers.CharField())


class PolicyView(APIView):
    def get_permissions(self):
        return [
            HasPermission("backups.manage" if self.request.method == "PATCH" else "backups.view")()
        ]

    @extend_schema(responses=BackupPolicySerializer)
    def get(self, request):
        obj = services.policy()
        return Response(BackupPolicySerializer(obj).data, headers={"ETag": f'"{obj.version}"'})

    @extend_schema(
        request=BackupPolicySerializer,
        responses=BackupPolicySerializer,
        parameters=[OpenApiParameter("If-Match", str, OpenApiParameter.HEADER, required=True)],
    )
    def patch(self, request):
        services.policy()
        with transaction.atomic():
            obj = BackupPolicy.objects.select_for_update().get(pk=1)
            require_if_match(request, obj.version)
            before = BackupPolicySerializer(obj).data
            data = BackupPolicySerializer(obj, data=request.data, partial=True)
            data.is_valid(raise_exception=True)
            if data.validated_data.get("enabled"):
                services.gate()
            data.save(version=obj.version + 1)
            audit.record(
                action="backups.policy_update",
                actor=request.user,
                request=request,
                object_type="backup_policy",
                object_id="1",
                before=before,
                after=BackupPolicySerializer(obj).data,
            )
        return Response(BackupPolicySerializer(obj).data, headers={"ETag": f'"{obj.version}"'})


class SummaryView(APIView):
    permission_classes = [HasPermission("backups.view")]

    @extend_schema(responses=BackupSummarySerializer)
    def get(self, request):
        return Response(BackupSummarySerializer(services.summary()).data)


class ReportView(SummaryView):
    @extend_schema(responses=BackupSummarySerializer)
    def get(self, request):
        audit.record(
            action="backups.report_download",
            actor=request.user,
            request=request,
            object_type="backup_report",
        )
        response = super().get(request)
        response["Content-Disposition"] = 'attachment; filename="itam-recovery-summary.json"'
        response["Cache-Control"] = "no-store"
        return response


class JobListView(APIView):
    def get_permissions(self):
        return [
            HasPermission("backups.manage" if self.request.method == "POST" else "backups.view")()
        ]

    @extend_schema(responses=BackupJobSerializer(many=True))
    def get(self, request):
        return Response(BackupJobSerializer(BackupJob.objects.all()[:100], many=True).data)

    @extend_schema(request=None, responses={202: BackupJobSerializer})
    def post(self, request):
        job = services.request_job(actor=request.user, request=request)
        return Response(BackupJobSerializer(job).data, status=202)


class JobDetailView(APIView):
    permission_classes = [HasPermission("backups.view")]

    @extend_schema(responses=BackupJobSerializer)
    def get(self, request, pk):
        return Response(BackupJobSerializer(get_object_or_404(BackupJob, pk=pk)).data)


def report_response(request, obj, serializer, filename):
    audit.record(
        action="backups.report_download",
        actor=request.user,
        request=request,
        object_type=obj._meta.model_name,
        object_id=obj.pk,
    )
    return Response(
        serializer(obj).data,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
        },
    )


class JobReportView(JobDetailView):
    @extend_schema(responses=BackupJobSerializer)
    def get(self, request, pk):
        obj = get_object_or_404(BackupJob, pk=pk)
        return report_response(request, obj, BackupJobSerializer, f"backup-{obj.pk}.json")


class DrillReportView(APIView):
    permission_classes = [HasPermission("backups.view")]

    @extend_schema(responses=RestoreDrillSerializer)
    def get(self, request, pk):
        obj = get_object_or_404(RestoreDrill.objects.select_related("backup"), pk=pk)
        return report_response(request, obj, RestoreDrillSerializer, f"restore-drill-{obj.pk}.json")


class VerifyView(APIView):
    permission_classes = [HasPermission("backups.manage")]

    @extend_schema(request=None, responses={202: BackupJobSerializer})
    def post(self, request, pk):
        source = get_object_or_404(BackupJob, pk=pk)
        job = services.request_job("verify", actor=request.user, source=source, request=request)
        return Response(BackupJobSerializer(job).data, status=202)


class DrillListView(APIView):
    def get_permissions(self):
        return [
            HasPermission("backups.manage" if self.request.method == "POST" else "backups.view")()
        ]

    @extend_schema(responses=RestoreDrillSerializer(many=True))
    def get(self, request):
        return Response(
            RestoreDrillSerializer(
                RestoreDrill.objects.select_related("backup")[:100], many=True
            ).data
        )

    @extend_schema(request=RestoreDrillSerializer, responses={201: RestoreDrillSerializer})
    def post(self, request):
        data = RestoreDrillSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        with transaction.atomic():
            obj = data.save(recorded_by=request.user)
            audit.record(
                action="backups.restore_drill_recorded",
                actor=request.user,
                request=request,
                object_type="restore_drill",
                object_id=obj.pk,
                after={
                    "backup": str(obj.backup_id),
                    "passed": obj.passed,
                    "target_label": obj.target_label,
                    "notes": obj.notes,
                    "started_at": obj.started_at.isoformat(),
                    "finished_at": obj.finished_at.isoformat(),
                },
            )
        if not obj.passed:
            services.operational_alert(
                "An isolated restore drill failed. Review Backups & Recovery.", str(obj.pk)
            )
        return Response(data.data, status=201)
