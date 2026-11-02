"""Identity matching (docs/03 matching precedence, docs/05 shared normalisation).

1. Instance + external ID already linked  → resolved before this module runs.
2. Verified manufacturer + serial, or hardware UUID seen on another linked source
   → strong key. A single strong match may auto-link only if the instance policy
   allows it, the category corroborates and nothing contradicts it.
3. Several corroborating keys (MAC, hostname, name, IP in the same site/VRF)
   → candidate for human review, never automatic.
4. One weak key alone → low-score candidate, never automatic.
5. Strong keys pointing at different assets → conflict candidate.
"""

from collections import defaultdict
from dataclasses import dataclass, field

from django.db.models import Q

from apps.assets.models import Asset, AssetCategory, AssetHostname, AssetInterface, AssetIPAddress
from apps.assets.tree import CategoryTree
from apps.observations.normalize import normalize_manufacturer

from .models import ReconciliationCandidate, SourceLink

Rule = ReconciliationCandidate.Rule

WEIGHTS = {
    "hardware_uuid": 80,
    "serial": 70,
    "serial_unverified": 35,
    "mac": 25,
    "hostname": 20,
    "name": 10,
    "ip": 10,
}
STRONG_KEYS = {"hardware_uuid", "serial"}
CATEGORY_BONUS = 10
# One fact can hit several keys (a hostname matches both hostname rows and the
# asset name). Scoring and "how many independent identifiers" count families.
FAMILY = {"name": "hostname", "serial_unverified": "serial"}


def _families(found) -> set:
    return {FAMILY.get(k["key"], k["key"]) for k in found}


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
                        "strength": "strong" if key in STRONG_KEYS else "corroborating",
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
            # Same serial, different manufacturer: not the same device.

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
    matches = []
    for asset_id, found in keys.items():
        asset = assets[asset_id]
        score = _score(found)
        category_agrees = None
        if suggested is not None:
            category_agrees = _root(tree, asset.category_id) == _root(tree, suggested.pk)
            if category_agrees:
                score += CATEGORY_BONUS
        matches.append(
            {
                "asset_id": str(asset_id),
                "asset_name": asset.name,
                "site_id": str(asset.site_id),
                "score": min(score, 99),
                "keys": sorted(found, key=lambda k: -WEIGHTS[k["key"]]),
                "category_agrees": category_agrees,
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
            "Strong identifiers (serial or hardware UUID) point to different assets."
        )
        return result

    if strong:
        (strong_id,) = strong
        winner = next(m for m in matches if m["asset_id"] == strong_id)
        result.proposed_asset_id = strong_id
        result.score = winner["score"]
        result.rule = Rule.STRONG
        if winner["category_agrees"] is False:
            result.conflicts.append("The source's device type does not match the asset's category.")
        others = [
            m for m in matches if m["asset_id"] != strong_id and len(_families(m["keys"])) >= 2
        ]
        if others:
            result.rule = Rule.CONFLICT
            result.conflicts.append(
                "Other assets share several identifiers with this device; check for duplicates."
            )
        result.auto_linkable = (
            result.rule == Rule.STRONG
            and winner["category_agrees"] is not False
            and any(k["key"] in STRONG_KEYS for k in winner["keys"])
        )
        return result

    result.rule = Rule.CORROBORATED if len(_families(top["keys"])) >= 2 else Rule.WEAK
    return result
