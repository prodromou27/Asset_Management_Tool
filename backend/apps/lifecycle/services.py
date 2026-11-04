"""Lifecycle catalogue changes, reassessment, match review and exceptions (Task 015).

Every catalogue change writes a product revision (numbered snapshot) and an audit record,
and queues a reassessment after commit. Matches and assessments are recalculated from
the assets' own fields; manual asset data and source observations are never modified -
only the computed ``Asset.support_status`` summary is updated (without touching the
asset's edit version).
"""

from datetime import UTC, timedelta

from django.conf import settings
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from apps.assets.models import Asset, FieldProvenance
from apps.audit import services as audit
from apps.audit.models import AuditEvent
from apps.organizations.services import check_version
from config.api import ApiError

from . import assessment, matching
from .matching import key
from .models import (
    AssetLifecycleMatch,
    Dimension,
    LifecycleAlias,
    LifecycleAssessment,
    LifecycleAssessmentHistory,
    LifecycleException,
    LifecycleMilestone,
    LifecycleProduct,
    LifecycleRevision,
    LifecycleSource,
    Status,
    VendorAlias,
)

ASSESSED_DIMENSIONS = (Dimension.HARDWARE, Dimension.OS)
BATCH = 500


def today_utc():
    return timezone.now().astimezone(UTC).date()


def thresholds() -> list[int]:
    return sorted(
        {int(d) for d in settings.ITAM_LIFECYCLE_WARNING_DAYS if int(d) > 0}, reverse=True
    )


# --- Snapshots, revisions and audit -----------------------------------------------------------


def snapshot(product: LifecycleProduct) -> dict:
    return {
        "kind": product.kind,
        "vendor": product.vendor,
        "name": product.name,
        "release": product.release,
        "family": product.family,
        "description": product.description,
        "is_active": product.is_active,
        "support_statement": product.support_statement,
        "statement_source": str(product.statement_source_id or ""),
        "statement_verified": product.statement_verified_at is not None,
        "aliases": sorted(
            [a.kind, a.value, a.release] for a in product.aliases.all().order_by("kind", "value")
        ),
        "milestones": [
            {
                "id": str(m.pk),
                "type": m.milestone_type,
                "date": m.date.isoformat(),
                "source": str(m.source_id),
                "verification": m.verification,
                "reviewed_by": m.reviewed_by.username if m.reviewed_by else None,
                "notes": m.notes,
            }
            for m in product.milestones.select_related("reviewed_by").order_by(
                "milestone_type", "date", "created_at"
            )
        ],
    }


def _revise(request, product: LifecycleProduct, action: str, summary: str = "", before=None):
    after = snapshot(product)
    number = (
        product.revisions.order_by("-number").values_list("number", flat=True).first() or 0
    ) + 1
    LifecycleRevision.objects.create(
        product=product,
        number=number,
        action=action,
        summary=summary[:500],
        snapshot=after,
        actor=request.user,
    )
    audit.record(
        action=f"lifecycle.{action}",
        actor=request.user,
        request=request,
        object_type="lifecycle_product",
        object_id=product.pk,
        object_label=str(product),
        before=before,
        after=after,
        detail=summary,
    )


def _queue(product_id=None) -> None:
    from .tasks import reassess

    transaction.on_commit(lambda: reassess.delay(str(product_id) if product_id else None))


def _keys(obj) -> None:
    if isinstance(obj, LifecycleProduct):
        obj.vendor_key, obj.name_key, obj.release_key = (
            key(obj.vendor),
            key(obj.name),
            key(obj.release),
        )


def _duplicate_product(data: dict, exclude=None) -> bool:
    qs = LifecycleProduct.objects.filter(
        kind=data["kind"],
        vendor_key=key(data["vendor"]),
        name_key=key(data["name"]),
        release_key=key(data.get("release", "")),
    )
    if exclude is not None:
        qs = qs.exclude(pk=exclude.pk)
    return qs.exists()


def _duplicate_error():
    return ApiError(
        "VALIDATION_ERROR",
        "A catalogue product with this kind, vendor, name and release already exists.",
        422,
        {"name": ["Already in the catalogue."]},
    )


# --- Products ---------------------------------------------------------------------------------


@transaction.atomic
def create_product(request, data: dict) -> LifecycleProduct:
    if _duplicate_product(data):
        raise _duplicate_error()
    product = LifecycleProduct(**data, created_by=request.user, modified_by=request.user)
    _keys(product)
    product.save()
    _revise(request, product, "product.create", f"Created {product}")
    _queue()
    return product


PRODUCT_FIELDS = ("kind", "vendor", "name", "release", "family", "description", "is_active")


@transaction.atomic
def update_product(request, product: LifecycleProduct, data: dict, expected) -> LifecycleProduct:
    product = LifecycleProduct.objects.select_for_update().get(pk=product.pk)
    check_version(product, expected)
    before = snapshot(product)
    merged = {f: data.get(f, getattr(product, f)) for f in PRODUCT_FIELDS}
    if _duplicate_product(merged, exclude=product):
        raise _duplicate_error()
    identity_changed = (
        any(
            key(merged[f]) != key(getattr(product, f))
            for f in ("kind", "vendor", "name", "release")
        )
        or merged["is_active"] != product.is_active
    )
    for name in PRODUCT_FIELDS:
        setattr(product, name, merged[name])
    _keys(product)
    product.modified_by = request.user
    product.version = F("version") + 1
    product.save()
    product.refresh_from_db()
    _revise(request, product, "product.update", data.get("reason", ""), before)
    _queue(None if identity_changed else product.pk)
    return product


@transaction.atomic
def set_statement(request, product, statement: str, source, verify: bool, expected):
    """Record (and optionally verify) the vendor's 'supported' / 'not announced' statement."""
    product = LifecycleProduct.objects.select_for_update().get(pk=product.pk)
    check_version(product, expected)
    before = snapshot(product)
    if statement and source is None:
        raise ApiError(
            "VALIDATION_ERROR",
            "A support statement needs a source.",
            422,
            {"statement_source": ["Choose the source that states this."]},
        )
    product.support_statement = statement
    product.statement_source = source if statement else None
    if statement and verify:
        product.statement_verified_by, product.statement_verified_at = request.user, timezone.now()
    else:
        product.statement_verified_by, product.statement_verified_at = None, None
    product.modified_by = request.user
    product.version = F("version") + 1
    product.save()
    product.refresh_from_db()
    _revise(request, product, "product.statement", statement or "cleared", before)
    _queue(product.pk)
    return product


# --- Aliases ----------------------------------------------------------------------------------


@transaction.atomic
def add_alias(request, product: LifecycleProduct, data: dict) -> LifecycleAlias:
    product = LifecycleProduct.objects.select_for_update().get(pk=product.pk)
    before = snapshot(product)
    value_key, release_key = key(data["value"]), key(data.get("release", ""))
    allowed = {
        LifecycleProduct.Kind.HARDWARE: {"model", "part_number"},
        LifecycleProduct.Kind.OPERATING_SYSTEM: {"os_name"},
        LifecycleProduct.Kind.FIRMWARE: {"os_name"},
        LifecycleProduct.Kind.SOFTWARE: {"product_name"},
    }[product.kind]
    if data["kind"] not in allowed:
        raise ApiError(
            "VALIDATION_ERROR",
            "This alias type does not apply to the product kind.",
            422,
            {"kind": [f"Use one of: {', '.join(sorted(allowed))}."]},
        )
    clash = LifecycleAlias.objects.filter(
        kind=data["kind"], value_key=value_key, release_key=release_key, product__kind=product.kind
    ).exclude(product=product)
    if product.kind == LifecycleProduct.Kind.HARDWARE:
        clash = clash.filter(product__vendor_key=product.vendor_key)
    if clash.exists():
        raise ApiError(
            "VALIDATION_ERROR",
            "This alias already points to another product; one alias must identify one product.",
            422,
            {"value": [f"Already used by {clash.first().product}."]},
        )
    alias, created = LifecycleAlias.objects.get_or_create(
        product=product,
        kind=data["kind"],
        value_key=value_key,
        release_key=release_key,
        defaults={
            "value": data["value"].strip(),
            "release": data.get("release", "").strip(),
            "note": data.get("note", ""),
            "created_by": request.user,
        },
    )
    if created:
        _revise(
            request, product, "alias.create", f"Alias {alias.value} {alias.release}".strip(), before
        )
        _queue()
    return alias


@transaction.atomic
def remove_alias(request, alias: LifecycleAlias, reason: str) -> None:
    product = LifecycleProduct.objects.select_for_update().get(pk=alias.product_id)
    before = snapshot(product)
    label = f"{alias.value} {alias.release}".strip()
    alias.delete()
    _revise(request, product, "alias.delete", f"Removed alias {label}: {reason}", before)
    _queue()


@transaction.atomic
def add_vendor_alias(request, alias: str, vendor: str) -> VendorAlias:
    alias_key = key(alias)
    if alias_key == key(vendor):
        raise ApiError(
            "VALIDATION_ERROR",
            "An alias must differ from the vendor name.",
            422,
            {"alias": ["Same as vendor."]},
        )
    if VendorAlias.objects.filter(alias_key=alias_key).exists():
        raise ApiError(
            "VALIDATION_ERROR",
            "This vendor alias already exists.",
            422,
            {"alias": ["Already defined."]},
        )
    obj = VendorAlias.objects.create(
        alias=alias.strip(), alias_key=alias_key, vendor=vendor.strip(), created_by=request.user
    )
    audit.record(
        action="lifecycle.vendor_alias.create",
        actor=request.user,
        request=request,
        object_type="lifecycle_vendor_alias",
        object_id=obj.pk,
        object_label=f"{obj.alias} -> {obj.vendor}",
    )
    _queue()
    return obj


@transaction.atomic
def remove_vendor_alias(request, obj: VendorAlias, reason: str) -> None:
    audit.record(
        action="lifecycle.vendor_alias.delete",
        actor=request.user,
        request=request,
        object_type="lifecycle_vendor_alias",
        object_id=obj.pk,
        object_label=f"{obj.alias} -> {obj.vendor}",
        detail=reason,
    )
    obj.delete()
    _queue()


# --- Sources ----------------------------------------------------------------------------------


def _source_snapshot(source: LifecycleSource) -> dict:
    return {
        "publisher": source.publisher,
        "title": source.title,
        "url": source.url,
        "source_type": source.source_type,
        "document_ref": source.document_ref,
        "collected_on": source.collected_on.isoformat(),
        "last_verified_on": source.last_verified_on.isoformat()
        if source.last_verified_on
        else None,
        "notes": source.notes,
    }


@transaction.atomic
def create_source(request, data: dict) -> LifecycleSource:
    source = LifecycleSource.objects.create(**data, created_by=request.user)
    audit.record(
        action="lifecycle.source.create",
        actor=request.user,
        request=request,
        object_type="lifecycle_source",
        object_id=source.pk,
        object_label=source.title,
        after=_source_snapshot(source),
    )
    return source


@transaction.atomic
def update_source(request, source: LifecycleSource, data: dict, expected) -> LifecycleSource:
    source = LifecycleSource.objects.select_for_update().get(pk=source.pk)
    check_version(source, expected)
    before = _source_snapshot(source)
    for name, value in data.items():
        setattr(source, name, value)
    source.version = F("version") + 1
    source.save()
    source.refresh_from_db()
    audit.record(
        action="lifecycle.source.update",
        actor=request.user,
        request=request,
        object_type="lifecycle_source",
        object_id=source.pk,
        object_label=source.title,
        before=before,
        after=_source_snapshot(source),
    )
    product_ids = set(source.milestones.values_list("product_id", flat=True))
    for product in LifecycleProduct.objects.filter(pk__in=product_ids):
        _revise(request, product, "source.update", f"Source '{source.title}' changed")
    _queue()
    return source


# --- Milestones -------------------------------------------------------------------------------


@transaction.atomic
def add_milestone(request, product: LifecycleProduct, data: dict) -> LifecycleMilestone:
    product = LifecycleProduct.objects.select_for_update().get(pk=product.pk)
    before = snapshot(product)
    milestone = LifecycleMilestone.objects.create(product=product, created_by=request.user, **data)
    _revise(
        request,
        product,
        "milestone.create",
        f"{milestone.get_milestone_type_display()} {milestone.date.isoformat()} "
        "(awaiting verification)",
        before,
    )
    _queue(product.pk)
    return milestone


@transaction.atomic
def update_milestone(request, milestone: LifecycleMilestone, data: dict, expected):
    """Editing a date or source resets verification: changed evidence must be re-verified."""
    milestone = LifecycleMilestone.objects.select_for_update().get(pk=milestone.pk)
    check_version(milestone, expected)
    product = milestone.product
    before = snapshot(product)
    changed = any(getattr(milestone, k) != v for k, v in data.items() if k != "reason")
    for name in ("milestone_type", "date", "source", "notes"):
        if name in data:
            setattr(milestone, name, data[name])
    if changed:
        milestone.verification = LifecycleMilestone.Verification.PENDING
        milestone.reviewed_by, milestone.reviewed_at = None, None
    milestone.version = F("version") + 1
    milestone.save()
    milestone.refresh_from_db()
    _revise(request, product, "milestone.update", data.get("reason", ""), before)
    _queue(product.pk)
    return milestone


@transaction.atomic
def review_milestone(request, milestone: LifecycleMilestone, decision: str, note: str, expected):
    milestone = LifecycleMilestone.objects.select_for_update().get(pk=milestone.pk)
    check_version(milestone, expected)
    product = milestone.product
    before = snapshot(product)
    milestone.verification = decision
    milestone.reviewed_by, milestone.reviewed_at = request.user, timezone.now()
    if note:
        milestone.notes = (f"{milestone.notes}\n{note}" if milestone.notes else note)[:1000]
    milestone.version = F("version") + 1
    milestone.save()
    milestone.refresh_from_db()
    _revise(
        request,
        product,
        f"milestone.{decision}",
        f"{milestone.get_milestone_type_display()} {milestone.date.isoformat()}: {note}".strip(
            ": "
        ),
        before,
    )
    _queue(product.pk)
    return milestone


# --- Reassessment -----------------------------------------------------------------------------


class Policy:
    def __init__(self):
        self.today = today_utc()
        self.thresholds = thresholds()
        self.count_extended = settings.ITAM_LIFECYCLE_COUNT_EXTENDED_SUPPORT
        self.catalogue = matching.Catalogue.load()
        self.rules = matching.CategoryRules()
        self._products: dict = {}

    def product(self, product_id):
        if product_id not in self._products:
            self._products[product_id] = (
                LifecycleProduct.objects.prefetch_related("milestones__source")
                .filter(pk=product_id)
                .first()
            )
        return self._products[product_id]


def reassess_assets(asset_ids, policy: Policy | None = None) -> dict:
    """Recalculate matches and assessments for the given assets (in batches)."""
    policy = policy or Policy()
    counts = {"assets": 0, "changed": 0}
    ids = list(asset_ids)
    for start in range(0, len(ids), BATCH):
        batch = ids[start : start + BATCH]
        with transaction.atomic():
            counts["changed"] += _reassess_batch(batch, policy)
        counts["assets"] += len(batch)
    return counts


def _reassess_batch(asset_ids, policy: Policy) -> int:
    assets = Asset.objects.filter(pk__in=asset_ids).select_related("category")
    matches = {
        (m.asset_id, m.dimension): m
        for m in AssetLifecycleMatch.objects.select_for_update().filter(asset_id__in=asset_ids)
    }
    current = {
        (a.asset_id, a.dimension): a
        for a in LifecycleAssessment.objects.filter(asset_id__in=asset_ids)
    }
    exceptions = {
        (e.asset_id, e.dimension): e
        for e in LifecycleException.objects.filter(
            asset_id__in=asset_ids, revoked_at__isnull=True, expires_on__gte=policy.today
        )
    }
    provenance: dict = {}
    for p in FieldProvenance.objects.filter(asset_id__in=asset_ids).select_related("instance"):
        provenance.setdefault(p.asset_id, {})[p.field] = p

    changed = 0
    for asset in assets:
        effective = []
        for dimension in ASSESSED_DIMENSIONS:
            match = _update_match(
                asset,
                dimension,
                matches.get((asset.pk, dimension)),
                provenance.get(asset.pk, {}),
                policy,
            )
            row = _assess(asset, dimension, match, exceptions.get((asset.pk, dimension)), policy)
            if _store(asset, dimension, row, current.get((asset.pk, dimension))):
                changed += 1
            effective.append(row["effective_status"])
        summary = assessment.summarize(effective)
        if asset.support_status != summary:
            Asset.objects.filter(pk=asset.pk).update(support_status=summary)
    return changed


def _update_match(asset, dimension, match, provenance, policy: Policy) -> AssetLifecycleMatch:
    State, Method = AssetLifecycleMatch.State, AssetLifecycleMatch.Method
    observed_key = matching.observed_key(asset, dimension)
    observed = matching.observed_values(asset, dimension, provenance)
    if match is None:
        match = AssetLifecycleMatch(asset=asset, dimension=dimension, observed_key=observed_key)
    rejected = set(match.rejected_products)

    if not policy.rules.applicable(asset.category_id, dimension):
        fields = {
            "state": State.NOT_APPLICABLE,
            "method": Method.NONE,
            "product_id": None,
            "candidates": [],
            "reason": "Not applicable to this asset category.",
        }
    elif (
        match.pk
        and match.method == Method.MANUAL
        and match.state == State.MATCHED
        and match.observed_key == observed_key
        and match.product_id
        and policy.product(match.product_id) is not None
        and policy.product(match.product_id).is_active
    ):
        return match  # a reviewer's decision stands while the observed values are unchanged
    else:
        result = matching.match(policy.catalogue, asset, dimension, rejected)
        fields = {
            "state": result.state,
            "method": result.method,
            "product_id": result.product_id,
            "candidates": result.candidates,
            "reason": result.reason,
        }
        if match.pk and match.method == Method.MANUAL and match.observed_key != observed_key:
            fields["reason"] = (
                f"Observed values changed since the reviewer's decision. {result.reason}"
            )
    fields["observed"] = observed
    fields["observed_key"] = observed_key
    dirty = not match.pk or any(
        str(getattr(match, k) or "") != str(v or "")
        if k == "product_id"
        else getattr(match, k) != v
        for k, v in fields.items()
    )
    if dirty:
        for k, v in fields.items():
            setattr(match, k, v)
        if match.pk:
            match.version += 1
        match.save()
    return match


def _assess(asset, dimension, match, exception, policy: Policy) -> dict:
    State = AssetLifecycleMatch.State
    product = None
    if match.state == State.NOT_APPLICABLE:
        outcome = assessment.Outcome(Status.NOT_APPLICABLE, reasons=[match.reason])
    elif match.state == State.CANDIDATE:
        outcome = assessment.Outcome(
            Status.UNVERIFIED,
            reasons=[match.reason, "Review the suggested match to assess support."],
        )
    elif match.state == State.NO_MATCH or not match.product_id:
        outcome = assessment.Outcome(Status.UNKNOWN, reasons=[match.reason])
    else:
        product = policy.product(match.product_id)
        outcome = assessment.evaluate(
            assessment.claims_for(product),
            policy.today,
            policy.thresholds,
            policy.count_extended,
            product.support_statement,
            product.statement_verified_at is not None and product.statement_source_id is not None,
        )
        outcome.reasons.insert(0, f"{match.get_method_display()}: {product}.")
    effective = outcome.status
    if exception is not None:
        effective = exception.status
        outcome.reasons.append(
            f"Exception until {exception.expires_on.isoformat()} sets the status to "
            f"{Status(exception.status).label.lower()}: {exception.reason}"
        )
    return {
        "status": outcome.status,
        "effective_status": effective,
        "product_id": product.pk if product else None,
        "support_level": outcome.support_level,
        "milestone_type": outcome.milestone_type,
        "milestone_date": outcome.milestone_date,
        "days_remaining": outcome.days_remaining,
        "threshold_days": outcome.threshold_days,
        "evidence_quality": outcome.evidence_quality,
        "milestone_ids": outcome.milestone_ids,
        "reasons": outcome.reasons,
        "exception_id": exception.pk if exception else None,
    }


_HISTORY_KEYS = ("status", "effective_status", "product_id", "milestone_type", "milestone_date")


def _store(asset, dimension, row: dict, existing: LifecycleAssessment | None) -> bool:
    now = timezone.now()
    if existing is None:
        LifecycleAssessment.objects.create(
            asset=asset, dimension=dimension, assessed_on=today_utc(), assessed_at=now, **row
        )
        _history(asset, dimension, row)
        return True
    significant = any(str(getattr(existing, k) or "") != str(row[k] or "") for k in _HISTORY_KEYS)
    if significant:
        _history(asset, dimension, row)
    for k, v in row.items():
        setattr(existing, k, v)
    existing.assessed_on, existing.assessed_at = today_utc(), now
    existing.save()
    return significant


def _history(asset, dimension, row: dict) -> None:
    product = (
        LifecycleProduct.objects.filter(pk=row["product_id"]).first() if row["product_id"] else None
    )
    LifecycleAssessmentHistory.objects.create(
        asset=asset,
        dimension=dimension,
        status=row["status"],
        effective_status=row["effective_status"],
        product_label=str(product) if product else "",
        milestone_type=row["milestone_type"] or "",
        milestone_date=row["milestone_date"],
        reasons=row["reasons"],
    )


def reassess_all() -> dict:
    ids = Asset.objects.filter(archived_at__isnull=True).values_list("pk", flat=True)
    return reassess_assets(ids)


def reassess_product(product_id) -> dict:
    ids = (
        AssetLifecycleMatch.objects.filter(product_id=product_id, asset__archived_at__isnull=True)
        .values_list("asset_id", flat=True)
        .distinct()
    )
    return reassess_assets(ids)


def request_reassessment(request, scope: str, object_id=None) -> None:
    audit.record(
        action="lifecycle.reassess",
        actor=request.user,
        request=request,
        object_type="lifecycle",
        object_id=object_id or "",
        object_label=scope,
    )


# --- Match review -----------------------------------------------------------------------------


def _alias_for(match: AssetLifecycleMatch, product: LifecycleProduct) -> dict | None:
    asset = match.asset
    if product.kind == LifecycleProduct.Kind.HARDWARE:
        if not asset.model or key(asset.model) == product.name_key:
            return None
        return {"kind": "model", "value": asset.model, "release": ""}
    if asset.os_name:
        if key(asset.os_name) == product.name_key and key(asset.os_version) == product.release_key:
            return None
        return {"kind": "os_name", "value": asset.os_name, "release": asset.os_version}
    if asset.firmware_version:
        return {"kind": "os_name", "value": asset.firmware_version, "release": ""}
    return None


def approve_match(
    request,
    match: AssetLifecycleMatch,
    product: LifecycleProduct,
    remember: bool,
    note: str,
    expected,
) -> AssetLifecycleMatch:
    with transaction.atomic():
        match = (
            AssetLifecycleMatch.objects.select_for_update().select_related("asset").get(pk=match.pk)
        )
        check_version(match, expected)
        if product.dimension != match.dimension:
            raise ApiError(
                "VALIDATION_ERROR",
                "The product is for a different lifecycle dimension.",
                422,
                {"product": ["Choose a product of the matching kind."]},
            )
        if match.state == AssetLifecycleMatch.State.NOT_APPLICABLE:
            raise ApiError(
                "LIFECYCLE_NOT_APPLICABLE", "This dimension does not apply to the asset.", 409
            )
        before = {"state": match.state, "product": str(match.product_id or "")}
        match.state = AssetLifecycleMatch.State.MATCHED
        match.method = AssetLifecycleMatch.Method.MANUAL
        match.product = product
        match.candidates = []
        match.reason = f"Approved by {request.user.username}."
        match.reviewed_by, match.reviewed_at, match.review_note = request.user, timezone.now(), note
        match.rejected_products = [p for p in match.rejected_products if p != str(product.pk)]
        match.version += 1
        match.save()
        audit.record(
            action="lifecycle.match.approve",
            actor=request.user,
            request=request,
            object_type="asset",
            object_id=match.asset_id,
            object_label=match.asset.name,
            before=before,
            after={
                "dimension": match.dimension,
                "product": str(product),
                "remember_alias": remember,
            },
            detail=note,
        )
        if remember and (alias := _alias_for(match, product)):
            add_alias(
                request, product, {**alias, "note": f"From approved match on {match.asset.name}"}
            )
    reassess_assets([match.asset_id])
    match.refresh_from_db()
    return match


def reject_match(request, match: AssetLifecycleMatch, product_ids: list[str], note: str, expected):
    with transaction.atomic():
        match = (
            AssetLifecycleMatch.objects.select_for_update().select_related("asset").get(pk=match.pk)
        )
        check_version(match, expected)
        targets = (
            product_ids
            or [c["product_id"] for c in match.candidates]
            or ([str(match.product_id)] if match.product_id else [])
        )
        if not targets:
            raise ApiError(
                "LIFECYCLE_NOTHING_TO_REJECT", "There is no suggested product to reject.", 409
            )
        match.rejected_products = sorted(set(match.rejected_products) | set(targets))
        match.reviewed_by, match.reviewed_at, match.review_note = request.user, timezone.now(), note
        if match.method == AssetLifecycleMatch.Method.MANUAL:
            match.method = AssetLifecycleMatch.Method.NONE
        match.version += 1
        match.save()
        audit.record(
            action="lifecycle.match.reject",
            actor=request.user,
            request=request,
            object_type="asset",
            object_id=match.asset_id,
            object_label=match.asset.name,
            after={"dimension": match.dimension, "rejected": targets},
            detail=note,
        )
    reassess_assets([match.asset_id])
    match.refresh_from_db()
    return match


# --- Exceptions -------------------------------------------------------------------------------


def create_exception(request, asset: Asset, data: dict) -> LifecycleException:
    if data["expires_on"] <= today_utc():
        raise ApiError(
            "VALIDATION_ERROR",
            "The expiry date must be in the future.",
            422,
            {"expires_on": ["Choose a date after today."]},
        )
    if data["expires_on"] > today_utc() + timedelta(
        days=settings.ITAM_LIFECYCLE_MAX_EXCEPTION_DAYS
    ):
        raise ApiError(
            "VALIDATION_ERROR",
            f"Exceptions can last at most {settings.ITAM_LIFECYCLE_MAX_EXCEPTION_DAYS} days.",
            422,
            {"expires_on": ["Too far in the future."]},
        )
    with transaction.atomic():
        if (
            LifecycleException.objects.filter(
                asset=asset, dimension=data["dimension"], revoked_at__isnull=True
            )
            .exclude(expires_on__lt=today_utc())
            .exists()
        ):
            raise ApiError(
                "LIFECYCLE_EXCEPTION_EXISTS",
                "An active exception already exists for this dimension; revoke it first.",
                409,
            )
        # Expired, unrevoked exceptions are closed so the one-open-exception rule holds.
        LifecycleException.objects.filter(
            asset=asset,
            dimension=data["dimension"],
            revoked_at__isnull=True,
            expires_on__lt=today_utc(),
        ).update(revoked_at=timezone.now(), revoke_reason="Expired")
        exc = LifecycleException.objects.create(asset=asset, approved_by=request.user, **data)
        audit.record(
            action="lifecycle.exception.create",
            actor=request.user,
            request=request,
            object_type="asset",
            object_id=asset.pk,
            object_label=asset.name,
            after={
                "dimension": exc.dimension,
                "status": exc.status,
                "expires_on": exc.expires_on.isoformat(),
                "compensating_controls": exc.compensating_controls,
            },
            detail=exc.reason,
        )
    reassess_assets([asset.pk])
    return exc


def revoke_exception(request, exc: LifecycleException, reason: str, expected) -> LifecycleException:
    with transaction.atomic():
        exc = LifecycleException.objects.select_for_update().select_related("asset").get(pk=exc.pk)
        check_version(exc, expected)
        if exc.revoked_at is not None:
            raise ApiError("LIFECYCLE_EXCEPTION_CLOSED", "This exception is already closed.", 409)
        exc.revoked_by, exc.revoked_at, exc.revoke_reason = request.user, timezone.now(), reason
        exc.version += 1
        exc.save()
        audit.record(
            action="lifecycle.exception.revoke",
            actor=request.user,
            request=request,
            object_type="asset",
            object_id=exc.asset_id,
            object_label=exc.asset.name,
            after={"dimension": exc.dimension},
            detail=reason,
        )
    reassess_assets([exc.asset_id])
    return exc


def record_system_audit(action: str, detail: str) -> None:
    audit.record(
        action=action, source=AuditEvent.Source.SYSTEM, object_type="lifecycle", detail=detail
    )
