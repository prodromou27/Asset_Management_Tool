"""The only entry point for reading assets. List, detail, history, saved views and
future export/report jobs must start from `visible_assets(user)` so site scope can
never be bypassed by URL, filter, saved view or payload."""

from django.apps import apps
from django.db.models import Count, Exists, IntegerField, OuterRef, Q, Subquery, Value
from django.db.models.functions import Coalesce

from apps.organizations import scope

from .models import Asset, AssetHostname, AssetInterface, AssetIPAddress
from .network import normalize_ip, normalize_mac
from .tree import CategoryTree


def _source_links():
    # Resolved lazily: reconciliation depends on assets, not the other way round.
    model = apps.get_model("reconciliation", "SourceLink")
    return model.objects.filter(asset=OuterRef("pk")).exclude(status="unlinked")


def visible_assets(user):
    primary_hostname = AssetHostname.objects.filter(asset=OuterRef("pk")).order_by(
        "-is_primary", "hostname"
    )
    primary_ip = AssetIPAddress.objects.filter(asset=OuterRef("pk")).order_by(
        "-is_primary", "address"
    )
    links = _source_links()
    qs = Asset.objects.select_related(
        "category", "site", "location", "department", "owner", "archived_by"
    ).annotate(
        primary_hostname=Subquery(primary_hostname.values("hostname")[:1]),
        primary_ip=Subquery(primary_ip.values("address")[:1]),
        last_seen_at=Subquery(links.order_by("-last_seen_at").values("last_seen_at")[:1]),
        source_count=Coalesce(
            Subquery(
                links.order_by().values("asset").annotate(n=Count("pk")).values("n")[:1],
                output_field=IntegerField(),
            ),
            Value(0),
        ),
    )
    return scope.restrict(qs, user, field="site")


ORDERING = {
    "name": ("name", "id"),
    "-name": ("-name", "-id"),
    "asset_tag": ("asset_tag", "id"),
    "-asset_tag": ("-asset_tag", "-id"),
    "modified_at": ("modified_at", "id"),
    "-modified_at": ("-modified_at", "-id"),
    "created_at": ("created_at", "id"),
    "-created_at": ("-created_at", "-id"),
}

ARCHIVED_MODES = ("exclude", "include", "only")

# Every filter key apply_filters understands; saved views are validated against it.
FILTER_KEYS = (
    "q",
    "category",
    "site",
    "location",
    "department",
    "owner",
    "manufacturer",
    "business_status",
    "support_status",
    "observation_status",
    "source",
    "archived",
)


def apply_filters(qs, params, tree: CategoryTree | None = None):
    """Typed allowlist of filters. Unknown parameters are ignored. No joins that
    multiply rows: related-table conditions use EXISTS, so no DISTINCT is needed."""
    archived = params.get("archived", "exclude")
    if archived == "exclude":
        qs = qs.filter(archived_at__isnull=True)
    elif archived == "only":
        qs = qs.filter(archived_at__isnull=False)

    try:
        if category := params.get("category"):
            tree = tree or CategoryTree()
            qs = qs.filter(category_id__in=tree.descendants(_uuid(category)))
        if site := params.get("site"):
            qs = qs.filter(site_id__in=scope.descendants({_uuid(site)}))
        for name in ("location", "department", "owner"):
            if value := params.get(name):
                qs = qs.filter(**{f"{name}_id": _uuid(value)})
        if source := params.get("source"):
            qs = qs.filter(Exists(_source_links().filter(instance_id=_uuid(source))))
    except ValueError:
        return qs.none()

    for name, choices in (
        ("business_status", Asset.BusinessStatus.values),
        ("support_status", Asset.SupportStatus.values),
        ("observation_status", Asset.ObservationStatus.values),
    ):
        if value := params.get(name):
            qs = qs.filter(**{name: value}) if value in choices else qs.none()
    if manufacturer := params.get("manufacturer", "").strip():
        qs = qs.filter(manufacturer__iexact=manufacturer)
    if q := params.get("q", "").strip()[:200]:
        qs = qs.filter(_search(q))
    return qs


def _search(q: str) -> Q:
    """Substring match on the asset's own text fields (trigram-indexed on PostgreSQL),
    plus hostnames, and exact IP/MAC when the query parses as one."""
    condition = (
        Q(name__icontains=q)
        | Q(asset_tag__icontains=q)
        | Q(serial_number__icontains=q)
        | Q(manufacturer__icontains=q)
        | Q(model__icontains=q)
        | Exists(AssetHostname.objects.filter(asset=OuterRef("pk"), hostname__icontains=q.lower()))
    )
    try:
        address = normalize_ip(q)
        condition |= Exists(AssetIPAddress.objects.filter(asset=OuterRef("pk"), address=address))
    except ValueError:
        pass
    try:
        mac = normalize_mac(q)
        if mac:
            condition |= Exists(
                AssetInterface.objects.filter(asset=OuterRef("pk"), mac_address=mac)
            )
    except ValueError:
        pass
    return condition


def _uuid(value: str):
    from uuid import UUID

    return UUID(str(value))
