"""The only entry point for reading assets. List, detail, history and future
export/report jobs must start from `visible_assets(user)` so site scope can never
be bypassed by URL, filter or payload."""

from django.db.models import OuterRef, Q, Subquery

from apps.organizations import scope

from .models import Asset, AssetHostname, AssetIPAddress
from .network import normalize_ip, normalize_mac
from .tree import CategoryTree


def visible_assets(user):
    primary_hostname = AssetHostname.objects.filter(asset=OuterRef("pk")).order_by(
        "-is_primary", "hostname"
    )
    primary_ip = AssetIPAddress.objects.filter(asset=OuterRef("pk")).order_by(
        "-is_primary", "address"
    )
    qs = Asset.objects.select_related(
        "category", "site", "location", "department", "owner", "archived_by"
    ).annotate(
        primary_hostname=Subquery(primary_hostname.values("hostname")[:1]),
        primary_ip=Subquery(primary_ip.values("address")[:1]),
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


def apply_filters(qs, params, tree: CategoryTree | None = None):
    """Typed allowlist of filters. Unknown parameters are ignored."""
    archived = params.get("archived", "exclude")
    if archived == "exclude":
        qs = qs.filter(archived_at__isnull=True)
    elif archived == "only":
        qs = qs.filter(archived_at__isnull=False)

    if category := params.get("category"):
        tree = tree or CategoryTree()
        try:
            qs = qs.filter(category_id__in=tree.descendants(_uuid(category)))
        except ValueError:
            return qs.none()
    if site := params.get("site"):
        try:
            qs = qs.filter(site_id__in=scope.descendants({_uuid(site)}))
        except ValueError:
            return qs.none()
    for name in ("location", "department", "owner"):
        if value := params.get(name):
            try:
                qs = qs.filter(**{f"{name}_id": _uuid(value)})
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
    return qs.distinct()


def _search(q: str) -> Q:
    condition = (
        Q(name__icontains=q)
        | Q(asset_tag__icontains=q)
        | Q(serial_number__icontains=q)
        | Q(manufacturer__icontains=q)
        | Q(model__icontains=q)
        | Q(hostnames__hostname__icontains=q.lower())
    )
    try:
        condition |= Q(ip_addresses__address=normalize_ip(q))
    except ValueError:
        pass
    try:
        condition |= Q(interfaces__mac_address=normalize_mac(q))
    except ValueError:
        pass
    return condition


def _uuid(value: str):
    from uuid import UUID

    return UUID(str(value))
