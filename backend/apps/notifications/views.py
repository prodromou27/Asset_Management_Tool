"""SMTP and notifications API (docs/04: GET/PATCH /settings/{area}, POST /smtp/test;
docs/10 admin buttons). Reading needs ``notifications.view``; changes, tests, retries and
cancels need ``notifications.manage``. No credential value is ever returned: only the
reference and whether it resolves."""

from django.contrib.auth import get_user_model
from django.db.models import Q
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_field
from rest_framework import generics, serializers
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts import catalog
from apps.accounts.permissions import HasPermission
from apps.organizations.models import Site
from config.api import ItemsCursorPagination

from . import rules, services
from .models import NotificationRule, NotificationTemplate, OutboxMessage, SmtpProfile

User = get_user_model()

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


# --- Rules (Task 018b) ------------------------------------------------------------------------


def _recipient(user) -> dict:
    return {
        "id": user.pk,
        "username": user.username,
        "display_name": user.display_name,
        "has_email": bool(user.email),
    }


class RecipientSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    username = serializers.CharField()
    display_name = serializers.CharField()
    has_email = serializers.BooleanField()


class RuleSiteSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    code = serializers.CharField()


class NotificationRuleSerializer(serializers.ModelSerializer):
    recipients = serializers.SerializerMethodField()
    sites = serializers.SerializerMethodField()
    thresholds = serializers.ListField(child=serializers.IntegerField(), read_only=True)

    class Meta:
        model = NotificationRule
        fields = [
            "id",
            "name",
            "event",
            "enabled",
            "thresholds",
            "include_expired",
            "failure_count",
            "recipients",
            "sites",
            "version",
            "last_run_at",
            "last_run_summary",
            "modified_at",
        ]
        read_only_fields = fields

    @extend_schema_field(RecipientSerializer(many=True))
    def get_recipients(self, obj):
        return [_recipient(u) for u in obj.recipients.all()]

    @extend_schema_field(RuleSiteSerializer(many=True))
    def get_sites(self, obj):
        return [{"id": s.pk, "code": s.code} for s in obj.sites.all()]


class NotificationRuleWriteSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=120)
    event = serializers.ChoiceField(choices=NotificationRule.Event.choices)
    enabled = serializers.BooleanField(required=False)
    thresholds = serializers.ListField(
        child=serializers.IntegerField(min_value=1, max_value=3650), required=False, max_length=10
    )
    include_expired = serializers.BooleanField(required=False)
    failure_count = serializers.IntegerField(min_value=1, max_value=50, required=False)
    recipients = serializers.PrimaryKeyRelatedField(
        many=True, queryset=User.objects.filter(is_active=True), required=False
    )
    sites = serializers.PrimaryKeyRelatedField(
        many=True, queryset=Site.objects.all(), required=False
    )


class RulePreviewItemSerializer(serializers.Serializer):
    title = serializers.CharField()
    detail = serializers.CharField()
    date = serializers.CharField()
    status = serializers.CharField()


class RulePreviewRecipientSerializer(serializers.Serializer):
    user = RecipientSerializer()
    eligible = serializers.BooleanField()
    reason = serializers.CharField()
    pending = serializers.IntegerField()
    items = RulePreviewItemSerializer(many=True)


class RulePreviewSerializer(serializers.Serializer):
    mail_enabled = serializers.BooleanField()
    recipients = RulePreviewRecipientSerializer(many=True)


def _rules():
    return NotificationRule.objects.prefetch_related("recipients", "sites")


def _rule_response(rule, http_status=200):
    rule = _rules().get(pk=rule.pk)
    return Response(
        NotificationRuleSerializer(rule).data,
        status=http_status,
        headers={"ETag": f'"{rule.version}"'},
    )


class RuleListView(APIView):
    def get_permissions(self):
        return [(Manage if self.request.method == "POST" else View)()]

    @extend_schema(responses=NotificationRuleSerializer(many=True))
    def get(self, request):
        return Response(NotificationRuleSerializer(_rules(), many=True).data)

    @extend_schema(
        request=NotificationRuleWriteSerializer, responses={201: NotificationRuleSerializer}
    )
    def post(self, request):
        data = NotificationRuleWriteSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        return _rule_response(services.create_rule(request, data.validated_data), 201)


class RuleDetailView(APIView):
    def get_permissions(self):
        return [(View if self.request.method == "GET" else Manage)()]

    @extend_schema(responses=NotificationRuleSerializer)
    def get(self, request, pk):
        return _rule_response(get_object_or_404(NotificationRule, pk=pk))

    @extend_schema(
        request=NotificationRuleWriteSerializer,
        responses=NotificationRuleSerializer,
        parameters=[IF_MATCH],
    )
    def patch(self, request, pk):
        rule = get_object_or_404(NotificationRule, pk=pk)
        data = NotificationRuleWriteSerializer(data=request.data, partial=True)
        data.is_valid(raise_exception=True)
        return _rule_response(
            services.update_rule(request, rule, data.validated_data, _if_match(request))
        )

    @extend_schema(request=None, responses={204: None})
    def delete(self, request, pk):
        services.delete_rule(request, get_object_or_404(NotificationRule, pk=pk))
        return Response(status=204)


class RulePreviewView(APIView):
    """Dry run: what each recipient would be told on the next run (nothing is sent)."""

    permission_classes = [Manage]

    @extend_schema(request=None, responses=RulePreviewSerializer)
    def post(self, request, pk):
        rule = get_object_or_404(_rules(), pk=pk)
        recipients = []
        for user in rule.recipients.all():
            if not rules.eligible(rule, user):
                reason = "No e-mail address" if not user.email else "Lacks access to these findings"
                recipients.append(
                    {
                        "user": _recipient(user),
                        "eligible": False,
                        "reason": reason,
                        "pending": 0,
                        "items": [],
                    }
                )
                continue
            found = rules.pending(rule, user)
            recipients.append(
                {
                    "user": _recipient(user),
                    "eligible": True,
                    "reason": "",
                    "pending": len(found),
                    "items": [
                        {"title": f.title, "detail": f.detail, "date": f.when, "status": f.status}
                        for f in found[:20]
                    ],
                }
            )
        return Response({"mail_enabled": services.get_profile().enabled, "recipients": recipients})


class RecipientListView(APIView):
    """Active ITAM users who can be chosen as recipients (no addresses are returned)."""

    permission_classes = [Manage]

    @extend_schema(responses=RecipientSerializer(many=True))
    def get(self, request):
        users = User.objects.filter(is_active=True).order_by("display_name", "username")
        return Response([_recipient(u) for u in users[:500]])
