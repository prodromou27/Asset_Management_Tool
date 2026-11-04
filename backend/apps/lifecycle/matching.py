"""Match an asset to lifecycle catalogue products, one dimension at a time (ASM-53).

Inputs are the asset's own fields (manufacturer, model, OS name/version, firmware version),
which every connector already fills through reconciliation, so no agent is needed.
Normalisation is only case-folding and whitespace collapsing; every other naming
difference must be an explicit, approved alias (``VendorAlias`` / ``LifecycleAlias``).

Outcomes:
- ``matched`` with method ``exact`` (canonical name/release) or ``alias`` (approved alias);
- ``candidate``: several products fit, or only a revision/prefix/family/firmware-only
  match exists - a reviewer must choose; nothing is selected silently;
- ``no_match``: the vendor, model or version is not in the catalogue, or a required
  identifier is missing;
- ``not_applicable``: the dimension does not exist for the asset's category.

Hostnames are never used, and a product family name alone never matches automatically.
"""

import hashlib
import json
from dataclasses import dataclass, field

from apps.assets.models import AssetCategory, FieldProvenance

from .models import AssetLifecycleMatch, Dimension, LifecycleAlias, LifecycleProduct, VendorAlias

State = AssetLifecycleMatch.State
Method = AssetLifecycleMatch.Method
Kind = LifecycleProduct.Kind

# Explicit category rules (ASM-53). Codes apply to the category and its descendants.
NO_HARDWARE_LIFECYCLE = {"servers-virtual-machine"}
NO_OS_LIFECYCLE = {"monitors", "tvs", "peripherals"}
_SEPARATORS = ("-", " ", ".", "/", "_")
_MIN_PREFIX = 4


def key(value) -> str:
    """Case-insensitive, whitespace-collapsed comparison key; nothing else is guessed."""
    return " ".join(str(value or "").casefold().split())


@dataclass
class Entry:
    id: str
    kind: str
    vendor_key: str
    name_key: str
    release_key: str
    family_key: str
    label: str
    aliases: list[tuple[str, str, str]] = field(default_factory=list)  # (kind, value, release)


@dataclass
class Catalogue:
    vendor_aliases: dict[str, str]
    vendors: set[str]
    entries: list[Entry]

    @classmethod
    def load(cls) -> "Catalogue":
        products = {
            str(p.pk): Entry(
                id=str(p.pk),
                kind=p.kind,
                vendor_key=p.vendor_key,
                name_key=p.name_key,
                release_key=p.release_key,
                family_key=key(p.family),
                label=str(p),
            )
            for p in LifecycleProduct.objects.filter(is_active=True)
        }
        for alias in LifecycleAlias.objects.filter(product_id__in=list(products)):
            products[str(alias.product_id)].aliases.append(
                (alias.kind, alias.value_key, alias.release_key)
            )
        return cls(
            vendor_aliases=dict(VendorAlias.objects.values_list("alias_key", "vendor")),
            vendors={e.vendor_key for e in products.values()},
            entries=list(products.values()),
        )

    def vendor_key(self, raw: str) -> str | None:
        k = key(raw)
        if not k:
            return None
        if k in self.vendor_aliases:
            return key(self.vendor_aliases[k])
        return k if k in self.vendors else None


@dataclass
class Result:
    state: str
    method: str = Method.NONE
    product_id: str | None = None
    candidates: list[dict] = field(default_factory=list)
    reason: str = ""


def _candidate(entry: Entry, reason: str) -> dict:
    return {"product_id": entry.id, "label": entry.label, "reason": reason}


def _related_prefix(observed: str, catalogued: str) -> bool:
    """A revision or sub-model: one key extends the other at a separator."""
    if len(catalogued) < _MIN_PREFIX or len(observed) < _MIN_PREFIX or observed == catalogued:
        return False
    longer, shorter = (
        (observed, catalogued) if len(observed) > len(catalogued) else (catalogued, observed)
    )
    return longer.startswith(shorter) and longer[len(shorter)] in _SEPARATORS


def _decide(hits: dict[str, tuple[Entry, str]], what: str) -> Result:
    if len(hits) == 1:
        entry, method = next(iter(hits.values()))
        return Result(State.MATCHED, method, entry.id, reason=f"Matched {what} to {entry.label}.")
    return Result(
        State.CANDIDATE,
        candidates=[_candidate(e, f"Also matches {what}") for e, _ in hits.values()],
        reason=f"{len(hits)} catalogue products match {what}; a reviewer must choose one.",
    )


def match_hardware(cat: Catalogue, manufacturer: str, model: str, rejected: set[str]) -> Result:
    if not key(manufacturer):
        return Result(State.NO_MATCH, reason="Manufacturer not recorded.")
    if not key(model):
        return Result(State.NO_MATCH, reason="Model not recorded.")
    vendor = cat.vendor_key(manufacturer)
    if vendor is None:
        return Result(
            State.NO_MATCH,
            reason=f"Manufacturer '{manufacturer}' is not in the lifecycle catalogue.",
        )
    model_key = key(model)
    pool = [
        e
        for e in cat.entries
        if e.kind == Kind.HARDWARE and e.vendor_key == vendor and e.id not in rejected
    ]
    hits: dict[str, tuple[Entry, str]] = {}
    for e in pool:
        if e.name_key == model_key:
            hits[e.id] = (e, Method.EXACT)
        elif any(k in ("model", "part_number") and v == model_key for k, v, _ in e.aliases):
            hits.setdefault(e.id, (e, Method.ALIAS))
    if hits:
        return _decide(hits, f"model '{model}'")

    candidates = []
    for e in pool:
        if e.family_key and e.family_key == model_key:
            candidates.append(_candidate(e, "Model equals a product family name only"))
        elif _related_prefix(model_key, e.name_key):
            candidates.append(_candidate(e, "Model differs by a revision or suffix"))
    if candidates:
        return Result(
            State.CANDIDATE,
            candidates=candidates,
            reason=f"No exact catalogue entry for model '{model}'; similar products need review.",
        )
    return Result(
        State.NO_MATCH, reason=f"Model '{model}' of {manufacturer} is not in the catalogue."
    )


def match_os(
    cat: Catalogue,
    manufacturer: str,
    os_name: str,
    os_version: str,
    firmware_version: str,
    rejected: set[str],
) -> Result:
    os_kinds = (Kind.OPERATING_SYSTEM, Kind.FIRMWARE)
    pool = [e for e in cat.entries if e.kind in os_kinds and e.id not in rejected]

    if key(os_name):
        name_key, ver_key = key(os_name), key(os_version)
        named = [
            e
            for e in pool
            if e.name_key == name_key
            or any(k == "os_name" and v == name_key for k, v, _ in e.aliases)
        ]
        if not named:
            return Result(
                State.NO_MATCH, reason=f"Operating system '{os_name}' is not in the catalogue."
            )
        if not ver_key:
            return Result(
                State.NO_MATCH,
                reason=f"Version of '{os_name}' not recorded; the release cannot be identified.",
            )
        hits: dict[str, tuple[Entry, str]] = {}
        for e in named:
            if e.name_key == name_key and e.release_key == ver_key:
                hits[e.id] = (e, Method.EXACT)
            elif any(
                k == "os_name" and v == name_key and (r or e.release_key) == ver_key
                for k, v, r in e.aliases
            ):
                hits.setdefault(e.id, (e, Method.ALIAS))
        if hits:
            return _decide(hits, f"'{os_name} {os_version}'")
        candidates = [
            _candidate(e, "Version is a build or patch of this release")
            for e in named
            if e.release_key
            and _related_prefix(ver_key, e.release_key)
            and ver_key.startswith(e.release_key)
        ]
        if candidates:
            return Result(
                State.CANDIDATE,
                candidates=candidates,
                reason=(
                    f"'{os_name} {os_version}' is not catalogued exactly; "
                    "a reviewer must confirm the release."
                ),
            )
        return Result(
            State.NO_MATCH, reason=f"Version '{os_version}' of '{os_name}' is not in the catalogue."
        )

    if key(firmware_version):
        fw_key = key(firmware_version)
        vendor = cat.vendor_key(manufacturer)
        if vendor is None:
            return Result(
                State.NO_MATCH,
                reason="Firmware version recorded but the manufacturer is not in the catalogue.",
            )
        firmware = [e for e in pool if e.kind == Kind.FIRMWARE and e.vendor_key == vendor]
        aliased = [
            e for e in firmware if any(k == "os_name" and v == fw_key for k, v, _ in e.aliases)
        ]
        if aliased:
            return _decide(
                {e.id: (e, Method.ALIAS) for e in aliased}, f"firmware '{firmware_version}'"
            )
        same_release = [e for e in firmware if e.release_key == fw_key]
        if same_release:
            return Result(
                State.CANDIDATE,
                candidates=[
                    _candidate(
                        e, "Same manufacturer and firmware version; product line not reported"
                    )
                    for e in same_release
                ],
                reason=(
                    "Only the firmware version is known; a reviewer must confirm the product line."
                ),
            )
        return Result(
            State.NO_MATCH,
            reason=f"Firmware '{firmware_version}' of {manufacturer} is not in the catalogue.",
        )

    return Result(State.NO_MATCH, reason="No operating system or firmware version recorded.")


# --- Asset-level helpers ----------------------------------------------------------------------


class CategoryRules:
    def __init__(self):
        rows = AssetCategory.objects.values_list("id", "code", "parent_id")
        self._code = {pk: code for pk, code, _ in rows}
        self._parent = {pk: parent for pk, _, parent in rows}

    def codes(self, category_id) -> set[str]:
        out, current = set(), category_id
        while current is not None and current in self._code:
            out.add(self._code[current])
            current = self._parent.get(current)
        return out

    def applicable(self, category_id, dimension: str) -> bool:
        codes = self.codes(category_id)
        if dimension == Dimension.HARDWARE:
            return not codes & NO_HARDWARE_LIFECYCLE
        if dimension == Dimension.OS:
            return not codes & NO_OS_LIFECYCLE
        return False  # software installations arrive with Task 016


FIELDS = {
    Dimension.HARDWARE: ("manufacturer", "model"),
    Dimension.OS: ("manufacturer", "os_name", "os_version", "firmware_version"),
}


def observed_values(asset, dimension: str, provenance: dict[str, FieldProvenance]) -> dict:
    out = {}
    for name in FIELDS[dimension]:
        prov = provenance.get(name)
        out[name] = {
            "value": getattr(asset, name) or "",
            "source": (
                None
                if prov is None
                else {
                    "kind": prov.kind,
                    "instance": prov.instance.name if prov.instance_id else None,
                    "observed_at": prov.observed_at.isoformat() if prov.observed_at else None,
                }
            ),
        }
    return out


def observed_key(asset, dimension: str) -> str:
    raw = json.dumps([key(getattr(asset, n)) for n in FIELDS[dimension]])
    return hashlib.sha256(raw.encode()).hexdigest()


def match(cat: Catalogue, asset, dimension: str, rejected: set[str]) -> Result:
    if dimension == Dimension.HARDWARE:
        return match_hardware(cat, asset.manufacturer, asset.model, rejected)
    return match_os(
        cat, asset.manufacturer, asset.os_name, asset.os_version, asset.firmware_version, rejected
    )
