"""Identity matching (docs/03 matching precedence, docs/05 shared normalisation).

1. Instance + external ID already linked  → resolved before this module runs.
2. Verified manufacturer + serial, or hardware UUID seen on another linked source
   → strong key. A strong key alone never decides: a single strong match may
   auto-link only if the instance policy allows it, the manufacturer is known and
   the same on both sides, the asset class is known and the same, and no other
   identifier contradicts it (a different hardware UUID or serial, or other assets
   sharing several identifiers). Any contradiction → conflict candidate.
3. Several corroborating keys (MAC, hostname, name, IP in the same site/VRF)
   → candidate for human review, never automatic.
4. One weak key alone → low-score candidate, never automatic.
5. Strong keys pointing at different assets → conflict candidate.
6. Same serial but a different manufacturer → conflict candidate (never a match,
   but shown to the reviewer instead of being dropped silently).
7. Microsoft Entra device ID (ADR-014): strong only between instances of the same
   tenant (verified), and only when it points at one asset (unambiguous). Microsoft
   sources such as Defender report no manufacturer or chassis, so instead of the
   manufacturer + class rule it may auto-link when nothing contradicts it (no known
   manufacturer or class disagreement, no conflicting identifier) AND at least one
   independent identifier (hostname, MAC or serial) corroborates it.
"""

from collections import defaultdict
from dataclasses import dataclass, field

from django.db.models import Q

from apps.assets.models import Asset, AssetCategory, AssetHostname, AssetInterface, AssetIPAddress
from apps.assets.tree import CategoryTree
from apps.observations.normalize import normalize_manufacturer, normalize_serial

from .models import ReconciliationCandidate, SourceLink

Rule = ReconciliationCandidate.Rule

WEIGHTS = {
    "hardware_uuid": 80,
    "entra_device_id": 75,
    "serial": 70,
    "serial_unverified": 35,
    "serial_other_make": 0,
    "mac": 25,
    "hostname": 20,
    "name": 10,
    "ip": 10,
}
STRONG_KEYS = {"hardware_uuid", "serial", "entra_device_id"}
# Families that may corroborate an Entra device ID match (IP is never enough).
CORROBORATING_FAMILIES = {"hostname", "mac", "serial"}
LIVE_LINKS = (SourceLink.Status.ACTIVE, SourceLink.Status.STALE)
CONFLICTING_KEYS = {"serial_other_make"}
CATEGORY_BONUS = 10
# One fact can hit several keys (a hostname matches both hostname rows and the
# asset name). Scoring and "how many independent identifiers" count families.
FAMILY = {"name": "hostname", "serial_unverified": "serial"}


def _strength(key) -> str:
    if key in STRONG_KEYS:
        return "strong"
    return "conflicting" if key in CONFLICTING_KEYS else "corroborating"


def _families(found) -> set:
    return {FAMILY.get(k["key"], k["key"]) for k in found if k["key"] not in CONFLICTING_KEYS}


def _score(found) -> int:
    best: dict = {}
    for k in found:
        family = FAMILY.get(k["key"], k["key"])
        best[family] = max(best.get(family, 0), WEIGHTS[k["key"]])
    return sum(best.values())


@dataclass
class MatchResult:
    rule: str
    score: int = 0
    proposed_asset_id: object = None
    matches: list = field(default_factory=list)
    conflicts: list = field(default_factory=list)
    strong_asset_ids: set = field(default_factory=set)
    auto_linkable: bool = False
    suggested_category: AssetCategory | None = None


def _root(tree: CategoryTree, category_id):
    lineage = tree.lineage(category_id)
    return lineage[0] if lineage else category_id


def find_matches(instance, normalized: dict, *, exclude_asset_ids=()) -> MatchResult:
    keys: dict = defaultdict(list)
    live = Asset.objects.filter(archived_at__isnull=True).exclude(pk__in=list(exclude_asset_ids))

    def add(asset_ids, key, value):
        for asset_id in set(asset_ids):
            if not any(k["key"] == key for k in keys[asset_id]):
                keys[asset_id].append(
                    {
                        "key": key,
                        "strength": _strength(key),
                        "value": value,
                    }
                )

    serial = normalized.get("serial_number")
    if serial:
        for asset_id, manufacturer in live.filter(serial_number__iexact=serial).values_list(
            "id", "manufacturer"
        ):
            asset_make = normalize_manufacturer(manufacturer)
            if normalized.get("serial_verified") and asset_make == normalized["manufacturer"]:
                add([asset_id], "serial", f"{normalized['manufacturer']} {serial}")
            elif not asset_make or not normalized.get("manufacturer"):
                add([asset_id], "serial_unverified", serial)
            else:
                # Same serial, different manufacturer: not the same device, but the
                # reviewer must see it rather than get a silent "new device".
                add([asset_id], "serial_other_make", f"{serial} ({asset_make})")

    if uuid := normalized.get("hardware_uuid"):
        linked = (
            SourceLink.objects.filter(
                asset__in=live,
                status__in=[SourceLink.Status.ACTIVE, SourceLink.Status.STALE],
                last_observation__normalized__hardware_uuid=uuid,
            )
            .exclude(instance=instance, external_id=normalized["external_id"])
            .values_list("asset_id", flat=True)
        )
        add(linked, "hardware_uuid", uuid)

    entra = normalized.get("entra_device_id")
    tenant = (getattr(instance, "tenant_id", "") or "").strip().lower()
    if entra and tenant:
        # Entra device IDs are only unique within a tenant: compare them only with
        # sources configured for the same tenant.
        linked = (
            SourceLink.objects.filter(
                asset__in=live,
                status__in=LIVE_LINKS,
                instance__tenant_id__iexact=tenant,
                last_observation__normalized__entra_device_id=entra,
            )
            .exclude(instance=instance, external_id=normalized["external_id"])
            .values_list("asset_id", flat=True)
        )
        add(linked, "entra_device_id", entra)

    if macs := normalized.get("mac_addresses"):
        for mac in macs:
            add(
                AssetInterface.objects.filter(asset__in=live, mac_address=mac).values_list(
                    "asset_id", flat=True
                ),
                "mac",
                mac,
            )

    hostnames = normalized.get("hostnames") or []
    shorts = normalized.get("short_hostnames") or []
    if hostnames:
        rows = AssetHostname.objects.filter(asset__in=live).filter(
            Q(hostname__in=hostnames) | Q(hostname__in=shorts)
        )
        add(rows.values_list("asset_id", flat=True), "hostname", hostnames[0])
        name_q = Q()
        for value in {*hostnames, *shorts}:
            name_q |= Q(name__iexact=value)
        add(
            live.filter(name_q).values_list("id", flat=True),
            "name",
            shorts[0] if shorts else hostnames[0],
        )

    site_id = instance.default_site_id
    for row in normalized.get("ip_addresses") or []:
        context = Q(site_id=site_id) | Q(site__isnull=True, asset__site_id=site_id)
        add(
            AssetIPAddress.objects.filter(
                asset__in=live, address=row["address"], vrf=row.get("vrf") or ""
            )
            .filter(context)
            .values_list("asset_id", flat=True),
            "ip",
            f"{row['address']}{' vrf ' + row['vrf'] if row.get('vrf') else ''}",
        )

    tree = CategoryTree()
    suggested = None
    if code := normalized.get("category_code"):
        suggested = AssetCategory.objects.filter(code=code, is_active=True).first()

    assets = {a.pk: a for a in Asset.objects.filter(pk__in=keys.keys()).select_related("site")}
    make = normalized.get("manufacturer")
    matches = []
    for asset_id, found in keys.items():
        asset = assets[asset_id]
        score = _score(found)
        category_agrees = None
        if suggested is not None:
            category_agrees = _root(tree, asset.category_id) == _root(tree, suggested.pk)
            if category_agrees:
                score += CATEGORY_BONUS
        asset_make = normalize_manufacturer(asset.manufacturer)
        manufacturer_agrees = None if not (make and asset_make) else make == asset_make
        matches.append(
            {
                "asset_id": str(asset_id),
                "asset_name": asset.name,
                "site_id": str(asset.site_id),
                "score": min(score, 99),
                "keys": sorted(found, key=lambda k: -WEIGHTS[k["key"]]),
                "category_agrees": category_agrees,
                "manufacturer_agrees": manufacturer_agrees,
            }
        )
    matches.sort(key=lambda m: -m["score"])

    result = MatchResult(rule=Rule.NEW_DEVICE, matches=matches, suggested_category=suggested)
    strong = {m["asset_id"] for m in matches if any(k["key"] in STRONG_KEYS for k in m["keys"])}
    result.strong_asset_ids = strong
    if not matches:
        return result

    top = matches[0]
    result.score = top["score"]
    result.proposed_asset_id = top["asset_id"]

    if len(strong) > 1:
        result.rule = Rule.CONFLICT
        result.proposed_asset_id = None
        result.conflicts.append(
            "Strong identifiers (serial, hardware UUID or Entra device ID) point to "
            "different assets."
        )
        return result

    if strong:
        (strong_id,) = strong
        winner = next(m for m in matches if m["asset_id"] == strong_id)
        result.proposed_asset_id = strong_id
        result.score = winner["score"]
        if winner["manufacturer_agrees"] is False:
            result.conflicts.append(
                "The source's manufacturer does not match the asset's manufacturer."
            )
        if winner["category_agrees"] is False:
            result.conflicts.append("The source's device type does not match the asset's category.")
        winner_asset = next(a for pk, a in assets.items() if str(pk) == strong_id)
        result.conflicts.extend(_identifier_conflicts(instance, normalized, winner_asset))
        others = [
            m for m in matches if m["asset_id"] != strong_id and len(_families(m["keys"])) >= 2
        ]
        if others:
            result.conflicts.append(
                "Other assets share several identifiers with this device; check for duplicates."
            )
        result.rule = Rule.CONFLICT if result.conflicts else Rule.STRONG
        # A strong key alone is not enough: manufacturer and class must be known and
        # agree. Unknown values leave the match for a reviewer.
        make_and_class = winner["manufacturer_agrees"] is True and winner["category_agrees"] is True
        # ADR-014: a verified, unambiguous Entra device ID with nothing contradicting it
        # and an independent identifier corroborating it.
        entra_rule = any(k["key"] == "entra_device_id" for k in winner["keys"]) and bool(
            _families(winner["keys"]) & CORROBORATING_FAMILIES
        )
        result.auto_linkable = result.rule == Rule.STRONG and (make_and_class or entra_rule)
        return result

    clashing = [m for m in matches if any(k["key"] in CONFLICTING_KEYS for k in m["keys"])]
    if clashing:
        result.rule = Rule.CONFLICT
        result.proposed_asset_id = clashing[0]["asset_id"]
        result.score = clashing[0]["score"]
        result.conflicts.append(
            "The serial number matches an asset from a different manufacturer; "
            "check whether this is a new device or a data-entry error."
        )
        return result

    result.rule = Rule.CORROBORATED if len(_families(top["keys"])) >= 2 else Rule.WEAK
    return result


def _identifier_conflicts(instance, normalized: dict, asset) -> list:
    """Identifiers the source reports that contradict what is known about the asset."""
    out = []
    serial = normalized.get("serial_number")
    asset_serial = normalize_serial(asset.serial_number)
    if serial and asset_serial and serial.upper() != asset_serial:
        out.append(f"The source reports serial {serial} but the asset has serial {asset_serial}.")
    if uuid := normalized.get("hardware_uuid"):
        known = {
            u
            for u in SourceLink.objects.filter(
                asset=asset, status__in=[SourceLink.Status.ACTIVE, SourceLink.Status.STALE]
            )
            .exclude(instance=instance, external_id=normalized["external_id"])
            .values_list("last_observation__normalized__hardware_uuid", flat=True)
            if u
        }
        if known and uuid not in known:
            out.append(
                "The source reports a hardware UUID that differs from the one other "
                "sources report for this asset."
            )
    if entra := normalized.get("entra_device_id"):
        known = {
            str(u).lower()
            for u in SourceLink.objects.filter(asset=asset, status__in=LIVE_LINKS)
            .exclude(instance=instance, external_id=normalized["external_id"])
            .values_list("last_observation__normalized__entra_device_id", flat=True)
            if u
        }
        if known and entra not in known:
            out.append(
                "The source reports an Entra device ID that differs from the one other "
                "sources report for this asset."
            )
    # One live record per device per source: a second active record from the same
    # integration (re-enrollment, duplicate MDM record) is never merged automatically.
    sibling = (
        SourceLink.objects.filter(asset=asset, instance=instance, status=SourceLink.Status.ACTIVE)
        .exclude(external_id=normalized["external_id"])
        .values_list("external_id", flat=True)
        .first()
    )
    if sibling:
        out.append(
            f"The asset is already linked to another active {instance.name} record "
            f"({sibling}); check for a re-enrollment or a duplicate record."
        )
    return out
