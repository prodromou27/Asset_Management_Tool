"""Lifecycle status from verified milestones (ASM-53). Pure functions; no database access.

Calendar rules: all evaluation uses the UTC calendar date. A milestone date is the last
day the service is provided, so it is "passed" from the next day; ``days_remaining`` is
``date - today`` (0 on the last day, negative once passed).

Evidence rules:
- only ``verified`` milestones count; pending ones are ignored (but explained);
- per milestone type the highest-precedence source tier wins: vendor > manual > third
  party; a lower tier with a different date is reported, not used;
- two different dates within the winning tier are a conflict: status ``unverified``;
- no verified milestone and no verified vendor statement means ``unknown`` - missing
  information is never treated as support.

Support: by default the governing date is the end of *standard* support (or the final
end of support when no standard date is published). Extended support is shown as the
support level but only governs the status when the deployment counts it
(``ITAM_LIFECYCLE_COUNT_EXTENDED_SUPPORT``), because it usually depends on a separate
customer agreement.
"""

from dataclasses import dataclass, field
from datetime import date

from .models import LifecycleAssessment, LifecycleMilestone, LifecycleProduct, MilestoneType, Status

M = MilestoneType
Quality = LifecycleAssessment.EvidenceQuality
Level = LifecycleAssessment.SupportLevel
PRECEDENCE = {"vendor": 0, "manual": 1, "third_party": 2}
_QUALITY = {"vendor": Quality.VENDOR, "manual": Quality.MANUAL, "third_party": Quality.THIRD_PARTY}


@dataclass(frozen=True)
class Claim:
    id: str
    milestone_type: str
    date: date
    source_type: str
    verification: str
    publisher: str = ""


@dataclass
class Picked:
    milestone_type: str
    date: date
    source_type: str
    ids: list[str]


@dataclass
class Outcome:
    status: str
    support_level: str = Level.NONE
    milestone_type: str = ""
    milestone_date: date | None = None
    days_remaining: int | None = None
    threshold_days: int | None = None
    evidence_quality: str = Quality.NONE
    milestone_ids: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)


def _label(milestone_type: str) -> str:
    return M(milestone_type).label


def claims_for(product: LifecycleProduct) -> list[Claim]:
    return [
        Claim(
            id=str(m.pk),
            milestone_type=m.milestone_type,
            date=m.date,
            source_type=m.source.source_type,
            verification=m.verification,
            publisher=m.source.publisher,
        )
        for m in product.milestones.all()
    ]


def evaluate(
    claims: list[Claim],
    today: date,
    thresholds: list[int],
    count_extended: bool = False,
    statement: str = "",
    statement_verified: bool = False,
) -> Outcome:
    reasons: list[str] = []
    verified = [c for c in claims if c.verification == LifecycleMilestone.Verification.VERIFIED]
    pending = [c for c in claims if c.verification == LifecycleMilestone.Verification.PENDING]
    conflicts: list[str] = []

    def pick(milestone_type: str) -> Picked | None:
        mine = [c for c in verified if c.milestone_type == milestone_type]
        if not mine:
            return None
        best = min(PRECEDENCE[c.source_type] for c in mine)
        tier = [c for c in mine if PRECEDENCE[c.source_type] == best]
        dates = sorted({c.date for c in tier})
        if len(dates) > 1:
            conflicts.append(
                f"Conflicting verified dates for {_label(milestone_type).lower()}: "
                + ", ".join(d.isoformat() for d in dates)
                + "."
            )
            return None
        lower = sorted(
            {c.date for c in mine if PRECEDENCE[c.source_type] > best and c.date != dates[0]}
        )
        for other in lower:
            reasons.append(
                f"A lower-precedence source gives {other.isoformat()} for "
                f"{_label(milestone_type).lower()}; {dates[0].isoformat()} is used."
            )
        return Picked(milestone_type, dates[0], tier[0].source_type, [c.id for c in tier])

    std = pick(M.END_OF_STANDARD_SUPPORT)
    ext = pick(M.END_OF_EXTENDED_SUPPORT)
    final = pick(M.END_OF_SUPPORT)
    sec = pick(M.END_OF_SECURITY_UPDATES)
    maint = pick(M.END_OF_MAINTENANCE)
    sale = pick(M.END_OF_SALE)
    announced = pick(M.ANNOUNCEMENT)

    if conflicts:
        return Outcome(
            Status.UNVERIFIED,
            reasons=[
                *conflicts,
                "Resolve the conflicting evidence before the status can be calculated.",
            ],
            milestone_ids=[c.id for c in verified],
        )

    governing = (final or ext or std) if count_extended else (std or final)
    level = _support_level(today, std, ext, final)

    def outcome(status: str, picked: Picked, extra: list[str]) -> Outcome:
        days = (picked.date - today).days
        tier = min((t for t in thresholds if days <= t), default=None) if days >= 0 else None
        used = [p for p in (std, ext, final, sec, maint, sale, announced) if p]
        quality = _QUALITY[picked.source_type]
        notes = list(extra)
        if quality == Quality.THIRD_PARTY:
            notes.append("Based on third-party evidence only; confirm with the vendor.")
        if ext and not count_extended and ext.date >= today and governing is not ext:
            notes.append(
                f"Extended support is published until {ext.date.isoformat()}; it usually needs a "
                "separate agreement and is not counted."
            )
        if maint and maint.date < today and status not in (Status.EOS,):
            notes.append(f"Maintenance releases ended on {maint.date.isoformat()}.")
        return Outcome(
            status,
            support_level=level,
            milestone_type=picked.milestone_type,
            milestone_date=picked.date,
            days_remaining=days,
            threshold_days=tier if status == Status.EXPIRING else None,
            evidence_quality=quality,
            milestone_ids=[i for p in used for i in p.ids],
            reasons=reasons + notes,
        )

    if governing and governing.date < today:
        return outcome(
            Status.EOS,
            governing,
            [f"{_label(governing.milestone_type)} was {governing.date.isoformat()}."],
        )
    if sec and sec.date < today:
        return outcome(
            Status.SECURITY_MAINTENANCE_ENDED,
            sec,
            [f"Security updates ended on {sec.date.isoformat()}."],
        )
    upcoming = [p for p in (sec, governing) if p]
    if upcoming:
        nearest = min(upcoming, key=lambda p: p.date)
        days = (nearest.date - today).days
        if thresholds and days <= max(thresholds):
            return outcome(
                Status.EXPIRING,
                nearest,
                [f"{_label(nearest.milestone_type)} on {nearest.date.isoformat()} ({days} days)."],
            )
        return outcome(
            Status.EOL_ANNOUNCED,
            nearest,
            [f"{_label(nearest.milestone_type)} on {nearest.date.isoformat()}."],
        )
    others = [p for p in (ext, maint, sale, announced) if p]
    if others:
        future = [p for p in others if p.date >= today]
        shown = min(future, key=lambda p: p.date) if future else max(others, key=lambda p: p.date)
        result = outcome(
            Status.EOL_ANNOUNCED,
            shown,
            ["No verified end-of-support date is published; only earlier milestones are known."],
        )
        result.threshold_days = None
        return result

    if statement and statement_verified:
        status = Status.SUPPORTED if statement == "supported" else Status.NOT_ANNOUNCED
        return Outcome(
            status,
            evidence_quality=Quality.VENDOR,
            reasons=[
                "The vendor states the product is supported."
                if status == Status.SUPPORTED
                else "The vendor has not announced end of life for this product."
            ],
        )
    if pending:
        return Outcome(
            Status.UNKNOWN,
            reasons=[f"{len(pending)} lifecycle date(s) are awaiting verification."],
        )
    return Outcome(Status.UNKNOWN, reasons=["No verified lifecycle dates for this product."])


def _support_level(today: date, std, ext, final) -> str:
    if not (std or ext or final):
        return Level.NONE
    if std and today <= std.date:
        return Level.STANDARD
    if ext and today <= ext.date:
        return Level.EXTENDED
    if final and today <= final.date:
        return Level.EXTENDED if std else Level.STANDARD
    return Level.ENDED


# Worst first; used for the asset-level summary in ``Asset.support_status``.
SUMMARY_ORDER = [
    Status.EOS,
    Status.SECURITY_MAINTENANCE_ENDED,
    Status.EXPIRING,
    Status.UNKNOWN,
    Status.EOL_ANNOUNCED,
    Status.NOT_ANNOUNCED,
    Status.SUPPORTED,
]


def summarize(effective_statuses: list[str]) -> str:
    """Asset support status = the worst applicable dimension; unverified counts as unknown and
    an asset with no applicable dimension is unknown."""
    applicable = [
        Status.UNKNOWN if s == Status.UNVERIFIED else s
        for s in effective_statuses
        if s != Status.NOT_APPLICABLE
    ]
    if not applicable:
        return Status.UNKNOWN
    return min(applicable, key=SUMMARY_ORDER.index)
