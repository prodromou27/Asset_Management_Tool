"""Asset group API (docs/04: GET/POST /groups, PATCH /groups/{id}, POST /groups/{id}/preview,
GET /groups/{id}/assets, POST /groups/{id}/members).

Groups are visible to holders of ``groups.view``; member lists, counts and previews only
ever include assets in the caller's site scope, so a group never widens access.
"""

from django.contrib.auth import get_user_model
from django.db.models import Count, OuterRef, Q, Subquery
from django.db.models.functions import Coalesce
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import generics, serializers
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts import catalog
from apps.accounts.permissions import HasPermission
from apps.assets.selectors import visible_assets
from apps.assets.serializers import ReasonSerializer, SiteRefSerializer, UserRefSerializer
from config.api import ItemsCursorPagination

from . import rules, services
from .models import AssetGroup, AssetGroupMembership, AssetGroupRuleVersion

IF_MATCH = OpenApiParameter("If-Match", str, OpenApiParameter.HEADER, required=True)


def _if_match(request):
    raw = request.headers.get("If-Match")
    if raw is None:
        return None
    try:
        return int(raw.strip('"W/ '))
    except ValueError:
        return -1


def visible_groups(user):
    """Live groups with the number of members the user may see."""
    visible = visible_assets(user).filter(archived_at__isnull=True).values("pk")
    counts = (
        AssetGroupMembership.objects.filter(
            group=OuterRef("pk"), removed_at__isnull=True, asset__in=visible
        )
        .order_by()
        .values("group")
        .annotate(n=Count("pk"))
        .values("n")
    )
    return (
        AssetGroup.objects.filter(archived_at__isnull=True)
        .select_related("parent", "owner")
        .annotate(member_count=Coalesce(Subquery(counts), 0))
    )


# --- Serializers ------------------------------------------------------------------------------


class ParentGroupRefSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField()


class GroupSerializer(serializers.ModelSerializer):
    parent = ParentGroupRefSerializer(read_only=True, allow_null=True)
    owner = UserRefSerializer(read_only=True, allow_null=True)
    member_count = serializers.IntegerField(read_only=True)
    rule = serializers.JSONField(read_only=True, allow_null=True)

    class Meta:
        model = AssetGroup
        fields = [
            "id",
            "name",
            "description",
            "kind",
            "parent",
            "owner",
            "rule",
            "rule_version",
            "member_count",
            "last_evaluated_at",
            "created_at",
            "modified_at",
            "version",
        ]
        read_only_fields = fields


class GroupWriteSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=120)
    description = serializers.CharField(max_length=500, allow_blank=True, required=False)
    kind = serializers.ChoiceField(choices=AssetGroup.Kind.choices, required=False)
    parent = serializers.PrimaryKeyRelatedField(
        queryset=AssetGroup.objects.filter(archived_at__isnull=True),
        allow_null=True,
        required=False,
    )
    owner = serializers.PrimaryKeyRelatedField(
        queryset=get_user_model().objects.filter(is_active=True), allow_null=True, required=False
    )
    rule = serializers.JSONField(required=False, allow_null=True)
    reason = serializers.CharField(max_length=500, allow_blank=True, required=False)

    def validate_name(self, value):
        value = value.strip()
        clash = AssetGroup.objects.filter(name__iexact=value, archived_at__isnull=True)
        if self.instance is not None:
            clash = clash.exclude(pk=self.instance.pk)
        if clash.exists():
            raise serializers.ValidationError("A group with this name already exists.")
        return value

    def validate(self, attrs):
        if self.instance is None and "kind" not in attrs:
            raise serializers.ValidationError({"kind": ["Choose static or dynamic."]})
        if self.instance is not None and "kind" in attrs and attrs["kind"] != self.instance.kind:
            raise serializers.ValidationError({"kind": ["The kind of a group cannot change."]})
        return attrs


class MemberAssetSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField()
    site = SiteRefSerializer()
    category = serializers.CharField(source="category.name")
    manufacturer = serializers.CharField()
    model = serializers.CharField()


class MembershipSerializer(serializers.ModelSerializer):
    asset = MemberAssetSerializer(read_only=True)
    added_by = serializers.SlugRelatedField(read_only=True, allow_null=True, slug_field="username")
    removed_by = serializers.SlugRelatedField(
        read_only=True, allow_null=True, slug_field="username"
    )

    class Meta:
        model = AssetGroupMembership
        fields = [
            "id",
            "asset",
            "source",
            "rule_version",
            "added_at",
            "added_by",
            "added_reason",
            "removed_at",
            "removed_by",
            "removed_reason",
        ]
        read_only_fields = fields


class RuleVersionSerializer(serializers.ModelSerializer):
    created_by = serializers.SlugRelatedField(
        read_only=True, allow_null=True, slug_field="username"
    )
    rule = serializers.JSONField(read_only=True)

    class Meta:
        model = AssetGroupRuleVersion
        fields = ["number", "rule", "reason", "created_by", "created_at"]
        read_only_fields = fields


class PreviewRequestSerializer(serializers.Serializer):
    rule = serializers.JSONField()


class PreviewAssetSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField()
    site = SiteRefSerializer()


class PreviewSerializer(serializers.Serializer):
    count = serializers.IntegerField()
    sample = PreviewAssetSerializer(many=True)
    would_add = serializers.IntegerField(allow_null=True)
    would_remove = serializers.IntegerField(allow_null=True)


class MemberChangeSerializer(serializers.Serializer):
    add = serializers.ListField(child=serializers.UUIDField(), required=False, default=list)
    remove = serializers.ListField(child=serializers.UUIDField(), required=False, default=list)
    reason = serializers.CharField(max_length=500, allow_blank=True, required=False, default="")


class MemberChangeResultSerializer(serializers.Serializer):
    added = serializers.IntegerField()
    removed = serializers.IntegerField()


class EvaluateResultSerializer(serializers.Serializer):
    added = serializers.IntegerField()
    removed = serializers.IntegerField()
    members = serializers.IntegerField()


class FieldChoiceSerializer(serializers.Serializer):
    value = serializers.CharField()
    label = serializers.CharField()


class RuleFieldSerializer(serializers.Serializer):
    field = serializers.CharField()
    label = serializers.CharField()
    kind = serializers.ChoiceField(choices=["text", "enum", "ref", "date"])
    operators = serializers.ListField(child=serializers.CharField())
    choices = FieldChoiceSerializer(many=True)
    ref = serializers.CharField(allow_blank=True)
    nullable = serializers.BooleanField()


class AssetGroupRefSerializer(serializers.Serializer):
    id = serializers.UUIDField(source="group.id")
    name = serializers.CharField(source="group.name")
    kind = serializers.CharField(source="group.kind")
    source = serializers.CharField()
    rule_version = serializers.IntegerField(allow_null=True)
    added_at = serializers.DateTimeField()


# --- Views ------------------------------------------------------------------------------------

View = HasPermission(catalog.GROUPS_VIEW)
Manage = HasPermission(catalog.GROUPS_MANAGE)


class _ManageOnWrite(APIView):
    def get_permissions(self):
        if self.request.method in ("GET", "HEAD", "OPTIONS"):
            return [View()]
        return [Manage()]


class GroupListCreateView(_ManageOnWrite):
    @extend_schema(
        parameters=[OpenApiParameter("q", str), OpenApiParameter("kind", str)],
        responses=GroupSerializer(many=True),
    )
    def get(self, request):
        rows = visible_groups(request.user)
        if q := request.query_params.get("q", "").strip():
            rows = rows.filter(Q(name__icontains=q) | Q(description__icontains=q))
        if kind := request.query_params.get("kind"):
            rows = rows.filter(kind=kind)
        return Response(GroupSerializer(rows, many=True).data)

    @extend_schema(request=GroupWriteSerializer, responses={201: GroupSerializer})
    def post(self, request):
        data = GroupWriteSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        group = services.create_group(request, data.validated_data)
        return Response(
            GroupSerializer(visible_groups(request.user).get(pk=group.pk)).data, status=201
        )


class GroupDetailView(_ManageOnWrite):
    def group(self, request, pk):
        return get_object_or_404(visible_groups(request.user), pk=pk)

    def respond(self, request, group):
        group = visible_groups(request.user).get(pk=group.pk)
        return Response(GroupSerializer(group).data, headers={"ETag": f'"{group.version}"'})

    @extend_schema(responses=GroupSerializer)
    def get(self, request, pk):
        return self.respond(request, self.group(request, pk))

    @extend_schema(
        request=GroupWriteSerializer(partial=True), responses=GroupSerializer, parameters=[IF_MATCH]
    )
    def patch(self, request, pk):
        group = self.group(request, pk)
        data = GroupWriteSerializer(group, data=request.data, partial=True)
        data.is_valid(raise_exception=True)
        group = services.update_group(request, group, data.validated_data, _if_match(request))
        return self.respond(request, group)


class GroupArchiveView(APIView):
    permission_classes = [Manage]

    @extend_schema(request=ReasonSerializer, responses={204: None}, parameters=[IF_MATCH])
    def post(self, request, pk):
        group = get_object_or_404(visible_groups(request.user), pk=pk)
        data = ReasonSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        services.archive_group(
            request, group, data.validated_data["reason"].strip(), _if_match(request)
        )
        return Response(status=204)


class RulePreviewView(APIView):
    """Preview a rule before creating a group."""

    permission_classes = [Manage]

    @extend_schema(
        request=PreviewRequestSerializer,
        responses=PreviewSerializer,
        operation_id="groups_rule_preview",
    )
    def post(self, request):
        data = PreviewRequestSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        rule = services.clean_rule(data.validated_data["rule"])
        services.check_references(None, rule)
        return Response(
            PreviewSerializer(services.preview(rule, visible_assets(request.user))).data
        )


class GroupPreviewView(APIView):
    """Preview a changed rule against a group's current members (visible assets only)."""

    permission_classes = [Manage]

    @extend_schema(request=PreviewRequestSerializer, responses=PreviewSerializer)
    def post(self, request, pk):
        group = get_object_or_404(visible_groups(request.user), pk=pk)
        data = PreviewRequestSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        rule = services.clean_rule(data.validated_data["rule"])
        services.check_references(group, rule)
        result = services.preview(rule, visible_assets(request.user), group)
        return Response(PreviewSerializer(result).data)


class MemberPagination(ItemsCursorPagination):
    ordering = ("-added_at", "-id")


@extend_schema(
    parameters=[
        OpenApiParameter("history", bool, description="Include removed memberships"),
        OpenApiParameter("q", str, description="Asset name contains"),
    ]
)
class GroupAssetsView(generics.ListAPIView):
    serializer_class = MembershipSerializer
    pagination_class = MemberPagination
    permission_classes = [View]

    def get_queryset(self):
        group = get_object_or_404(visible_groups(self.request.user), pk=self.kwargs["pk"])
        rows = AssetGroupMembership.objects.select_related(
            "asset__site", "asset__category", "added_by", "removed_by"
        ).filter(group=group, asset__in=visible_assets(self.request.user).values("pk"))
        if self.request.query_params.get("history") not in ("true", "1"):
            rows = rows.filter(removed_at__isnull=True)
        if q := self.request.query_params.get("q", "").strip():
            rows = rows.filter(asset__name__icontains=q)
        return rows


class GroupMembersView(APIView):
    permission_classes = [HasPermission(catalog.GROUPS_MEMBERS)]

    @extend_schema(request=MemberChangeSerializer, responses=MemberChangeResultSerializer)
    def post(self, request, pk):
        group = get_object_or_404(visible_groups(request.user), pk=pk)
        data = MemberChangeSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        values = data.validated_data
        wanted = set(values["add"]) | set(values["remove"])
        found = {a.pk: a for a in visible_assets(request.user).filter(pk__in=wanted)}
        if len(found) != len(wanted):
            raise serializers.ValidationError(
                {"assets": ["Some assets do not exist or are outside your sites."]}
            )
        result = services.change_members(
            request,
            group,
            [found[i] for i in values["add"]],
            [found[i] for i in values["remove"]],
            values["reason"].strip(),
        )
        return Response(MemberChangeResultSerializer(result).data)


class GroupEvaluateView(APIView):
    permission_classes = [Manage]

    @extend_schema(request=None, responses=EvaluateResultSerializer)
    def post(self, request, pk):
        group = get_object_or_404(visible_groups(request.user), pk=pk)
        return Response(EvaluateResultSerializer(services.evaluate(group, request=request)).data)


class GroupRuleVersionsView(APIView):
    permission_classes = [View]

    @extend_schema(responses=RuleVersionSerializer(many=True))
    def get(self, request, pk):
        group = get_object_or_404(visible_groups(request.user), pk=pk)
        return Response(RuleVersionSerializer(group.rule_versions.all()[:50], many=True).data)


class RuleFieldsView(APIView):
    permission_classes = [View]

    @extend_schema(responses=RuleFieldSerializer(many=True))
    def get(self, request):
        return Response(RuleFieldSerializer(rules.field_catalogue(), many=True).data)


class AssetGroupsView(APIView):
    """Groups an asset currently belongs to (only for assets the caller can see)."""

    permission_classes = [View]

    @extend_schema(responses=AssetGroupRefSerializer(many=True))
    def get(self, request, pk):
        asset = get_object_or_404(visible_assets(request.user), pk=pk)
        rows = (
            AssetGroupMembership.objects.select_related("group")
            .filter(asset=asset, removed_at__isnull=True, group__archived_at__isnull=True)
            .order_by("group__name")
        )
        return Response(AssetGroupRefSerializer(rows, many=True).data)
