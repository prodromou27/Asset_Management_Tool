"""SMTP and notifications API (docs/04: GET/PATCH /settings/{area}, POST /smtp/test;
docs/10 admin buttons). Reading needs ``notifications.view``; changes, tests, retries and
cancels need ``notifications.manage``. No credential value is ever returned: only the
reference and whether it resolves."""

from django.db.models import Q
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import generics, serializers
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts import catalog
from apps.accounts.permissions import HasPermission
from config.api import ItemsCursorPagination

from . import services
from .models import NotificationTemplate, OutboxMessage, SmtpProfile

View = HasPermission(catalog.NOTIFICATIONS_VIEW)
Manage = HasPermission(catalog.NOTIFICATIONS_VIEW, catalog.NOTIFICATIONS_MANAGE)


def _if_match(request):
    raw = request.headers.get("If-Match")
    if raw is None:
        return None
    try:
        return int(raw.strip('"W/ '))
    except ValueError:
        return -1


IF_MATCH = OpenApiParameter("If-Match", str, OpenApiParameter.HEADER, required=True)


class SmtpProfileSerializer(serializers.ModelSerializer):
    password_status = serializers.SerializerMethodField(
        help_text="not_set | invalid | missing | configured (never the value)"
    )
    modified_by = serializers.SlugRelatedField(
        read_only=True, allow_null=True, slug_field="username"
    )

    class Meta:
        model = SmtpProfile
        fields = [
            "enabled",
            "host",
            "port",
            "security",
            "username",
            "password_ref",
            "password_status",
            "ca_bundle_ref",
            "from_address",
            "from_name",
            "reply_to",
            "timeout_seconds",
            "max_per_minute",
            "last_test_at",
            "last_test_ok",
            "last_test_error",
            "last_test_email_at",
            "version",
            "modified_by",
            "modified_at",
        ]
        read_only_fields = fields

    def get_password_status(self, obj) -> str:
        return services.password_status(obj)


class SmtpProfileWriteSerializer(serializers.Serializer):
    enabled = serializers.BooleanField(required=False)
    host = serializers.CharField(max_length=253, allow_blank=True, required=False)
    port = serializers.IntegerField(min_value=1, max_value=65535, required=False)
    security = serializers.ChoiceField(choices=SmtpProfile.Security.choices, required=False)
    username = serializers.CharField(max_length=254, allow_blank=True, required=False)
    password_ref = serializers.CharField(max_length=120, allow_blank=True, required=False)
    ca_bundle_ref = serializers.CharField(max_length=120, allow_blank=True, required=False)
    from_address = serializers.EmailField(allow_blank=True, required=False)
    from_name = serializers.CharField(max_length=100, required=False)
    reply_to = serializers.EmailField(allow_blank=True, required=False)
    timeout_seconds = serializers.IntegerField(min_value=3, max_value=120, required=False)
    max_per_minute = serializers.IntegerField(min_value=1, max_value=1000, required=False)


class OutboxStatsSerializer(serializers.Serializer):
    counts = serializers.DictField(child=serializers.IntegerField())
    oldest_waiting_at = serializers.DateTimeField(allow_null=True)
    dead_last_24h = serializers.IntegerField()
    problems = serializers.ListField(child=serializers.CharField())
    enabled = serializers.BooleanField()
    configured = serializers.BooleanField()


class OutboxMessageSerializer(serializers.ModelSerializer):
    class Meta:
        model = OutboxMessage
        fields = [
            "id",
            "event_type",
            "template_code",
            "template_version",
            "to_address",
            "subject",
            "message_id",
            "status",
            "attempts",
            "max_attempts",
            "next_attempt_at",
            "last_error",
            "queued_at",
            "sent_at",
            "finished_at",
            "expires_at",
        ]
        read_only_fields = fields


class TemplateVariableSerializer(serializers.Serializer):
    name = serializers.CharField()
    description = serializers.CharField()
    example = serializers.CharField(required=False)


class NotificationTemplateSerializer(serializers.ModelSerializer):
    variables = TemplateVariableSerializer(many=True, read_only=True)
    modified_by = serializers.SlugRelatedField(
        read_only=True, allow_null=True, slug_field="username"
    )

    class Meta:
        model = NotificationTemplate
        fields = [
            "id",
            "code",
            "name",
            "description",
            "variables",
            "subject",
            "body_text",
            "body_html",
            "version",
            "modified_by",
            "modified_at",
        ]
        read_only_fields = fields


class TemplateWriteSerializer(serializers.Serializer):
    subject = serializers.CharField(max_length=300, required=False)
    body_text = serializers.CharField(max_length=20000, required=False)
    body_html = serializers.CharField(max_length=50000, allow_blank=True, required=False)


class TemplatePreviewSerializer(serializers.Serializer):
    subject = serializers.CharField()
    body_text = serializers.CharField()
    body_html = serializers.CharField(allow_blank=True)


def _profile_response(profile):
    return Response(SmtpProfileSerializer(profile).data, headers={"ETag": f'"{profile.version}"'})


class SmtpSettingsView(APIView):
    def get_permissions(self):
        return [(Manage if self.request.method == "PATCH" else View)()]

    @extend_schema(responses=SmtpProfileSerializer)
    def get(self, request):
        return _profile_response(services.get_profile())

    @extend_schema(
        request=SmtpProfileWriteSerializer, responses=SmtpProfileSerializer, parameters=[IF_MATCH]
    )
    def patch(self, request):
        data = SmtpProfileWriteSerializer(data=request.data, partial=True)
        data.is_valid(raise_exception=True)
        return _profile_response(
            services.update_profile(request, data.validated_data, _if_match(request))
        )


class SmtpTestView(APIView):
    """Connect, TLS and login only; sends nothing."""

    permission_classes = [Manage]

    @extend_schema(request=None, responses=SmtpProfileSerializer)
    def post(self, request):
        return _profile_response(services.test_connection(request))


class SmtpTestEmailView(APIView):
    """Send one test message to the signed-in administrator's own address."""

    permission_classes = [Manage]

    @extend_schema(request=None, responses=OutboxMessageSerializer)
    def post(self, request):
        return Response(OutboxMessageSerializer(services.send_test_email(request)).data)


class OutboxStatsView(APIView):
    permission_classes = [View]

    @extend_schema(responses=OutboxStatsSerializer)
    def get(self, request):
        return Response(OutboxStatsSerializer(services.stats()).data)


class OutboxPagination(ItemsCursorPagination):
    ordering = ("-queued_at", "-id")


class OutboxListView(generics.ListAPIView):
    serializer_class = OutboxMessageSerializer
    pagination_class = OutboxPagination
    permission_classes = [View]

    @extend_schema(
        parameters=[
            OpenApiParameter("status", str, description="Comma-separated statuses"),
            OpenApiParameter("q", str, description="Recipient or subject"),
        ]
    )
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

    def get_queryset(self):
        params = self.request.query_params
        qs = OutboxMessage.objects.all()
        if value := params.get("status"):
            qs = qs.filter(status__in=[s for s in value.split(",") if s])
        if q := params.get("q", "").strip()[:100]:
            qs = qs.filter(Q(to_address__icontains=q) | Q(subject__icontains=q))
        return qs


class OutboxRetryView(APIView):
    permission_classes = [Manage]

    @extend_schema(request=None, responses=OutboxMessageSerializer)
    def post(self, request, pk):
        message = services.retry(request, get_object_or_404(OutboxMessage, pk=pk))
        return Response(OutboxMessageSerializer(message).data)


class OutboxCancelView(APIView):
    permission_classes = [Manage]

    @extend_schema(request=None, responses=OutboxMessageSerializer)
    def post(self, request, pk):
        message = services.cancel(request, get_object_or_404(OutboxMessage, pk=pk))
        return Response(OutboxMessageSerializer(message).data)


class TemplateListView(APIView):
    permission_classes = [View]

    @extend_schema(responses=NotificationTemplateSerializer(many=True))
    def get(self, request):
        return Response(
            NotificationTemplateSerializer(NotificationTemplate.objects.all(), many=True).data
        )


class TemplateDetailView(APIView):
    def get_permissions(self):
        return [(Manage if self.request.method == "PATCH" else View)()]

    @extend_schema(responses=NotificationTemplateSerializer)
    def get(self, request, code):
        template = get_object_or_404(NotificationTemplate, code=code)
        return Response(
            NotificationTemplateSerializer(template).data,
            headers={"ETag": f'"{template.version}"'},
        )

    @extend_schema(
        request=TemplateWriteSerializer,
        responses=NotificationTemplateSerializer,
        parameters=[IF_MATCH],
    )
    def patch(self, request, code):
        template = get_object_or_404(NotificationTemplate, code=code)
        data = TemplateWriteSerializer(data=request.data, partial=True)
        data.is_valid(raise_exception=True)
        template = services.update_template(
            request, template, data.validated_data, _if_match(request)
        )
        return Response(
            NotificationTemplateSerializer(template).data,
            headers={"ETag": f'"{template.version}"'},
        )


class TemplatePreviewView(APIView):
    """Render the saved template, or an unsaved draft, with example values."""

    permission_classes = [View]

    @extend_schema(request=TemplateWriteSerializer, responses=TemplatePreviewSerializer)
    def post(self, request, code):
        template = get_object_or_404(NotificationTemplate, code=code)
        data = TemplateWriteSerializer(data=request.data, partial=True)
        data.is_valid(raise_exception=True)
        rendered = services.preview(template, data.validated_data)
        return Response(
            {
                "subject": rendered.subject,
                "body_text": rendered.body_text,
                "body_html": rendered.body_html,
            }
        )
