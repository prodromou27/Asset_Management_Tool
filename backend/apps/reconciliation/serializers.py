from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.assets.models import TECHNICAL_FIELDS, Asset, AssetCategory
from apps.assets.selectors import visible_assets
from apps.assets.serializers import RefSerializer, SiteRefSerializer
from apps.observations.models import Observation

from .models import AssetMerge, FieldConflict, ReconciliationCandidate, SourceLink


class InstanceRefSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField()
    source = serializers.CharField(source="source_id")


class MatchKeySerializer(serializers.Serializer):
    key = serializers.CharField()
    strength = serializers.ChoiceField(choices=["strong", "corroborating", "conflicting"])
    value = serializers.CharField()


class MatchSerializer(serializers.Serializer):
    asset_id = serializers.UUIDField()
    asset_name = serializers.CharField()
    score = serializers.IntegerField()
    keys = MatchKeySerializer(many=True)
    category_agrees = serializers.BooleanField(allow_null=True)
    # Absent on candidates stored before the rule existed.
    manufacturer_agrees = serializers.BooleanField(allow_null=True, default=None)


class ObservationSummarySerializer(serializers.ModelSerializer):
    normalized = serializers.DictField(read_only=True)

    class Meta:
        model = Observation
        fields = [
            "id",
            "external_id",
            "observed_at",
            "received_at",
            "checksum",
            "source_version",
            "normalized",
        ]
        read_only_fields = fields


class ObservationDetailSerializer(ObservationSummarySerializer):
    instance = InstanceRefSerializer(read_only=True)
    payload = serializers.DictField(read_only=True)

    class Meta(ObservationSummarySerializer.Meta):
        fields = [
            *ObservationSummarySerializer.Meta.fields,
            "instance",
            "payload",
            "normalizer_version",
        ]
        read_only_fields = fields


def _visible_ids(context, ids) -> set:
    key = "_visible_asset_ids"
    cache = context.setdefault(key, {})
    missing = [i for i in ids if i not in cache]
    if missing:
        visible = {
            str(pk)
            for pk in visible_assets(context["request"].user)
            .filter(pk__in=missing)
            .values_list("pk", flat=True)
        }
        for asset_id in missing:
            cache[asset_id] = asset_id in visible
    return {i for i in ids if cache[i]}


class CandidateSerializer(serializers.ModelSerializer):
    instance = InstanceRefSerializer(read_only=True)
    site = SiteRefSerializer(read_only=True)
    observation = ObservationSummarySerializer(read_only=True)
    suggested_category = RefSerializer(read_only=True, allow_null=True)
    proposed_asset = serializers.SerializerMethodField()
    matches = serializers.SerializerMethodField()
    hidden_match_count = serializers.SerializerMethodField()
    conflicts = serializers.ListField(child=serializers.CharField(), read_only=True)
    decided_by = serializers.SlugRelatedField(
        read_only=True, allow_null=True, slug_field="username"
    )
    resulting_asset = RefSerializer(read_only=True, allow_null=True)

    class Meta:
        model = ReconciliationCandidate
        fields = [
            "id",
            "instance",
            "external_id",
            "site",
            "status",
            "rule",
            "score",
            "proposed_asset",
            "matches",
            "hidden_match_count",
            "conflicts",
            "suggested_category",
            "observation",
            "decision",
            "decision_reason",
            "decided_by",
            "decided_at",
            "resulting_asset",
            "created_at",
            "modified_at",
            "version",
        ]
        read_only_fields = fields

    def _visible_matches(self, obj):
        ids = [m["asset_id"] for m in obj.matches]
        visible = _visible_ids(self.context, ids)
        return [m for m in obj.matches if m["asset_id"] in visible]

    @extend_schema_field(MatchSerializer(many=True))
    def get_matches(self, obj):
        return self._visible_matches(obj)

    def get_hidden_match_count(self, obj) -> int:
        return len(obj.matches) - len(self._visible_matches(obj))

    @extend_schema_field(RefSerializer(allow_null=True))
    def get_proposed_asset(self, obj):
        if obj.proposed_asset_id is None or not _visible_ids(
            self.context, [str(obj.proposed_asset_id)]
        ):
            return None
        return {"id": obj.proposed_asset_id, "name": obj.proposed_asset.name}


class ApproveSerializer(serializers.Serializer):
    action = serializers.ChoiceField(choices=["link", "create"])
    asset = serializers.UUIDField(required=False)
    category = serializers.PrimaryKeyRelatedField(
        queryset=AssetCategory.objects.filter(is_active=True), required=False
    )
    name = serializers.CharField(max_length=200, required=False, allow_blank=True)
    business_status = serializers.ChoiceField(choices=Asset.BusinessStatus.choices, required=False)
    reason = serializers.CharField(min_length=5, max_length=500)

    def validate(self, attrs):
        if attrs["action"] == "link" and not attrs.get("asset"):
            raise serializers.ValidationError({"asset": ["Choose the asset to link."]})
        return attrs


class SourceLinkSerializer(serializers.ModelSerializer):
    instance = InstanceRefSerializer(read_only=True)
    linked_by = serializers.SlugRelatedField(read_only=True, allow_null=True, slug_field="username")
    unlinked_by = serializers.SlugRelatedField(
        read_only=True, allow_null=True, slug_field="username"
    )
    last_observation_id = serializers.UUIDField(read_only=True, allow_null=True)

    class Meta:
        model = SourceLink
        fields = [
            "id",
            "instance",
            "external_id",
            "status",
            "method",
            "first_seen_at",
            "last_seen_at",
            "last_observation_id",
            "linked_at",
            "linked_by",
            "unlinked_at",
            "unlinked_by",
            "unlink_reason",
        ]
        read_only_fields = fields


class FieldConflictSerializer(serializers.ModelSerializer):
    asset = RefSerializer(read_only=True)
    instance = InstanceRefSerializer(read_only=True)
    observed_at = serializers.DateTimeField(source="observation.observed_at", read_only=True)
    resolved_by = serializers.SlugRelatedField(
        read_only=True, allow_null=True, slug_field="username"
    )

    class Meta:
        model = FieldConflict
        fields = [
            "id",
            "asset",
            "field",
            "current_value",
            "observed_value",
            "reason",
            "instance",
            "observation",
            "observed_at",
            "status",
            "created_at",
            "modified_at",
            "resolved_by",
            "resolved_at",
            "resolution_reason",
        ]
        read_only_fields = fields


class ResolveConflictSerializer(serializers.Serializer):
    resolution = serializers.ChoiceField(choices=["accept_observed", "keep_current"])
    reason = serializers.CharField(min_length=5, max_length=500)


class LockSerializer(serializers.Serializer):
    field = serializers.ChoiceField(choices=list(TECHNICAL_FIELDS))
    reason = serializers.CharField(min_length=5, max_length=300)


class MergeRequestSerializer(serializers.Serializer):
    source_asset = serializers.UUIDField()
    reason = serializers.CharField(min_length=5, max_length=500)


class AssetMergeSerializer(serializers.ModelSerializer):
    survivor = RefSerializer(read_only=True)
    merged = RefSerializer(read_only=True)
    performed_by = serializers.SlugRelatedField(read_only=True, slug_field="username")
    reverted_by = serializers.SlugRelatedField(
        read_only=True, allow_null=True, slug_field="username"
    )
    moved_link_ids = serializers.ListField(child=serializers.UUIDField(), read_only=True)

    class Meta:
        model = AssetMerge
        fields = [
            "id",
            "survivor",
            "merged",
            "reason",
            "status",
            "moved_link_ids",
            "performed_by",
            "performed_at",
            "reverted_by",
            "reverted_at",
            "revert_reason",
        ]
        read_only_fields = fields


# --- Evidence ---------------------------------------------------------------------------


class ProvenanceSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(choices=["manual", "discovery"])
    instance = InstanceRefSerializer(allow_null=True)
    observed_at = serializers.DateTimeField(allow_null=True)
    recorded_at = serializers.DateTimeField()
    recorded_by = serializers.CharField(allow_null=True)


class LockInfoSerializer(serializers.Serializer):
    locked_by = serializers.CharField(allow_null=True)
    locked_at = serializers.DateTimeField()
    reason = serializers.CharField()


class SourceValueSerializer(serializers.Serializer):
    instance = InstanceRefSerializer()
    external_id = serializers.CharField()
    value = serializers.CharField(allow_null=True)
    observed_at = serializers.DateTimeField()
    link_status = serializers.CharField()
    differs = serializers.BooleanField()


class FieldEvidenceSerializer(serializers.Serializer):
    field = serializers.CharField()
    value = serializers.CharField(allow_blank=True)
    provenance = ProvenanceSerializer(allow_null=True)
    lock = LockInfoSerializer(allow_null=True)
    sources = SourceValueSerializer(many=True)
    open_conflicts = FieldConflictSerializer(many=True)


class AssetEvidenceSerializer(serializers.Serializer):
    field_evidence = FieldEvidenceSerializer(many=True)
    links = SourceLinkSerializer(many=True)
    merges = AssetMergeSerializer(many=True)
