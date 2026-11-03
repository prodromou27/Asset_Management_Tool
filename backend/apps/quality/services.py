"""Detect and manage data-quality findings (Task 011).

Rules (all on live, non-archived assets):
- duplicate_candidate (high): another live asset has the same manufacturer (normalised)
  and serial number; (medium) another live asset has the same MAC address.
- model_unknown (medium): no model recorded (blocks lifecycle matching). Virtual machines
  are exempt.
- source_stale (medium): the asset has source links but none is active (every source
  stopped reporting it). Never interpreted as "the device is gone".
- owner_missing: deployed (low) or assigned (medium) without an owner.
"""

from collections import defaultdict

from django.db import transaction
from django.db.models import F
from django.utils import timezone

from apps.assets.models import Asset, AssetInterface
from apps.assets.tree import CategoryTree
from apps.audit import services as audit
from apps.observations.normalize import normalize_manufacturer, normalize_serial
from apps.organizations.services import check_version
from config.api import ApiError

from .models import ACTIVE_STATES, DataQualityFinding

Finding = DataQualityFinding
Kind = Finding.Kind
Severity = Finding.Severity
NO_MODEL_EXPECTED = {"servers-virtual-machine"}


def _detect() -> dict[tuple[str, object], dict]:
    """(kind, asset_id) → {severity, summary, evidence} for every condition that holds."""
    out: dict[tuple[str, object], dict] = {}
    live = Asset.objects.filter(archived_at__isnull=True)
    names = dict(live.values_list("id", "name"))

    # Duplicates: manufacturer + serial.
    by_serial: dict[tuple[str, str], list] = defaultdict(list)
    for asset_id, maker, serial in live.exclude(serial_number="").values_list(
        "id", "manufacturer", "serial_number"
    ):
        make, sn = normalize_manufacturer(maker), normalize_serial(serial)
        if make and sn:
            by_serial[(make, sn)].append(asset_id)
    for (make, serial), ids in by_serial.items():
        if len(ids) < 2:
            continue
        for asset_id in ids:
            others = [{"id": str(o), "name": names[o]} for o in ids if o != asset_id]
            out[(Kind.DUPLICATE_CANDIDATE, asset_id)] = {
                "severity": Severity.HIGH,
                "summary": f"Same manufacturer and serial ({make} {serial}) as "
                f"{len(others)} other asset(s).",
                "evidence": {
                    "match": "manufacturer_serial",
                    "value": f"{make} {serial}",
                    "assets": others,
                },
            }

    # Duplicates: MAC address (weaker: NICs move, docks are shared).
    by_mac: dict[str, set] = defaultdict(set)
    for asset_id, mac in (
        AssetInterface.objects.filter(asset__archived_at__isnull=True)
        .exclude(mac_address="")
        .values_list("asset_id", "mac_address")
    ):
        if mac:
            by_mac[mac].add(asset_id)
    for mac, ids in by_mac.items():
        if len(ids) < 2:
            continue
        for asset_id in ids:
            if (Kind.DUPLICATE_CANDIDATE, asset_id) in out:
                continue  # the serial finding is stronger
            others = [
                {"id": str(o), "name": names[o]} for o in sorted(ids, key=str) if o != asset_id
            ]
            out[(Kind.DUPLICATE_CANDIDATE, asset_id)] = {
                "severity": Severity.MEDIUM,
                "summary": f"MAC address {mac} is also recorded on {len(others)} other asset(s).",
                "evidence": {"match": "mac", "value": mac, "assets": others},
            }

    # Model unknown.
    tree = CategoryTree()
    for asset_id, category_id, maker in live.filter(model="").values_list(
        "id", "category_id", "manufacturer"
    ):
        node = tree.by_id.get(category_id)
        if node is not None and node.code in NO_MODEL_EXPECTED:
            continue
        out[(Kind.MODEL_UNKNOWN, asset_id)] = {
            "severity": Severity.MEDIUM,
            "summary": "No model recorded; lifecycle (EOL) cannot be matched.",
            "evidence": {"manufacturer": maker or None, "category": tree.path(category_id)},
        }

    # Source stale: links exist, none active.
    from apps.reconciliation.models import SourceLink

    links: dict[object, list] = defaultdict(list)
    for asset_id, status, instance, external_id, last_seen in (
        SourceLink.objects.filter(asset__archived_at__isnull=True)
        .exclude(status=SourceLink.Status.UNLINKED)
        .values_list("asset_id", "status", "instance__name", "external_id", "last_seen_at")
    ):
        links[asset_id].append((status, instance, external_id, last_seen))
    for asset_id, rows in links.items():
        if any(status == SourceLink.Status.ACTIVE for status, *_ in rows):
            continue
        latest = max(r[3] for r in rows)
        out[(Kind.SOURCE_STALE, asset_id)] = {
            "severity": Severity.MEDIUM,
            "summary": f"No linked source has reported this asset since {latest:%Y-%m-%d}.",
            "evidence": {
                "links": [
                    {"source": instance, "external_id": ext, "last_seen_at": seen.isoformat()}
                    for _, instance, ext, seen in rows
                ]
            },
        }

    # Owner missing on deployed/assigned assets.
    for asset_id, status in live.filter(
        owner__isnull=True,
        business_status__in=[Asset.BusinessStatus.DEPLOYED, Asset.BusinessStatus.ASSIGNED],
    ).values_list("id", "business_status"):
        assigned = status == Asset.BusinessStatus.ASSIGNED
        out[(Kind.OWNER_MISSING, asset_id)] = {
            "severity": Severity.MEDIUM if assigned else Severity.LOW,
            "summary": f"{'Assigned' if assigned else 'Deployed'} without an owner.",
            "evidence": {"business_status": status},
        }
    return out


def refresh(now=None) -> dict:
    """Recompute findings. Returns counts {opened, refreshed, resolved}."""
    now = now or timezone.now()
    found = _detect()
    counts = {"opened": 0, "refreshed": 0, "resolved": 0}
    with transaction.atomic():
        active = {
            (f.kind, f.asset_id): f
            for f in Finding.objects.select_for_update().filter(status__in=ACTIVE_STATES)
        }
        for key, data in found.items():
            finding = active.get(key)
            if finding is None:
                Finding.objects.create(
                    kind=key[0],
                    asset_id=key[1],
                    detected_at=now,
                    last_confirmed_at=now,
                    **data,
                )
                counts["opened"] += 1
                continue
            changed = any(getattr(finding, k) != v for k, v in data.items())
            Finding.objects.filter(pk=finding.pk).update(
                last_confirmed_at=now,
                **data,
                **({"version": F("version") + 1} if changed else {}),
            )
            counts["refreshed"] += 1
        cleared = [f.pk for key, f in active.items() if key not in found]
        counts["resolved"] = Finding.objects.filter(pk__in=cleared).update(
            status=Finding.Status.RESOLVED,
            resolved_at=now,
            resolved_by=None,
            resolution_reason="The condition no longer holds.",
            version=F("version") + 1,
        )
    return counts


def _locked(finding: Finding, expected_version) -> Finding:
    finding = Finding.objects.select_for_update().get(pk=finding.pk)
    check_version(finding, expected_version)
    return finding


def assign(request, finding: Finding, assignee, expected_version) -> Finding:
    with transaction.atomic():
        finding = _locked(finding, expected_version)
        if finding.status != Finding.Status.OPEN:
            raise ApiError("FINDING_CLOSED", "Only open findings can be assigned.", 409)
        before = finding.assignee.username if finding.assignee else None
        finding.assignee = assignee
        finding.assigned_at = timezone.now() if assignee else None
        finding.version = F("version") + 1
        finding.save()
        finding.refresh_from_db()
        audit.record(
            action="quality.assign",
            actor=request.user,
            request=request,
            object_type="asset",
            object_id=finding.asset_id,
            object_label=finding.asset.name,
            before={"assignee": before, "kind": finding.kind},
            after={"assignee": assignee.username if assignee else None},
        )
    return finding


def dismiss(request, finding: Finding, reason: str, expected_version) -> Finding:
    """Accept the finding as is (e.g. a lab device without an owner). It stays dismissed
    while the condition holds."""
    with transaction.atomic():
        finding = _locked(finding, expected_version)
        if finding.status != Finding.Status.OPEN:
            raise ApiError("FINDING_CLOSED", "Only open findings can be dismissed.", 409)
        finding.status = Finding.Status.DISMISSED
        finding.resolved_by = request.user
        finding.resolved_at = timezone.now()
        finding.resolution_reason = reason
        finding.version = F("version") + 1
        finding.save()
        finding.refresh_from_db()
        audit.record(
            action="quality.dismiss",
            actor=request.user,
            request=request,
            object_type="asset",
            object_id=finding.asset_id,
            object_label=finding.asset.name,
            after={"kind": finding.kind, "severity": finding.severity},
            detail=reason,
        )
    return finding


def reopen(request, finding: Finding, reason: str, expected_version) -> Finding:
    with transaction.atomic():
        finding = _locked(finding, expected_version)
        if finding.status != Finding.Status.DISMISSED:
            raise ApiError("FINDING_NOT_DISMISSED", "Only dismissed findings can be reopened.", 409)
        finding.status = Finding.Status.OPEN
        finding.resolved_by = None
        finding.resolved_at = None
        finding.resolution_reason = ""
        finding.version = F("version") + 1
        finding.save()
        finding.refresh_from_db()
        audit.record(
            action="quality.reopen",
            actor=request.user,
            request=request,
            object_type="asset",
            object_id=finding.asset_id,
            object_label=finding.asset.name,
            after={"kind": finding.kind},
            detail=reason,
        )
    return finding
