"""Apply a linked observation to its canonical asset under field authority rules.

- Only TECHNICAL_FIELDS are written; business fields are never touched.
- A manually locked field is never overwritten; a differing value opens a conflict.
- Between sources, FieldAuthorityPolicy precedence decides, but only while the
  higher-precedence source's link is still active (a stale source loses authority).
- Missing values never clear existing data (missing = unknown, docs/05).
- Discovered identifiers are replaced per source link; manual rows are untouched.
"""

from datetime import datetime

from django.db.models import F

from apps.assets.models import (
    TECHNICAL_FIELDS,
    Asset,
    AssetHistoryEntry,
    AssetHostname,
    AssetInterface,
    AssetIPAddress,
    FieldLock,
    FieldProvenance,
)
from apps.assets.services import network_snapshot
from apps.integrations.models import FieldAuthorityPolicy

from .models import FieldConflict, SourceLink


def link_key(instance, external_id: str) -> str:
    return f"{instance.source_key}{external_id}"


def _parse(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _open_conflict(asset, field, current, observed, reason, instance, observation) -> bool:
    conflict = FieldConflict.objects.filter(
        asset=asset, field=field, instance=instance, status=FieldConflict.Status.OPEN
    ).first()
    if conflict is None:
        FieldConflict.objects.create(
            asset=asset,
            field=field,
            current_value=current or "",
            observed_value=observed,
            reason=reason,
            instance=instance,
            observation=observation,
        )
        return True
    if conflict.observed_value != observed or conflict.current_value != (current or ""):
        conflict.observed_value = observed
        conflict.current_value = current or ""
        conflict.observation = observation
        conflict.save(
            update_fields=["observed_value", "current_value", "observation", "modified_at"]
        )
    return False


def _sync_identifiers(asset, instance, external_id, normalized, observed_at) -> None:
    key = link_key(instance, external_id)
    source = instance.source_id

    wanted_hosts = list(normalized.get("hostnames") or [])
    hosts = asset.hostnames.filter(source_ref=key)
    hosts.exclude(hostname__in=wanted_hosts).delete()
    existing = set(hosts.values_list("hostname", flat=True))
    hosts.update(observed_at=observed_at)
    AssetHostname.objects.bulk_create(
        AssetHostname(
            asset=asset, hostname=h, source=source, source_ref=key, observed_at=observed_at
        )
        for h in wanted_hosts
        if h not in existing
    )

    wanted_ifaces = {i["name"]: i.get("mac") or "" for i in normalized.get("interfaces") or []}
    ifaces = asset.interfaces.filter(source_ref=key)
    ifaces.exclude(name__in=wanted_ifaces).delete()
    by_name = {i.name: i for i in ifaces}
    for name, mac in wanted_ifaces.items():
        row = by_name.get(name)
        if row is None:
            by_name[name] = AssetInterface.objects.create(
                asset=asset,
                name=name,
                mac_address=mac,
                source=source,
                source_ref=key,
                observed_at=observed_at,
            )
        else:
            row.mac_address = mac
            row.observed_at = observed_at
            row.save(update_fields=["mac_address", "observed_at"])

    wanted_ips = {
        (r["address"], r.get("vrf") or ""): r for r in normalized.get("ip_addresses") or []
    }
    ips = asset.ip_addresses.filter(source_ref=key)
    for row in ips:
        if (row.address, row.vrf) not in wanted_ips:
            row.delete()
    existing_ips = {(r.address, r.vrf): r for r in asset.ip_addresses.filter(source_ref=key)}
    for (address, vrf), row in wanted_ips.items():
        interface = by_name.get(row.get("interface") or "")
        current = existing_ips.get((address, vrf))
        if current is None:
            AssetIPAddress.objects.create(
                asset=asset,
                address=address,
                vrf=vrf,
                site_id=row.get("site"),
                interface=interface,
                source=source,
                source_ref=key,
                observed_at=observed_at,
            )
        else:
            current.interface = interface
            current.observed_at = observed_at
            current.save(update_fields=["interface", "observed_at"])


def apply_observation(asset: Asset, link: SourceLink, observation) -> dict:
    """Returns {"changes": {...}, "conflicts_opened": int}."""
    instance = link.instance
    normalized = observation.normalized
    observed_at = _parse(normalized["observed_at"])
    policy = FieldAuthorityPolicy.load()
    locks = set(FieldLock.objects.filter(asset=asset).values_list("field", flat=True))
    provenance = {
        p.field: p for p in FieldProvenance.objects.filter(asset=asset).select_related("instance")
    }
    active_instances = set(
        SourceLink.objects.filter(asset=asset, status=SourceLink.Status.ACTIVE).values_list(
            "instance_id", flat=True
        )
    )

    before_network = network_snapshot(asset)
    changes: dict = {}
    conflicts_opened = 0

    for field in TECHNICAL_FIELDS:
        value = normalized.get(field)
        if value in (None, ""):
            continue
        current = getattr(asset, field)
        if field in locks:
            if current != value:
                conflicts_opened += _open_conflict(
                    asset, field, current, value, "locked", instance, observation
                )
            continue
        prov = provenance.get(field)
        if (
            prov is not None
            and prov.kind == FieldProvenance.Kind.DISCOVERY
            and prov.instance_id != instance.pk
            and prov.instance_id in active_instances
            and policy.rank(field, prov.instance.source_id) < policy.rank(field, instance.source_id)
        ):
            continue  # a fresher higher-authority source owns this field; kept as evidence only
        if current != value:
            changes[field] = {"before": current, "after": value}
            setattr(asset, field, value)
        FieldProvenance.objects.update_or_create(
            asset=asset,
            field=field,
            defaults={
                "kind": FieldProvenance.Kind.DISCOVERY,
                "instance": instance,
                "observation": observation,
                "value": value,
                "observed_at": observed_at,
                "recorded_by": None,
            },
        )

    _sync_identifiers(asset, instance, link.external_id, normalized, observed_at)
    after_network = network_snapshot(asset)
    for key in after_network:
        if before_network[key] != after_network[key]:
            changes[key] = {"before": before_network[key], "after": after_network[key]}

    if changes:
        asset.version = F("version") + 1
        asset.save()
        asset.refresh_from_db()
        AssetHistoryEntry.objects.create(
            asset=asset,
            actor=None,
            actor_label=f"source:{instance.name}",
            change_type=AssetHistoryEntry.ChangeType.DISCOVERED,
            changes=changes,
            reason=f"Observation {observation.pk} from {instance.name}",
            version=asset.version,
        )
    return {"changes": changes, "conflicts_opened": conflicts_opened}


def recompute_observation_status(asset_ids) -> None:
    """recently_seen if any active link, stale if only stale links, else manual_only.
    System-managed and read-only via the API, so the record version is not bumped."""
    statuses = {}
    for asset_id, status in SourceLink.objects.filter(asset_id__in=asset_ids).values_list(
        "asset_id", "status"
    ):
        if status == SourceLink.Status.ACTIVE:
            statuses[asset_id] = Asset.ObservationStatus.RECENTLY_SEEN
        elif (
            status == SourceLink.Status.STALE
            and statuses.get(asset_id) != Asset.ObservationStatus.RECENTLY_SEEN
        ):
            statuses[asset_id] = Asset.ObservationStatus.STALE
    for asset_id in asset_ids:
        Asset.objects.filter(pk=asset_id).update(
            observation_status=statuses.get(asset_id, Asset.ObservationStatus.MANUAL_ONLY)
        )
