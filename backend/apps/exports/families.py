"""Export families: which columns and related tables exist and how rows are built (ASM-52).

Rows always start from the viewer's own scoped queryset (``visible_assets`` /
``visible_groups``), so an export can never contain more than the user can open in the UI.
Personal-data columns (people's names and usernames) are dropped at query time unless the
user holds ``exports.personal`` (docs/14); they are listed in ``masked_columns``.

1:N data (hostnames, interfaces, IP addresses, group memberships) is never flattened into
one field: each is its own table keyed by the parent ID (CSV file, XLSX sheet) or a nested
list (JSON).
"""

from collections.abc import Callable, Iterator
from dataclasses import dataclass, field

from apps.accounts import catalog
from apps.assets.models import (
    AssetHostname,
    AssetInterface,
    AssetIPAddress,
    CustomFieldDefinition,
)
from apps.assets.selectors import FILTER_KEYS, apply_filters, visible_assets
from apps.assets.tree import CategoryTree
from apps.groups.models import AssetGroupMembership

BATCH = 1000


def _iso(value) -> str:
    return value.isoformat() if value else ""


def _user(user) -> str:
    return user.username if user else ""


def _person(user) -> str:
    return user.display_name if user else ""


@dataclass(frozen=True)
class Column:
    key: str
    label: str
    get: Callable
    personal: bool = False


@dataclass(frozen=True)
class Related:
    key: str
    label: str
    parent_key: str
    columns: tuple[Column, ...]
    permission: str = ""


@dataclass
class Table:
    name: str
    columns: list[Column]
    rows: list[dict] = field(default_factory=list)


@dataclass
class ExportData:
    main: Table
    related: dict[str, Table]
    parent_key: dict[str, str]
    masked: list[str]


class ExportTooLarge(Exception):
    pass


# --- Assets -----------------------------------------------------------------------------------

ASSET_COLUMNS: tuple[Column, ...] = (
    Column("id", "Asset ID", lambda a, c: str(a.pk)),
    Column("name", "Name", lambda a, c: a.name),
    Column("asset_tag", "Asset tag", lambda a, c: a.asset_tag or ""),
    Column("category", "Category", lambda a, c: c["tree"].path(a.category_id)),
    Column("manufacturer", "Manufacturer", lambda a, c: a.manufacturer),
    Column("model", "Model", lambda a, c: a.model),
    Column("serial_number", "Serial number", lambda a, c: a.serial_number),
    Column("os_name", "Operating system", lambda a, c: a.os_name),
    Column("os_version", "OS version", lambda a, c: a.os_version),
    Column("firmware_version", "Firmware", lambda a, c: a.firmware_version),
    Column("primary_hostname", "Primary hostname", lambda a, c: a.primary_hostname or ""),
    Column("primary_ip", "Primary IP", lambda a, c: a.primary_ip or ""),
    Column("site", "Site code", lambda a, c: a.site.code),
    Column("site_name", "Site", lambda a, c: a.site.name),
    Column("location", "Location", lambda a, c: a.location.name if a.location else ""),
    Column("department", "Department", lambda a, c: a.department.name if a.department else ""),
    Column("owner", "Owner username", lambda a, c: _user(a.owner), personal=True),
    Column("owner_name", "Owner", lambda a, c: _person(a.owner), personal=True),
    Column("business_status", "Business status", lambda a, c: a.business_status),
    Column("observation_status", "Observation status", lambda a, c: a.observation_status),
    Column("support_status", "Support status", lambda a, c: a.support_status),
    Column("last_seen_at", "Last seen by a source", lambda a, c: _iso(a.last_seen_at)),
    Column("source_count", "Linked sources", lambda a, c: a.source_count),
    Column("notes", "Notes", lambda a, c: a.notes),
    Column("archived_at", "Archived at", lambda a, c: _iso(a.archived_at)),
    Column("created_at", "Created at", lambda a, c: _iso(a.created_at)),
    Column("modified_at", "Modified at", lambda a, c: _iso(a.modified_at)),
    Column("modified_by", "Modified by", lambda a, c: _user(a.modified_by), personal=True),
    Column("version", "Version", lambda a, c: a.version),
)

_EVIDENCE = (
    Column("source", "Source", lambda r, c: r.source),
    Column("source_ref", "Source reference", lambda r, c: r.source_ref),
    Column("observed_at", "Observed at", lambda r, c: _iso(r.observed_at)),
)
_ASSET_ID = Column("asset_id", "Asset ID", lambda r, c: str(r.asset_id))

ASSET_RELATED: tuple[Related, ...] = (
    Related(
        "hostnames",
        "Hostnames",
        "asset_id",
        (
            _ASSET_ID,
            Column("hostname", "Hostname", lambda r, c: r.hostname),
            Column("is_primary", "Primary", lambda r, c: r.is_primary),
            *_EVIDENCE,
        ),
    ),
    Related(
        "interfaces",
        "Interfaces and MAC addresses",
        "asset_id",
        (
            _ASSET_ID,
            Column("interface_id", "Interface ID", lambda r, c: str(r.pk)),
            Column("name", "Interface", lambda r, c: r.name),
            Column("mac_address", "MAC address", lambda r, c: r.mac_address),
            *_EVIDENCE,
        ),
    ),
    Related(
        "ip_addresses",
        "IP addresses",
        "asset_id",
        (
            _ASSET_ID,
            Column("address", "IP address", lambda r, c: r.address),
            Column("interface_id", "Interface ID", lambda r, c: str(r.interface_id or "")),
            Column("is_primary", "Primary", lambda r, c: r.is_primary),
            Column("vrf", "VRF", lambda r, c: r.vrf),
            *_EVIDENCE,
        ),
    ),
    Related(
        "groups",
        "Group memberships",
        "asset_id",
        (
            _ASSET_ID,
            Column("group_id", "Group ID", lambda m, c: str(m.group_id)),
            Column("group_name", "Group", lambda m, c: m.group.name),
            Column("membership_source", "Membership", lambda m, c: m.source),
            Column("added_at", "Added at", lambda m, c: _iso(m.added_at)),
        ),
        permission=catalog.GROUPS_VIEW,
    ),
)


def _custom_columns() -> list[Column]:
    keys = sorted(
        set(CustomFieldDefinition.objects.filter(is_active=True).values_list("key", flat=True))
    )
    labels = dict(CustomFieldDefinition.objects.filter(is_active=True).values_list("key", "label"))
    return [
        Column(f"cf.{key}", labels.get(key, key), lambda a, c, k=key: a.custom_fields.get(k, ""))
        for key in keys
    ]


def _asset_queryset(user, scope: str, filters: dict, ids: list):
    qs = visible_assets(user).select_related("modified_by")
    if scope == "selected":
        return apply_filters(qs, {"archived": "include"}).filter(pk__in=ids)
    if scope == "all":
        return apply_filters(qs, {"archived": "include"})
    params = {key: str(value) for key, value in filters.items() if key in FILTER_KEYS}
    return apply_filters(qs, params, CategoryTree())


def _asset_related_rows(key: str, asset_ids: list) -> Iterator:
    if key == "hostnames":
        return AssetHostname.objects.filter(asset_id__in=asset_ids).order_by(
            "asset_id", "-is_primary", "hostname"
        )
    if key == "interfaces":
        return AssetInterface.objects.filter(asset_id__in=asset_ids).order_by("asset_id", "name")
    if key == "ip_addresses":
        return AssetIPAddress.objects.filter(asset_id__in=asset_ids).order_by(
            "asset_id", "-is_primary", "address"
        )
    return (
        AssetGroupMembership.objects.filter(
            asset_id__in=asset_ids, removed_at__isnull=True, group__archived_at__isnull=True
        )
        .select_related("group")
        .order_by("asset_id", "group__name")
    )


# --- Groups -----------------------------------------------------------------------------------

GROUP_COLUMNS: tuple[Column, ...] = (
    Column("id", "Group ID", lambda g, c: str(g.pk)),
    Column("name", "Name", lambda g, c: g.name),
    Column("kind", "Kind", lambda g, c: g.kind),
    Column("description", "Description", lambda g, c: g.description),
    Column("parent", "Parent group", lambda g, c: g.parent.name if g.parent else ""),
    Column("owner", "Owner username", lambda g, c: _user(g.owner), personal=True),
    Column("rule_version", "Rule version", lambda g, c: g.rule_version or ""),
    Column("member_count", "Members you can see", lambda g, c: g.member_count),
    Column("last_evaluated_at", "Last evaluated", lambda g, c: _iso(g.last_evaluated_at)),
    Column("created_at", "Created at", lambda g, c: _iso(g.created_at)),
    Column("modified_at", "Modified at", lambda g, c: _iso(g.modified_at)),
)

GROUP_RELATED: tuple[Related, ...] = (
    Related(
        "members",
        "Members",
        "group_id",
        (
            Column("group_id", "Group ID", lambda m, c: str(m.group_id)),
            Column("asset_id", "Asset ID", lambda m, c: str(m.asset_id)),
            Column("asset_name", "Asset", lambda m, c: m.asset.name),
            Column("asset_tag", "Asset tag", lambda m, c: m.asset.asset_tag or ""),
            Column("site", "Site code", lambda m, c: m.asset.site.code),
            Column("membership_source", "Membership", lambda m, c: m.source),
            Column("rule_version", "Rule version", lambda m, c: m.rule_version or ""),
            Column("added_at", "Added at", lambda m, c: _iso(m.added_at)),
            Column("added_by", "Added by", lambda m, c: _user(m.added_by), personal=True),
        ),
    ),
)


# --- Registry ---------------------------------------------------------------------------------


@dataclass(frozen=True)
class Family:
    code: str
    label: str
    permission: str
    description: str
    filter_keys: tuple[str, ...]
    related: tuple[Related, ...]

    def columns(self) -> list[Column]:
        if self.code == "assets":
            return [*ASSET_COLUMNS, *_custom_columns()]
        return list(GROUP_COLUMNS)


FAMILIES: dict[str, Family] = {
    "assets": Family(
        "assets",
        "Assets",
        catalog.ASSETS_VIEW,
        "Assets in your sites with provenance and source freshness; related tables keep "
        "hostnames, interfaces/MACs, IPs and group memberships separate.",
        FILTER_KEYS,
        ASSET_RELATED,
    ),
    "groups": Family(
        "groups",
        "Asset groups",
        catalog.GROUPS_VIEW,
        "Groups with their members; members outside your sites are never included.",
        (),
        GROUP_RELATED,
    ),
}


def allowed_related(family: Family, permissions: set[str]) -> list[Related]:
    return [r for r in family.related if not r.permission or r.permission in permissions]


def build(job, user, max_rows: int) -> ExportData:
    """Rows for ``job`` as ``user`` sees the data right now."""
    family = FAMILIES[job.family]
    permissions = user.permission_codes()
    personal = catalog.EXPORTS_PERSONAL in permissions
    available = family.columns()
    wanted = set(job.columns)
    columns = [c for c in available if not wanted or c.key in wanted]
    masked = [c.key for c in columns if c.personal and not personal]
    columns = [c for c in columns if not c.personal or personal]
    related = [r for r in allowed_related(family, permissions) if r.key in set(job.related)]
    ctx = {"tree": CategoryTree()}

    if family.code == "assets":
        qs = _asset_queryset(user, job.scope, job.filters, job.ids).order_by("name", "pk")
    else:
        qs = _group_queryset(user, job.scope, job.ids).order_by("name", "pk")
    if qs.count() > max_rows:
        raise ExportTooLarge(
            f"This export would contain more than {max_rows:,} records. Narrow the filters."
        )

    main = Table(family.code, columns)
    tables = {
        r.key: Table(
            r.key,
            [c for c in r.columns if not c.personal or personal],
        )
        for r in related
    }
    for rel in related:
        masked += [f"{rel.key}.{c.key}" for c in rel.columns if c.personal and not personal]

    ids_batch: list = []
    for obj in qs.iterator(chunk_size=BATCH):
        main.rows.append({c.key: c.get(obj, ctx) for c in columns})
        ids_batch.append(obj.pk)
        if len(ids_batch) >= BATCH:
            _fill_related(family, user, related, tables, ids_batch, ctx)
            ids_batch = []
    if ids_batch:
        _fill_related(family, user, related, tables, ids_batch, ctx)

    return ExportData(
        main=main,
        related=tables,
        parent_key={r.key: r.parent_key for r in related},
        masked=masked,
    )


def _group_queryset(user, scope: str, ids: list):
    from apps.groups.views import visible_groups

    qs = visible_groups(user).select_related("owner")
    return qs.filter(pk__in=ids) if scope == "selected" else qs


def _fill_related(family, user, related, tables, parent_ids, ctx) -> None:
    for rel in related:
        table = tables[rel.key]
        if family.code == "assets":
            rows = _asset_related_rows(rel.key, parent_ids)
        else:
            visible = visible_assets(user).filter(archived_at__isnull=True).values("pk")
            rows = (
                AssetGroupMembership.objects.filter(
                    group_id__in=parent_ids, removed_at__isnull=True, asset__in=visible
                )
                .select_related("asset__site", "added_by")
                .order_by("group_id", "asset__name")
            )
        for row in rows:
            table.rows.append({c.key: c.get(row, ctx) for c in table.columns})
