"""Manually maintained software entitlements (docs/11 template table: "License | vendor SKU +
entitlement ID | product, quantity, term"). Graph license counts can never be imported."""

import datetime as dt
import re

from apps.accounts import catalog
from apps.licensing import entitlements as services
from apps.licensing.models import LicenseEntitlement, LicenseProduct
from apps.lifecycle.matching import key
from config.api import ApiError

from .base import Column, Context, Family, Plan, RowError, check_formulas, choice, text

_DATE = re.compile(r"^(\d{4}-\d{2}-\d{2})(?:[ T]00:00(?::00)?)?$")
FIELDS = ("quantity", "starts_on", "ends_on", "supplier", "owner", "note")


def _date(values: dict, name: str):
    match = _DATE.match(text(values, name, 30))
    if match:
        try:
            return dt.date.fromisoformat(match.group(1))
        except ValueError:
            pass
    raise RowError(f"{name}: use a date like 2027-01-31.")


def _raw(value):
    return value.isoformat() if isinstance(value, dt.date) else value


class EntitlementFamily(Family):
    code = "license_entitlement"
    label = "License entitlements"
    version = 1
    description = (
        "Create or update purchased license entitlements (manually maintained). A missing "
        "license product is created. Rows never retire entitlements or change allocations."
    )
    match_help = "Matches on product (publisher + name + SKU) and reference (case-insensitive)."
    permission = catalog.LICENSES_MANAGE
    columns = (
        Column("publisher", "Publisher", "", "", "Example Software Corp"),
        Column("product", "Product", "always", "License product name.", "Example CAD"),
        Column("sku", "Vendor SKU", "", "Part number, if any.", "ECAD-STD-1Y"),
        Column(
            "metric",
            "Metric",
            "",
            "New products: user, device, core, concurrent, subscription or other.",
            "user",
        ),
        Column("reference", "Reference", "always", "Agreement, order or contract number.", "PO-1"),
        Column("quantity", "Quantity", "create", "Purchased units (whole number).", "25"),
        Column("starts_on", "Starts", "", "YYYY-MM-DD.", "2026-01-01"),
        Column("ends_on", "Ends", "", "YYYY-MM-DD; empty for perpetual.", "2026-12-31"),
        Column("supplier", "Supplier", "", "", "Example Reseller Ltd"),
        Column("owner", "Owner", "", "Responsible person or team.", "Engineering"),
        Column("note", "Note", "", "", ""),
    )

    def plan(self, ctx: Context, values: dict, row_number: int) -> Plan:
        plan = Plan(action="error")
        try:
            check_formulas(values)
            publisher = " ".join(text(values, "publisher", 200).split())
            name = " ".join(text(values, "product", 200).split())
            sku = " ".join(text(values, "sku", 120).split())
            reference = " ".join(text(values, "reference", 120).split())
            if not name or not reference:
                raise RowError("product and reference are required.")
            identity = services.product_key(publisher, name, sku)
            plan.key = f"{identity}#{key(reference)}"
            first = ctx.remember(plan.key, row_number)
            if first is not None:
                plan.action = "conflict"
                plan.messages.append(f"Same entitlement as row {first}.")
                return plan
            data: dict = {}
            if raw := text(values, "quantity", 12):
                try:
                    data["quantity"] = int(raw)
                except ValueError as exc:
                    raise RowError("quantity: a whole number of units.") from exc
                if not 1 <= data["quantity"] <= 10_000_000:
                    raise RowError("quantity: between 1 and 10,000,000.")
            for name_ in ("starts_on", "ends_on"):
                if values.get(name_, "").strip():
                    data[name_] = _date(values, name_)
            for name_, limit in (("supplier", 200), ("owner", 200), ("note", 2000)):
                if value := text(values, name_, limit):
                    data[name_] = value
            product = LicenseProduct.objects.filter(identity_key=identity).first()
            existing = (
                LicenseEntitlement.objects.filter(product=product, reference_key=key(reference))
                .select_related("product")
                .first()
                if product
                else None
            )
            if existing is None:
                if ctx.mode == "update_matched":
                    plan.action = "skip"
                    plan.messages.append("No matching entitlement (update only).")
                    return plan
                if "quantity" not in data:
                    raise RowError("quantity is required for new entitlements.")
                if (
                    data.get("starts_on")
                    and data.get("ends_on")
                    and data["ends_on"] < data["starts_on"]
                ):
                    raise RowError("ends_on is before starts_on.")
                metric = LicenseProduct.Metric.USER
                if value := text(values, "metric", 20):
                    metric = choice(value, LicenseProduct.Metric.choices, "metric")
                if product is None:
                    plan.messages.append("Creates the license product.")
                elif not product.is_active:
                    raise RowError("The license product is inactive.")
                plan.action, plan.target_label = "create", f"{name} / {reference}"
                plan.data = {
                    "product": product,
                    "new_product": {
                        "publisher": publisher,
                        "name": name,
                        "sku": sku,
                        "metric": metric,
                    },
                    "entitlement": {"reference": reference, **data},
                }
                plan.changes = {
                    k: {"before": None, "after": str(v)}
                    for k, v in {"reference": reference, **data}.items()
                }
                return plan
            plan.target, plan.target_id = existing, str(existing.pk)
            plan.target_label = str(existing)
            if ctx.mode == "create_only":
                plan.action = "skip"
                plan.messages.append("Exists already (create only).")
                return plan
            if existing.retired_at:
                plan.action = "conflict"
                plan.messages.append("The entitlement is retired; it is not changed by imports.")
                return plan
            changes = {}
            for field, value in data.items():
                current = getattr(existing, field)
                if current != value:
                    changes[field] = {
                        "before": str(current) if current not in (None, "") else None,
                        "after": str(value),
                        "before_raw": _raw(current),
                    }
            starts = data.get("starts_on", existing.starts_on)
            ends = data.get("ends_on", existing.ends_on)
            if starts and ends and ends < starts:
                raise RowError("ends_on is before starts_on.")
            if not changes:
                plan.action = "skip"
                plan.messages.append("Unchanged.")
                return plan
            plan.action, plan.changes = "update", changes
            plan.data = {k: data[k] for k in changes}
            return plan
        except RowError as exc:
            plan.messages.append(str(exc))
            return plan

    def apply(self, ctx: Context, plan: Plan, values: dict):
        try:
            if plan.action == "create":
                product = plan.data["product"]
                if product is None:
                    identity = services.product_key(
                        plan.data["new_product"]["publisher"],
                        plan.data["new_product"]["name"],
                        plan.data["new_product"]["sku"],
                    )
                    product = LicenseProduct.objects.filter(identity_key=identity).first()
                    if product is None:
                        product = services.create_product(ctx.request, plan.data["new_product"])
                entitlement = services.create_entitlement(
                    ctx.request,
                    product,
                    plan.data["entitlement"],
                    source=LicenseEntitlement.Source.IMPORT,
                )
            else:
                entitlement = services.update_entitlement(
                    ctx.request,
                    plan.target,
                    {**plan.data, "reason": f"Imported from {ctx.job.filename}"},
                    plan.target.version,
                )
        except ApiError as exc:
            detail = "; ".join(" ".join(v) for v in exc.field_errors.values())
            raise RowError(detail or str(exc.detail)) from exc
        return str(entitlement.pk), str(entitlement), entitlement.version

    def rollback(self, ctx: Context, row) -> tuple[bool, str]:
        entitlement = LicenseEntitlement.objects.filter(pk=row.target_id).first()
        if entitlement is None or entitlement.version != row.version_after:
            return False, "The entitlement changed after the import; correct it by hand."
        if row.action == "create":
            if entitlement.allocations.exists():
                return False, "Units were allocated from it since; retire it by hand."
            services.retire_entitlement(
                ctx.request,
                entitlement,
                f"Rollback of import {ctx.job.pk}",
                entitlement.version,
            )
            return True, "Retired (created by the import)."
        restore = {}
        for field, change in row.changes.items():
            raw = change.get("before_raw")
            if field in ("starts_on", "ends_on"):
                restore[field] = dt.date.fromisoformat(raw) if raw else None
            elif field == "quantity":
                restore[field] = raw
            else:
                restore[field] = raw or ""
        restore["reason"] = f"Rollback of import {ctx.job.pk}"
        services.update_entitlement(ctx.request, entitlement, restore, entitlement.version)
        return True, "Previous values restored."
