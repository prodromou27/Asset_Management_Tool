"""License products, entitlements and allocations maintained by people (Task 016b, ASM-55).

Every change is audited. Entitlements are retired and allocations ended, never deleted.
Totals are arithmetic over the stored records (purchased units of entitlements in term,
units allocated from them); they are labelled as such and are not a compliance verdict
(docs/06: V1 reports inventory/allocation, not license compliance).
"""

from dataclasses import dataclass

from django.db import IntegrityError, transaction
from django.db.models import Count, F, Q, Sum
from django.utils import timezone

from apps.audit import services as audit
from apps.lifecycle.matching import key
from apps.lifecycle.services import today_utc
from apps.organizations.scope import ALL, accessible_site_ids
from apps.organizations.services import check_version
from config.api import ApiError

from .models import EntitlementAllocation, LicenseEntitlement, LicenseProduct

PRODUCT_FIELDS = ("publisher", "name", "sku", "metric", "software_product", "note", "is_active")
ENTITLEMENT_FIELDS = (
    "reference",
    "quantity",
    "starts_on",
    "ends_on",
    "supplier",
    "owner",
    "note",
)


def _value(v):
    if hasattr(v, "pk"):
        return str(v.pk)
    if hasattr(v, "isoformat"):
        return v.isoformat()
    return v


def _snap(obj, fields) -> dict:
    return {f: _value(getattr(obj, f)) for f in fields}


def product_key(publisher: str, name: str, sku: str) -> str:
    return "|".join((key(publisher), key(name), key(sku)))[:530]


def _record(request, action, obj, label, before=None, after=None, detail=""):
    audit.record(
        action=f"license.{action}",
        actor=request.user,
        request=request,
        object_type=obj._meta.model_name,
        object_id=obj.pk,
        object_label=label,
        before=before,
        after=after,
        detail=detail,
    )


def _invalid(field: str, message: str, summary: str | None = None):
    return ApiError("VALIDATION_ERROR", summary or message, 422, {field: [message]})


# --- Products ---------------------------------------------------------------------------------


def _duplicate_product(identity: str, exclude=None) -> bool:
    qs = LicenseProduct.objects.filter(identity_key=identity)
    if exclude is not None:
        qs = qs.exclude(pk=exclude.pk)
    return qs.exists()


def _duplicate_product_error():
    return _invalid("name", "A license product with this publisher, name and SKU exists already.")


@transaction.atomic
def create_product(request, data: dict) -> LicenseProduct:
    product = LicenseProduct(**data, created_by=request.user, modified_by=request.user)
    product.identity_key = product_key(product.publisher, product.name, product.sku)
    if _duplicate_product(product.identity_key):
        raise _duplicate_product_error()
    product.save()
    _record(request, "product.create", product, str(product), after=_snap(product, PRODUCT_FIELDS))
    return product


@transaction.atomic
def update_product(request, product: LicenseProduct, data: dict, expected) -> LicenseProduct:
    product = LicenseProduct.objects.select_for_update().get(pk=product.pk)
    check_version(product, expected)
    before = _snap(product, PRODUCT_FIELDS)
    for name in PRODUCT_FIELDS:
        if name in data:
            setattr(product, name, data[name])
    product.identity_key = product_key(product.publisher, product.name, product.sku)
    if _duplicate_product(product.identity_key, exclude=product):
        raise _duplicate_product_error()
    product.modified_by = request.user
    product.version = F("version") + 1
    product.save()
    product.refresh_from_db()
    _record(
        request,
        "product.update",
        product,
        str(product),
        before=before,
        after=_snap(product, PRODUCT_FIELDS),
    )
    return product


# --- Entitlements -----------------------------------------------------------------------------


def _check_term(starts_on, ends_on) -> None:
    if starts_on and ends_on and ends_on < starts_on:
        raise _invalid("ends_on", "The end date is before the start date.")


def _duplicate_reference(product, reference: str, exclude=None):
    qs = LicenseEntitlement.objects.filter(product=product, reference_key=key(reference))
    if exclude is not None:
        qs = qs.exclude(pk=exclude.pk)
    if qs.exists():
        raise _invalid("reference", "This product already has an entitlement with this reference.")


@transaction.atomic
def create_entitlement(
    request, product: LicenseProduct, data: dict, source=LicenseEntitlement.Source.MANUAL
) -> LicenseEntitlement:
    if not product.is_active:
        raise _invalid("product", "This license product is inactive.")
    _check_term(data.get("starts_on"), data.get("ends_on"))
    _duplicate_reference(product, data["reference"])
    entitlement = LicenseEntitlement(
        product=product,
        **{f: data[f] for f in ENTITLEMENT_FIELDS if f in data},
        source=source,
        created_by=request.user,
        modified_by=request.user,
    )
    entitlement.reference_key = key(entitlement.reference)
    entitlement.save()
    _record(
        request,
        "entitlement.create",
        entitlement,
        str(entitlement),
        after=_snap(entitlement, ENTITLEMENT_FIELDS),
    )
    return entitlement


@transaction.atomic
def update_entitlement(
    request, entitlement: LicenseEntitlement, data: dict, expected
) -> LicenseEntitlement:
    entitlement = LicenseEntitlement.objects.select_for_update().get(pk=entitlement.pk)
    check_version(entitlement, expected)
    if entitlement.retired_at:
        raise ApiError("ENTITLEMENT_RETIRED", "Retired entitlements cannot be changed.", 409)
    before = _snap(entitlement, ENTITLEMENT_FIELDS)
    merged = {f: data.get(f, getattr(entitlement, f)) for f in ENTITLEMENT_FIELDS}
    _check_term(merged["starts_on"], merged["ends_on"])
    _duplicate_reference(entitlement.product, merged["reference"], exclude=entitlement)
    for name, value in merged.items():
        setattr(entitlement, name, value)
    entitlement.reference_key = key(entitlement.reference)
    entitlement.modified_by = request.user
    entitlement.version = F("version") + 1
    entitlement.save()
    entitlement.refresh_from_db()
    _record(
        request,
        "entitlement.update",
        entitlement,
        str(entitlement),
        before=before,
        after=_snap(entitlement, ENTITLEMENT_FIELDS),
        detail=data.get("reason", ""),
    )
    return entitlement


@transaction.atomic
def retire_entitlement(request, entitlement: LicenseEntitlement, reason: str, expected):
    """Retire an entitlement (contract ended, recorded in error, ...). Its open allocations
    end with it so no units stay allocated from a retired purchase."""
    entitlement = LicenseEntitlement.objects.select_for_update().get(pk=entitlement.pk)
    check_version(entitlement, expected)
    if entitlement.retired_at:
        raise ApiError("ENTITLEMENT_RETIRED", "This entitlement is already retired.", 409)
    now = timezone.now()
    ended = EntitlementAllocation.objects.filter(
        entitlement=entitlement, ended_at__isnull=True
    ).update(
        ended_at=now, ended_by=request.user, ended_reason=f"Entitlement retired: {reason}"[:500]
    )
    entitlement.retired_at, entitlement.retired_by = now, request.user
    entitlement.retired_reason = reason[:500]
    entitlement.modified_by = request.user
    entitlement.version = F("version") + 1
    entitlement.save()
    entitlement.refresh_from_db()
    _record(
        request,
        "entitlement.retire",
        entitlement,
        str(entitlement),
        after={"ended_allocations": ended},
        detail=reason,
    )
    return entitlement


# --- Allocations ------------------------------------------------------------------------------


def allocate(request, entitlement: LicenseEntitlement, data: dict) -> EntitlementAllocation:
    """Allocate units to an asset (already checked to be in the caller's sites) or a named
    user. Allocating more than was purchased is recorded, and shown as such."""
    asset, user_name = data.get("asset"), " ".join((data.get("user_name") or "").split())
    if bool(asset) == bool(user_name):
        raise _invalid("asset", "Allocate to either an asset or a named user.")
    status = entitlement.status(today_utc())
    if status in ("retired", "expired"):
        raise ApiError(
            "ENTITLEMENT_NOT_USABLE",
            f"This entitlement is {status.replace('_', ' ')}; allocate from one in term.",
            409,
        )
    row = EntitlementAllocation(
        entitlement=entitlement,
        asset=asset,
        user_name=user_name[:320],
        user_key=key(user_name)[:320],
        units=data.get("units") or 1,
        note=(data.get("note") or "")[:500],
        allocated_at=timezone.now(),
        allocated_by=request.user,
    )
    try:
        with transaction.atomic():
            row.save()
            _record(
                request,
                "allocation.create",
                entitlement,
                str(entitlement),
                after={
                    "asset": str(asset.pk) if asset else None,
                    "asset_name": asset.name if asset else None,
                    "user": user_name or None,
                    "units": row.units,
                },
            )
    except IntegrityError as exc:
        raise ApiError(
            "ALLOCATION_EXISTS",
            "This entitlement is already allocated to that " + ("asset." if asset else "user."),
            409,
        ) from exc
    return row


@transaction.atomic
def end_allocation(request, row: EntitlementAllocation, reason: str) -> EntitlementAllocation:
    row = EntitlementAllocation.objects.select_for_update().get(pk=row.pk)
    if row.ended_at is not None:
        raise ApiError("ALLOCATION_ENDED", "This allocation has already ended.", 409)
    row.ended_at, row.ended_by, row.ended_reason = timezone.now(), request.user, reason[:500]
    row.save(update_fields=["ended_at", "ended_by", "ended_reason"])
    _record(
        request,
        "allocation.end",
        row.entitlement,
        str(row.entitlement),
        after={
            "asset": str(row.asset_id) if row.asset_id else None,
            "user": row.user_name or None,
            "units": row.units,
        },
        detail=reason,
    )
    return row


# --- Totals -----------------------------------------------------------------------------------


@dataclass
class Totals:
    purchased: int = 0  # units of entitlements in term (not retired, started, not expired)
    allocated: int = 0  # units of open allocations from those entitlements
    entitlements_in_term: int = 0

    @property
    def available(self) -> int:
        return self.purchased - self.allocated


def in_term_q(today, prefix: str = "") -> Q:
    p = prefix
    return (
        Q(**{f"{p}retired_at__isnull": True})
        & (Q(**{f"{p}starts_on__isnull": True}) | Q(**{f"{p}starts_on__lte": today}))
        & (Q(**{f"{p}ends_on__isnull": True}) | Q(**{f"{p}ends_on__gte": today}))
    )


def totals_for(product_ids, today=None) -> dict:
    """Totals per license product ID. Allocations count across all sites: an entitlement
    is organisation-wide even when the asset it is allocated to is not visible to the
    reader (only the number is shown, never the asset)."""
    today = today or today_utc()
    result = {pid: Totals() for pid in product_ids}
    for row in (
        LicenseEntitlement.objects.filter(in_term_q(today), product_id__in=product_ids)
        .values("product_id")
        .annotate(units=Sum("quantity"), n=Count("pk"))
    ):
        t = result[row["product_id"]]
        t.purchased, t.entitlements_in_term = row["units"] or 0, row["n"] or 0
    for row in (
        EntitlementAllocation.objects.filter(
            in_term_q(today, "entitlement__"),
            ended_at__isnull=True,
            entitlement__product_id__in=product_ids,
        )
        .values("entitlement__product_id")
        .annotate(units=Sum("units"))
    ):
        result[row["entitlement__product_id"]].allocated = row["units"] or 0
    return result


def allocated_units(entitlement_ids) -> dict:
    return {
        row["entitlement_id"]: row["units"] or 0
        for row in EntitlementAllocation.objects.filter(
            entitlement_id__in=entitlement_ids, ended_at__isnull=True
        )
        .values("entitlement_id")
        .annotate(units=Sum("units"))
    }


def visible_allocations(user):
    """Allocations a reader may list: named-user allocations and allocations to assets in
    the reader's sites."""
    rows = EntitlementAllocation.objects.select_related(
        "entitlement__product", "asset__site", "allocated_by", "ended_by"
    )
    scope = accessible_site_ids(user)
    if scope is not ALL:
        rows = rows.filter(Q(asset__isnull=True) | Q(asset__site_id__in=scope))
    return rows
