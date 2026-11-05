"""Scoped report queries shared by previews, encrypted exports and scheduled links."""

import json

from django.db.models import CharField, Count, Exists, OuterRef, Q, Subquery, Value
from django.db.models.functions import Coalesce
from django.utils import timezone
from rest_framework import serializers

from apps.assets.selectors import apply_filters, visible_assets
from apps.groups.models import AssetGroupMembership
from apps.groups.views import visible_groups
from apps.lifecycle.models import Dimension, LifecycleAssessment, Status
from apps.reconciliation.models import SourceLink
from config.api import ApiError

CATALOGUE = {
    "inventory": ("Inventory breakdown", "assets.view"),
    "lifecycle": ("Lifecycle evidence", "lifecycle.view"),
    "coverage": ("Observed source coverage", "discovery.view"),
    "groups": ("Group replacement and ownership", "groups.view"),
}
FILTER_KEYS = ("site", "group", "q", "breakdown", "dimension", "status", "coverage")
COLUMNS = {
    "inventory": [
        ("label", "Breakdown"),
        ("total", "Assets"),
        ("model_unknown", "Model unknown"),
        ("not_observed", "No source link"),
    ],
    "lifecycle": [
        ("id", "Asset ID"),
        ("name", "Asset"),
        ("site", "Site"),
        ("dimension", "Dimension"),
        ("status", "Effective status"),
        ("base_status", "Evidence status"),
        ("milestone", "Milestone"),
        ("date", "Milestone date"),
        ("quality", "Evidence quality"),
        ("assessment_id", "Assessment ID"),
        ("product_id", "Product ID"),
        ("milestone_ids", "Milestone IDs (JSON array)"),
        ("assessed_at", "Assessed at"),
    ],
    "coverage": [
        ("id", "Asset ID"),
        ("name", "Asset"),
        ("site", "Site"),
        ("category", "Category"),
        ("endpoint_central", "Endpoint Central link"),
        ("defender", "Defender link"),
    ],
    "groups": [
        ("id", "Group ID"),
        ("name", "Group"),
        ("kind", "Kind"),
        ("members", "Visible members"),
        ("eos", "Verified EOS assets"),
        ("owner_missing", "Assets without owner"),
    ],
}
NOTES = {
    "inventory": "Live assets in your scope. Owner breakdown requires personal-data permission.",
    "lifecycle": "One selected dimension per asset. Missing assessments remain Unknown. "
    "Effective status may include an exception; dates and evidence are recorded results.",
    "coverage": "Recorded links do not prove agent installation or absence. Stale/disabled links "
    "and Not reported are distinct. Select an eligible site/group; no compliance is inferred.",
    "groups": "Only visible, live members. EOS needs a recorded effective EOS assessment "
    "with evidence. Groups never widen site access.",
}


class ReportFilters(serializers.Serializer):
    coverage = serializers.ChoiceField(
        choices=["any_gap", "endpoint_central_gap", "defender_gap"], required=False
    )
    site = serializers.UUIDField(required=False)
    group = serializers.UUIDField(required=False)
    q = serializers.CharField(required=False, max_length=200, allow_blank=True)
    breakdown = serializers.ChoiceField(
        choices=["site", "category", "manufacturer", "owner"], required=False
    )
    dimension = serializers.ChoiceField(choices=Dimension.choices, required=False)
    status = serializers.ChoiceField(choices=Status.choices, required=False)


def can_view(user, kind, filters=None):
    codes = user.permission_codes()
    return (
        user.is_active
        and kind in CATALOGUE
        and {"reports.view", "assets.view", CATALOGUE[kind][1]} <= codes
        and (not (filters or {}).get("group") or "groups.view" in codes)
        and ((filters or {}).get("breakdown") != "owner" or "exports.personal" in codes)
    )


def clean_filters(user, kind, values):
    if kind not in CATALOGUE:
        raise ApiError("NOT_FOUND", "Unknown report.", 404)
    unknown = set(values) - set(FILTER_KEYS)
    if unknown:
        raise serializers.ValidationError(
            {key: ["Unknown report filter."] for key in sorted(unknown)}
        )
    serializer = ReportFilters(data=values)
    serializer.is_valid(raise_exception=True)
    filters = {key: str(value) for key, value in serializer.validated_data.items()}
    if not can_view(user, kind, filters):
        raise ApiError("PERMISSION_DENIED", "You cannot view this report or breakdown.", 403)
    if kind != "lifecycle" and ("dimension" in filters or "status" in filters):
        raise serializers.ValidationError(
            "Dimension and lifecycle status apply only to lifecycle reports."
        )
    if kind != "inventory" and "breakdown" in filters:
        raise serializers.ValidationError("Breakdown applies only to inventory reports.")
    if kind != "coverage" and "coverage" in filters:
        raise serializers.ValidationError("Coverage filters apply only to source coverage reports.")
    return filters


def columns_for(kind, user=None):
    from apps.exports.families import Column

    columns = list(COLUMNS[kind])
    if kind == "groups":
        columns.append(("owner", "Group owner"))
    return [
        Column(key, label, lambda row, ctx, k=key: row.get(k, ""), personal=key == "owner")
        for key, label in columns
    ]


def dataset(user, kind, filters):
    filters = clean_filters(user, kind, filters)
    asset_keys = ("site",) if kind == "groups" else ("site", "q")
    assets = apply_filters(
        visible_assets(user), {key: filters[key] for key in asset_keys if key in filters}
    )
    if group := filters.get("group"):
        members = AssetGroupMembership.objects.filter(
            group_id=group, group__archived_at__isnull=True, removed_at__isnull=True
        )
        assets = assets.filter(pk__in=members.values("asset_id"))
    if kind == "inventory":
        breakdown = filters.get("breakdown", "site")
        fields = {
            "site": ("site_id", "site__name"),
            "category": ("category_id", "category__name"),
            "manufacturer": ("manufacturer",),
            "owner": ("owner_id", "owner__display_name"),
        }[breakdown]
        qs = (
            assets.order_by()
            .values(*fields)
            .annotate(
                total=Count("pk"),
                model_unknown=Count("pk", filter=Q(model="")),
                not_observed=Count("pk", filter=Q(source_count=0)),
            )
            .order_by(*fields)
        )
        return qs, lambda obj: {
            "label": obj[fields[-1]] or "Not recorded",
            "total": obj["total"],
            "model_unknown": obj["model_unknown"],
            "not_observed": obj["not_observed"],
        }
    if kind == "lifecycle":
        dimension = filters.get("dimension", "hardware")
        assessment = LifecycleAssessment.objects.filter(
            asset_id=OuterRef("pk"), dimension=dimension
        )
        fields = (
            "status",
            "effective_status",
            "milestone_type",
            "milestone_date",
            "evidence_quality",
            "id",
            "product_id",
            "milestone_ids",
            "assessed_at",
        )
        qs = assets.annotate(
            **{f"r_{field}": Subquery(assessment.values(field)[:1]) for field in fields}
        )
        qs = qs.annotate(
            report_status=Coalesce("r_effective_status", Value("unknown"), output_field=CharField())
        )
        if status := filters.get("status"):
            qs = qs.filter(report_status=status)

        def lifecycle_row(obj):
            return {
                "id": str(obj.pk),
                "name": obj.name,
                "site": obj.site.code,
                "dimension": dimension,
                "status": obj.report_status,
                "base_status": obj.r_status or "unknown",
                "milestone": obj.r_milestone_type or "",
                "date": obj.r_milestone_date.isoformat() if obj.r_milestone_date else "",
                "quality": obj.r_evidence_quality or "",
                "assessment_id": str(obj.r_id or ""),
                "product_id": str(obj.r_product_id or ""),
                "milestone_ids": json.dumps(obj.r_milestone_ids or []),
                "assessed_at": obj.r_assessed_at.isoformat() if obj.r_assessed_at else "",
            }

        return qs.order_by("name", "pk"), lifecycle_row
    if kind == "coverage":
        annotations = {}
        for provider in ("endpoint_central", "defender"):
            links = SourceLink.objects.filter(
                asset_id=OuterRef("pk"), instance__source_id=provider
            ).exclude(status="unlinked")
            annotations[f"r_{provider}_any"] = Exists(links)
            annotations[f"r_{provider}_active"] = Exists(
                links.filter(status="active", instance__is_enabled=True).exclude(
                    instance__status="disconnected"
                )
            )
        qs = assets.annotate(**annotations).order_by("name", "pk")
        if filters.get("coverage") == "any_gap":
            qs = qs.filter(Q(r_endpoint_central_active=False) | Q(r_defender_active=False))
        elif filters.get("coverage"):
            provider = filters["coverage"].removesuffix("_gap")
            qs = qs.filter(**{f"r_{provider}_active": False})

        def coverage_row(obj):
            result = {
                "id": str(obj.pk),
                "name": obj.name,
                "site": obj.site.code,
                "category": obj.category.name,
            }
            for provider in ("endpoint_central", "defender"):
                result[provider] = (
                    "Reported (active link)"
                    if getattr(obj, f"r_{provider}_active")
                    else "Stale or disabled link"
                    if getattr(obj, f"r_{provider}_any")
                    else "Not reported"
                )
            return result

        return qs, coverage_row
    members = Q(memberships__removed_at__isnull=True, memberships__asset_id__in=assets.values("pk"))
    eos = (
        LifecycleAssessment.objects.filter(effective_status="eos")
        .exclude(evidence_quality="")
        .values("asset_id")
    )
    groups = (
        visible_groups(user).filter(pk=filters["group"])
        if filters.get("group")
        else visible_groups(user)
    )
    if q := filters.get("q"):
        groups = groups.filter(name__icontains=q)
    qs = groups.annotate(
        r_members=Count("memberships", filter=members, distinct=True),
        r_eos=Count(
            "memberships", filter=members & Q(memberships__asset_id__in=eos), distinct=True
        ),
        r_no_owner=Count(
            "memberships", filter=members & Q(memberships__asset__owner__isnull=True), distinct=True
        ),
    ).order_by("name", "pk")
    personal = "exports.personal" in user.permission_codes()
    return qs, lambda obj: {
        "id": str(obj.pk),
        "name": obj.name,
        "kind": obj.kind,
        "members": obj.r_members,
        "eos": obj.r_eos,
        "owner_missing": obj.r_no_owner,
        **({"owner": obj.owner.display_name if obj.owner else ""} if personal else {}),
    }


def preview(user, kind, filters, offset=0, limit=50):
    qs, build = dataset(user, kind, filters)
    columns = [
        column
        for column in columns_for(kind)
        if not column.personal or "exports.personal" in user.permission_codes()
    ]
    return {
        "report": kind,
        "label": CATALOGUE[kind][0],
        "note": NOTES[kind],
        "generated_at": timezone.now(),
        "count": qs.count(),
        "columns": [{"key": c.key, "label": c.label} for c in columns],
        "rows": [build(obj) for obj in qs[offset : offset + limit]],
        "offset": offset,
        "limit": limit,
    }


def export_data(job, user, maximum):
    from apps.exports.families import ExportData, ExportTooLarge, Table

    kind = job.family.removeprefix("report_")
    qs, build = dataset(user, kind, job.filters if job.scope == "filtered" else {})
    if qs.count() > maximum:
        raise ExportTooLarge("Report exceeds the export limit. Narrow its site or group filters.")
    columns = columns_for(kind)
    wanted = set(job.columns)
    columns = [c for c in columns if not wanted or c.key in wanted]
    masked = [
        c.key for c in columns if c.personal and "exports.personal" not in user.permission_codes()
    ]
    columns = [c for c in columns if c.key not in masked]
    rows = []
    for obj in qs.iterator(chunk_size=1000):
        row = build(obj)
        rows.append({c.key: row.get(c.key, "") for c in columns})
    return ExportData(Table(job.family, columns, rows), {}, {}, masked)
