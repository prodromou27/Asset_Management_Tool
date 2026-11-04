from rest_framework import serializers

from apps.assets.serializers import SiteRefSerializer

from .models import (
    AssetLifecycleMatch,
    Dimension,
    LifecycleAlias,
    LifecycleAssessment,
    LifecycleAssessmentHistory,
    LifecycleException,
    LifecycleMilestone,
    LifecycleProduct,
    LifecycleRevision,
    LifecycleSource,
    MilestoneType,
    Status,
    VendorAlias,
)


def _username(user) -> str | None:
    return user.username if user else None


# --- Sources ----------------------------------------------------------------------------------


class LifecycleSourceSerializer(serializers.ModelSerializer):
    created_by = serializers.SlugRelatedField(
        read_only=True, allow_null=True, slug_field="username"
    )

    class Meta:
        model = LifecycleSource
        fields = [
            "id",
            "publisher",
            "title",
            "url",
            "source_type",
            "document_ref",
            "collected_on",
            "last_verified_on",
            "notes",
            "created_by",
            "created_at",
            "modified_at",
            "version",
        ]
        read_only_fields = ["id", "created_by", "created_at", "modified_at", "version"]

    def validate_url(self, value):
        if value and not value.lower().startswith(("https://", "http://")):
            raise serializers.ValidationError("Use an http(s) link.")
        return value


class LifecycleSourceRefSerializer(serializers.ModelSerializer):
    class Meta:
        model = LifecycleSource
        fields = [
            "id",
            "publisher",
            "title",
            "url",
            "source_type",
            "collected_on",
            "last_verified_on",
        ]
        read_only_fields = fields


# --- Products, aliases, milestones --------------------------------------------------------------


class LifecycleAliasSerializer(serializers.ModelSerializer):
    created_by = serializers.SlugRelatedField(
        read_only=True, allow_null=True, slug_field="username"
    )

    class Meta:
        model = LifecycleAlias
        fields = ["id", "kind", "value", "release", "note", "created_by", "created_at"]
        read_only_fields = ["id", "created_by", "created_at"]

    def validate_value(self, value):
        if not value.strip():
            raise serializers.ValidationError("Enter the alias.")
        return value


class LifecycleMilestoneSerializer(serializers.ModelSerializer):
    source = LifecycleSourceRefSerializer(read_only=True)
    reviewed_by = serializers.SerializerMethodField()
    created_by = serializers.SlugRelatedField(
        read_only=True, allow_null=True, slug_field="username"
    )

    class Meta:
        model = LifecycleMilestone
        fields = [
            "id",
            "milestone_type",
            "date",
            "source",
            "verification",
            "reviewed_by",
            "reviewed_at",
            "notes",
            "created_by",
            "created_at",
            "version",
        ]
        read_only_fields = fields

    def get_reviewed_by(self, obj) -> str | None:
        return _username(obj.reviewed_by)


class LifecycleMilestoneWriteSerializer(serializers.Serializer):
    milestone_type = serializers.ChoiceField(choices=MilestoneType.choices)
    date = serializers.DateField()
    source = serializers.PrimaryKeyRelatedField(queryset=LifecycleSource.objects.all())
    notes = serializers.CharField(max_length=1000, required=False, allow_blank=True, default="")


class LifecycleMilestoneUpdateSerializer(serializers.Serializer):
    milestone_type = serializers.ChoiceField(choices=MilestoneType.choices, required=False)
    date = serializers.DateField(required=False)
    source = serializers.PrimaryKeyRelatedField(
        queryset=LifecycleSource.objects.all(), required=False
    )
    notes = serializers.CharField(max_length=1000, required=False, allow_blank=True)
    reason = serializers.CharField(min_length=5, max_length=500)


class LifecycleMilestoneReviewSerializer(serializers.Serializer):
    decision = serializers.ChoiceField(choices=["verified", "rejected"])
    note = serializers.CharField(max_length=500, required=False, allow_blank=True, default="")

    def validate(self, attrs):
        if attrs["decision"] == "rejected" and len(attrs["note"].strip()) < 5:
            raise serializers.ValidationError({"note": ["Explain why the date is rejected."]})
        return attrs


class LifecycleProductSerializer(serializers.ModelSerializer):
    dimension = serializers.ChoiceField(choices=Dimension.choices, read_only=True)
    milestones_verified = serializers.IntegerField(read_only=True, default=0)
    milestones_pending = serializers.IntegerField(read_only=True, default=0)
    alias_count = serializers.IntegerField(read_only=True, default=0)
    matched_assets = serializers.IntegerField(read_only=True, default=0)

    class Meta:
        model = LifecycleProduct
        fields = [
            "id",
            "kind",
            "dimension",
            "vendor",
            "name",
            "release",
            "family",
            "description",
            "support_statement",
            "is_active",
            "milestones_verified",
            "milestones_pending",
            "alias_count",
            "matched_assets",
            "modified_at",
            "version",
        ]
        read_only_fields = [
            "id",
            "dimension",
            "support_statement",
            "milestones_verified",
            "milestones_pending",
            "alias_count",
            "matched_assets",
            "modified_at",
            "version",
        ]


class LifecycleProductDetailSerializer(LifecycleProductSerializer):
    aliases = LifecycleAliasSerializer(many=True, read_only=True)
    milestones = LifecycleMilestoneSerializer(many=True, read_only=True)
    statement_source = LifecycleSourceRefSerializer(read_only=True, allow_null=True)
    statement_verified_by = serializers.SerializerMethodField()
    created_by = serializers.SlugRelatedField(
        read_only=True, allow_null=True, slug_field="username"
    )
    modified_by = serializers.SlugRelatedField(
        read_only=True, allow_null=True, slug_field="username"
    )

    class Meta(LifecycleProductSerializer.Meta):
        fields = [
            *LifecycleProductSerializer.Meta.fields,
            "statement_source",
            "statement_verified_by",
            "statement_verified_at",
            "aliases",
            "milestones",
            "created_by",
            "created_at",
            "modified_by",
        ]
        read_only_fields = fields

    def get_statement_verified_by(self, obj) -> str | None:
        return _username(obj.statement_verified_by)


class LifecycleProductWriteSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(choices=LifecycleProduct.Kind.choices)
    vendor = serializers.CharField(max_length=150)
    name = serializers.CharField(max_length=200)
    release = serializers.CharField(max_length=100, required=False, allow_blank=True, default="")
    family = serializers.CharField(max_length=150, required=False, allow_blank=True, default="")
    description = serializers.CharField(
        max_length=500, required=False, allow_blank=True, default=""
    )

    def validate(self, attrs):
        for name in ("vendor", "name"):
            if name in attrs and not attrs[name].strip():
                raise serializers.ValidationError({name: ["This field may not be blank."]})
        kind = attrs.get("kind")
        if (
            kind in ("operating_system", "firmware", "software")
            and "release" in attrs
            and not attrs["release"].strip()
        ):
            raise serializers.ValidationError(
                {"release": ["Enter the release or version this lifecycle applies to."]}
            )
        return {k: v.strip() if isinstance(v, str) else v for k, v in attrs.items()}


class LifecycleProductUpdateSerializer(LifecycleProductWriteSerializer):
    kind = serializers.ChoiceField(choices=LifecycleProduct.Kind.choices, required=False)
    vendor = serializers.CharField(max_length=150, required=False)
    name = serializers.CharField(max_length=200, required=False)
    release = serializers.CharField(max_length=100, required=False, allow_blank=True)
    family = serializers.CharField(max_length=150, required=False, allow_blank=True)
    description = serializers.CharField(max_length=500, required=False, allow_blank=True)
    is_active = serializers.BooleanField(required=False)
    reason = serializers.CharField(min_length=5, max_length=500)


class LifecycleStatementSerializer(serializers.Serializer):
    support_statement = serializers.ChoiceField(choices=LifecycleProduct.SupportStatement.choices)
    statement_source = serializers.PrimaryKeyRelatedField(
        queryset=LifecycleSource.objects.all(), allow_null=True, required=False
    )
    verify = serializers.BooleanField(default=False)


class LifecycleRevisionSerializer(serializers.ModelSerializer):
    actor = serializers.SlugRelatedField(read_only=True, allow_null=True, slug_field="username")
    snapshot = serializers.DictField(read_only=True)

    class Meta:
        model = LifecycleRevision
        fields = ["number", "action", "summary", "snapshot", "actor", "created_at"]
        read_only_fields = fields


class VendorAliasSerializer(serializers.ModelSerializer):
    created_by = serializers.SlugRelatedField(
        read_only=True, allow_null=True, slug_field="username"
    )

    class Meta:
        model = VendorAlias
        fields = ["id", "alias", "vendor", "created_by", "created_at"]
        read_only_fields = ["id", "created_by", "created_at"]


# --- Assets: matches, assessments, exceptions ---------------------------------------------------


class LifecycleAssetRefSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField()
    site = SiteRefSerializer()
    manufacturer = serializers.CharField()
    model = serializers.CharField()
    os_name = serializers.CharField()
    os_version = serializers.CharField()
    firmware_version = serializers.CharField()


class LifecycleProductRefSerializer(serializers.ModelSerializer):
    label = serializers.CharField(source="__str__", read_only=True)

    class Meta:
        model = LifecycleProduct
        fields = ["id", "kind", "vendor", "name", "release", "label"]
        read_only_fields = fields


class LifecycleCandidateSerializer(serializers.Serializer):
    product_id = serializers.UUIDField()
    label = serializers.CharField()
    reason = serializers.CharField()


class LifecycleMatchSerializer(serializers.ModelSerializer):
    asset = LifecycleAssetRefSerializer(read_only=True)
    product = LifecycleProductRefSerializer(read_only=True, allow_null=True)
    candidates = LifecycleCandidateSerializer(many=True, read_only=True)
    observed = serializers.DictField(read_only=True)
    rejected_products = serializers.ListField(child=serializers.UUIDField(), read_only=True)
    reviewed_by = serializers.SerializerMethodField()

    class Meta:
        model = AssetLifecycleMatch
        fields = [
            "id",
            "asset",
            "dimension",
            "state",
            "method",
            "product",
            "observed",
            "candidates",
            "reason",
            "rejected_products",
            "reviewed_by",
            "reviewed_at",
            "review_note",
            "modified_at",
            "version",
        ]
        read_only_fields = fields

    def get_reviewed_by(self, obj) -> str | None:
        return _username(obj.reviewed_by)


class LifecycleMatchApproveSerializer(serializers.Serializer):
    product = serializers.PrimaryKeyRelatedField(
        queryset=LifecycleProduct.objects.filter(is_active=True)
    )
    remember_alias = serializers.BooleanField(default=False)
    note = serializers.CharField(max_length=500, required=False, allow_blank=True, default="")


class LifecycleMatchRejectSerializer(serializers.Serializer):
    products = serializers.ListField(child=serializers.UUIDField(), required=False, default=list)
    note = serializers.CharField(min_length=5, max_length=500)


class LifecycleExceptionSerializer(serializers.ModelSerializer):
    approved_by = serializers.SlugRelatedField(read_only=True, slug_field="username")
    revoked_by = serializers.SlugRelatedField(
        read_only=True, allow_null=True, slug_field="username"
    )
    asset = LifecycleAssetRefSerializer(read_only=True)
    active = serializers.SerializerMethodField()

    class Meta:
        model = LifecycleException
        fields = [
            "id",
            "asset",
            "dimension",
            "status",
            "reason",
            "compensating_controls",
            "expires_on",
            "approved_by",
            "approved_at",
            "revoked_by",
            "revoked_at",
            "revoke_reason",
            "active",
            "version",
        ]
        read_only_fields = fields

    def get_active(self, obj) -> bool:
        from .services import today_utc

        return obj.revoked_at is None and obj.expires_on >= today_utc()


class LifecycleExceptionWriteSerializer(serializers.Serializer):
    dimension = serializers.ChoiceField(choices=[Dimension.HARDWARE, Dimension.OS])
    status = serializers.ChoiceField(
        choices=[s for s in Status.choices if s[0] not in ("unverified", "not_applicable")]
    )
    reason = serializers.CharField(min_length=10, max_length=1000)
    compensating_controls = serializers.CharField(
        max_length=1000, required=False, allow_blank=True, default=""
    )
    expires_on = serializers.DateField()


class LifecycleExceptionRefSerializer(serializers.ModelSerializer):
    approved_by = serializers.SlugRelatedField(read_only=True, slug_field="username")

    class Meta:
        model = LifecycleException
        fields = ["id", "status", "expires_on", "approved_by"]
        read_only_fields = fields


class LifecycleAssessmentSerializer(serializers.ModelSerializer):
    asset = LifecycleAssetRefSerializer(read_only=True)
    product = LifecycleProductRefSerializer(read_only=True, allow_null=True)
    reasons = serializers.ListField(child=serializers.CharField(), read_only=True)
    milestone_ids = serializers.ListField(child=serializers.UUIDField(), read_only=True)
    exception = LifecycleExceptionRefSerializer(read_only=True, allow_null=True)
    # Blank when no milestone governs the status (Unknown, Not applicable, statements).
    milestone_type = serializers.ChoiceField(
        choices=MilestoneType.choices, allow_blank=True, read_only=True
    )
    support_level = serializers.ChoiceField(
        choices=LifecycleAssessment.SupportLevel.choices, allow_blank=True, read_only=True
    )
    evidence_quality = serializers.ChoiceField(
        choices=LifecycleAssessment.EvidenceQuality.choices, allow_blank=True, read_only=True
    )

    class Meta:
        model = LifecycleAssessment
        fields = [
            "id",
            "asset",
            "dimension",
            "status",
            "effective_status",
            "product",
            "support_level",
            "milestone_type",
            "milestone_date",
            "days_remaining",
            "threshold_days",
            "evidence_quality",
            "milestone_ids",
            "reasons",
            "exception",
            "assessed_at",
        ]
        read_only_fields = fields


class LifecycleAssessmentHistorySerializer(serializers.ModelSerializer):
    reasons = serializers.ListField(child=serializers.CharField(), read_only=True)

    class Meta:
        model = LifecycleAssessmentHistory
        fields = [
            "dimension",
            "status",
            "effective_status",
            "product_label",
            "milestone_type",
            "milestone_date",
            "reasons",
            "recorded_at",
        ]
        read_only_fields = fields


class AssetLifecycleSerializer(serializers.Serializer):
    assessments = LifecycleAssessmentSerializer(many=True)
    matches = LifecycleMatchSerializer(many=True)
    exceptions = LifecycleExceptionSerializer(many=True)
    history = LifecycleAssessmentHistorySerializer(many=True)
    evidence = LifecycleMilestoneSerializer(many=True)


class LifecycleSummaryRowSerializer(serializers.Serializer):
    dimension = serializers.ChoiceField(choices=Dimension.choices)
    effective_status = serializers.ChoiceField(choices=Status.choices)
    count = serializers.IntegerField()


class LifecyclePolicySerializer(serializers.Serializer):
    warning_days = serializers.ListField(child=serializers.IntegerField())
    count_extended_support = serializers.BooleanField()
    max_exception_days = serializers.IntegerField()
    today = serializers.DateField()
