"""Asset import family (docs/11: match on id or approved asset tag; serial+manufacturer and
name+site are review-only, never hostname or IP).

Blank cells leave values unchanged. Category changes are refused (reclassification has its
own reviewed workflow). Locked (manually approved) technical fields are never overwritten:
a differing value is a conflict. Discovery-sourced technical values need technical edit
rights, exactly as in the API. Missing rows never archive assets.
"""

import re
import uuid

from django.db.models import Q
from rest_framework import serializers

from apps.accounts import catalog
from apps.assets import custom_fields as cf
from apps.assets import services as asset_services
from apps.assets.models import (
    TECHNICAL_FIELDS,
    Asset,
    AssetCategory,
    FieldLock,
    FieldProvenance,
)
from apps.assets.serializers import ASSET_TAG_PATTERN
from apps.assets.tree import CategoryTree
from apps.observations.normalize import normalize_manufacturer, normalize_serial
from apps.organizations import scope
from apps.organizations.models import Department, Location, Site

from .base import Column, Context, Family, Plan, RowError, check_formulas, choice, find_user, text

TEXT_FIELDS = {
    "manufacturer": 150,
    "model": 150,
    "serial_number": 150,
    "os_name": 150,
    "os_version": 100,
    "firmware_version": 100,
    "notes": 10000,
}
REF_FIELDS = ("site", "location", "department", "owner")


def _flatten(errors) -> str:
    if isinstance(errors, dict):
        return "; ".join(f"{k}: {_flatten(v)}" for k, v in errors.items())
    if isinstance(errors, list):
        return " ".join(_flatten(e) for e in errors)
    return str(errors)


class AssetFamily(Family):
    code = "asset"
    label = "Assets"
    version = 1
    description = "Create or update assets. Blank cells leave existing values unchanged."
    match_help = (
        "Updates match on id or asset_tag only. A matching manufacturer + serial or name + site "
        "without id/tag is reported as a conflict for review, never merged. Hostname and IP are "
        "never used for matching."
    )
    permission = catalog.ASSETS_VIEW
    allow_custom_columns = True
    columns = (
        Column("id", "Asset ID", "match", "Existing asset UUID (from an export).", ""),
        Column(
            "asset_tag",
            "Asset tag",
            "match",
            "Unique tag; matches existing assets.",
            "IT-000123",
            ("tag", "asset tag"),
        ),
        Column("name", "Name", "create", "Required for new assets.", "LT-0042"),
        Column(
            "category",
            "Category",
            "create",
            "Code, path (Workstations / Laptop) or name.",
            "workstations-laptop",
        ),
        Column("site", "Site", "create", "Site code.", "HQ"),
        Column("location", "Location", "", "Location name in the site.", "Server room"),
        Column("department", "Department", "", "Department code or name.", "FIN"),
        Column("owner", "Owner", "", "Username or e-mail of an active user.", "j.smith"),
        Column("manufacturer", "Manufacturer", "", "", "Dell"),
        Column("model", "Model", "", "", "Latitude 7440"),
        Column("serial_number", "Serial number", "", "", "7XK2Q93", ("serial",)),
        Column("os_name", "Operating system", "", "", "Windows 11"),
        Column("os_version", "OS version", "", "", "23H2"),
        Column("firmware_version", "Firmware", "", "", ""),
        Column(
            "business_status",
            "Business status",
            "",
            "ordered, in_stock, deployed, assigned, in_repair, retired, disposed, lost.",
            "deployed",
            ("status",),
        ),
        Column("notes", "Notes", "", "", ""),
    )

    # --- Lookups ----------------------------------------------------------------------------

    def _category(self, ctx: Context, value: str) -> AssetCategory:
        def load():
            tree = CategoryTree()
            index: dict[str, list] = {}
            for cat in tree.by_id.values():
                for key in {cat.code.lower(), tree.path(cat.pk).lower(), cat.name.lower()}:
                    index.setdefault(key, []).append(cat)
            return index

        found = ctx.lookup("categories", load).get(value.lower(), [])
        if len({c.pk for c in found}) != 1:
            raise RowError(
                f"Category {value!r} {'is ambiguous; use its code' if found else 'not found'}."
            )
        category = found[0]
        if not category.is_active:
            raise RowError(f"Category {category.name!r} is inactive.")
        return category

    def _site(self, ctx: Context, value: str) -> Site:
        sites = ctx.lookup(
            "sites",
            lambda: {
                s.code.lower(): s for s in scope.restrict(Site.objects.all(), ctx.user, field="pk")
            },
        )
        site = sites.get(value.lower())
        if site is None:
            raise RowError(f"Site {value!r} not found in your sites.")  # never confirms others
        if not site.is_active:
            raise RowError(f"Site {value!r} is inactive.")
        return site

    def _location(self, ctx: Context, site: Site, value: str) -> Location:
        location = Location.objects.filter(site=site, name__iexact=value, is_active=True).first()
        if location is None:
            raise RowError(f"Location {value!r} not found in site {site.code}.")
        return location

    def _department(self, ctx: Context, value: str) -> Department:
        department = (
            Department.objects.filter(is_active=True)
            .filter(Q(code__iexact=value) | Q(name__iexact=value))
            .first()
        )
        if department is None:
            raise RowError(f"Department {value!r} not found.")
        return department

    # --- Matching -----------------------------------------------------------------------------

    def _visible(self, ctx: Context):
        return scope.restrict(Asset.objects.all(), ctx.user, field="site")

    def _match(self, ctx: Context, values: dict, row_number: int, plan: Plan):
        raw_id, raw_tag = text(values, "id", 40), text(values, "asset_tag", 64).upper()
        if raw_id:
            try:
                asset_id = uuid.UUID(raw_id)
            except ValueError as exc:
                raise RowError("id: not a valid asset ID.") from exc
            asset = self._visible(ctx).filter(pk=asset_id).first()
            if asset is None:
                raise RowError("id: no asset with this ID in your sites.")
            if raw_tag and (asset.asset_tag or "") != raw_tag:
                raise RowError("id and asset_tag point to different assets.")
            return asset, f"id:{asset.pk}"
        if raw_tag:
            if not re.match(ASSET_TAG_PATTERN, raw_tag):
                raise RowError("asset_tag: use up to 64 letters, digits or . _ / -.")
            asset = Asset.objects.filter(asset_tag=raw_tag).first()
            if asset is not None and not self._visible(ctx).filter(pk=asset.pk).exists():
                raise RowError("asset_tag: already in use by an asset you cannot see.")
            return asset, f"tag:{raw_tag}"
        return None, ""

    def _review_only(self, ctx: Context, values: dict, row_number: int, plan: Plan) -> bool:
        """Serial+manufacturer or name+site matches without id/tag: conflict, never merge."""
        serial = normalize_serial(values.get("serial_number"))
        maker = normalize_manufacturer(values.get("manufacturer"))
        if serial and maker:
            first = ctx.remember(f"serial:{maker}:{serial}", row_number)
            if first is not None:
                plan.messages.append(f"Same manufacturer and serial as row {first}.")
                return True
            for asset in self._visible(ctx).filter(
                serial_number__iexact=serial, archived_at__isnull=True
            ):
                if normalize_manufacturer(asset.manufacturer) == maker:
                    plan.messages.append(
                        f"Manufacturer and serial match {asset.name!r}; add its id or asset_tag "
                        "to update it, or leave the row out."
                    )
                    plan.target_id, plan.target_label = str(asset.pk), asset.name
                    return True
        name, site_code = text(values, "name"), text(values, "site", 32)
        if name and site_code:
            first = ctx.remember(f"name:{site_code.lower()}:{name.lower()}", row_number)
            if first is not None:
                plan.messages.append(f"Same name and site as row {first}.")
                return True
            existing = (
                self._visible(ctx)
                .filter(name__iexact=name, site__code__iexact=site_code, archived_at__isnull=True)
                .first()
            )
            if existing is not None:
                plan.messages.append(
                    f"An asset named {existing.name!r} already exists in site {site_code}; add its "
                    "id or asset_tag to update it."
                )
                plan.target_id, plan.target_label = str(existing.pk), existing.name
                return True
        return False

    # --- Planning -----------------------------------------------------------------------------

    def _custom(self, values: dict) -> dict:
        return {k[3:]: v for k, v in values.items() if k.startswith("cf.") and v != ""}

    def plan(self, ctx: Context, values: dict, row_number: int) -> Plan:
        plan = Plan(action="error")
        try:
            check_formulas(values)
            asset, key = self._match(ctx, values, row_number, plan)
            if key:
                first = ctx.remember(key, row_number)
                if first is not None:
                    plan.action, plan.key = "conflict", key
                    plan.messages.append(f"The same asset is already in row {first}.")
                    return plan
                plan.key = key
            if asset is not None:
                plan.target, plan.target_id, plan.target_label = asset, str(asset.pk), asset.name
                if ctx.mode == "create_only":
                    plan.action = "skip"
                    plan.messages.append("Exists already (create only).")
                    return plan
                return self._plan_update(ctx, values, asset, plan)
            if text(values, "id", 40):
                raise RowError("id: no asset with this ID in your sites.")
            if self._review_only(ctx, values, row_number, plan):
                plan.action = "conflict"
                return plan
            if ctx.mode == "update_matched":
                plan.action = "skip"
                plan.messages.append("No matching asset (update only).")
                return plan
            return self._plan_create(ctx, values, plan)
        except RowError as exc:
            plan.action = "error"
            plan.messages.append(str(exc))
            return plan

    def _common(self, ctx: Context, values: dict, site: Site | None) -> dict:
        data: dict = {}
        for name, limit in TEXT_FIELDS.items():
            value = text(values, name, limit)
            if value:
                data[name] = value
        if value := text(values, "name"):
            data["name"] = value
        if value := text(values, "asset_tag", 64):
            data["asset_tag"] = value.upper()
        if value := text(values, "business_status", 30):
            data["business_status"] = choice(value, Asset.BusinessStatus.choices, "business_status")
        if value := text(values, "location", 150):
            if site is None:
                raise RowError("location: give the site as well.")
            data["location"] = self._location(ctx, site, value)
        if value := text(values, "department", 150):
            data["department"] = self._department(ctx, value)
        if value := text(values, "owner", 254):
            data["owner"] = find_user(ctx, value)
        return data

    def _plan_create(self, ctx: Context, values: dict, plan: Plan) -> Plan:
        if catalog.ASSETS_CREATE not in ctx.permissions:
            raise RowError("You cannot create assets.")
        missing = [c for c in ("name", "category", "site") if not text(values, c)]
        if missing:
            raise RowError(f"New assets need {', '.join(missing)}.")
        site = self._site(ctx, text(values, "site", 32))
        category = self._category(ctx, text(values, "category"))
        data = {"site": site, "category": category, **self._common(ctx, values, site)}
        definitions = cf.applicable_definitions(category.pk, CategoryTree())
        try:
            data["custom_fields"] = cf.validate_values(
                definitions, self._custom(values), {}, enforce_required=True
            )
        except serializers.ValidationError as exc:
            raise RowError(_flatten(exc.detail)) from exc
        plan.action, plan.data = "create", data
        plan.target_label = data["name"]
        plan.changes = {k: {"before": None, "after": _show(v)} for k, v in data.items() if v}
        return plan

    def _plan_update(self, ctx: Context, values: dict, asset: Asset, plan: Plan) -> Plan:
        if asset.archived_at is not None:
            raise RowError("The asset is archived; restore it first.")
        if catalog.ASSETS_EDIT not in ctx.permissions and catalog.ASSETS_EDIT_TECHNICAL not in (
            ctx.permissions
        ):
            raise RowError("You cannot edit assets.")
        site = asset.site
        if value := text(values, "site", 32):
            site = self._site(ctx, value)
        if value := text(values, "category"):
            category = self._category(ctx, value)
            if category.pk != asset.category_id:
                plan.action = "conflict"
                plan.messages.append(
                    "Category differs; change categories with Change category on the asset "
                    "(template impact and reason)."
                )
                return plan
        data = self._common(ctx, values, site)
        if site.pk != asset.site_id:
            data["site"] = site
        if "asset_tag" in data and data["asset_tag"] == (asset.asset_tag or ""):
            data.pop("asset_tag")
        changes = {}
        for name, value in list(data.items()):
            current = getattr(asset, name)
            if current == value:
                data.pop(name)
                continue
            changes[name] = {"before": _show(current), "after": _show(value)}
            if name in REF_FIELDS:
                changes[name]["before_raw"] = str(current.pk) if current is not None else None
        custom = self._custom(values)
        if custom:
            definitions = cf.applicable_definitions(asset.category_id, CategoryTree())
            try:
                merged = cf.validate_values(
                    definitions, custom, asset.custom_fields, enforce_required=False
                )
            except serializers.ValidationError as exc:
                raise RowError(_flatten(exc.detail)) from exc
            if merged != asset.custom_fields:
                data["custom_fields"] = merged
                for key in custom:
                    if asset.custom_fields.get(key) != merged.get(key):
                        changes[f"cf.{key}"] = {
                            "before": asset.custom_fields.get(key),
                            "after": merged.get(key),
                        }
        locked = set(FieldLock.objects.filter(asset=asset).values_list("field", flat=True))
        clashes = [f for f in changes if f in locked]
        if clashes:
            plan.action = "conflict"
            plan.messages.append(
                f"Locked (manually approved) fields would change: {', '.join(sorted(clashes))}. "
                "Unlock them on the asset first."
            )
            plan.changes = changes
            return plan
        technical = [f for f in changes if f in TECHNICAL_FIELDS]
        if technical and catalog.ASSETS_EDIT_TECHNICAL not in ctx.permissions:
            discovered = FieldProvenance.objects.filter(
                asset=asset, field__in=technical, kind=FieldProvenance.Kind.DISCOVERY
            ).exists()
            if discovered:
                raise RowError("Discovered technical values need technical edit rights.")
        business = [f for f in changes if f not in TECHNICAL_FIELDS]
        if business and catalog.ASSETS_EDIT not in ctx.permissions:
            raise RowError("You cannot edit business fields.")
        if not changes:
            plan.action = "skip"
            plan.messages.append("Unchanged.")
            return plan
        plan.action, plan.data, plan.changes = "update", data, changes
        return plan

    # --- Apply and rollback -------------------------------------------------------------------

    def apply(self, ctx: Context, plan: Plan, values: dict) -> tuple[str, str, int | None]:
        if plan.action == "create":
            asset = asset_services.create_asset(ctx.request, plan.data)
        else:
            asset = asset_services.update_asset(
                ctx.request, plan.target, plan.data, plan.target.version
            )
        return str(asset.pk), asset.name, asset.version

    def rollback(self, ctx: Context, row) -> tuple[bool, str]:
        asset = Asset.objects.filter(pk=row.target_id).first()
        if asset is None or asset.version != row.version_after:
            return False, "The asset changed after the import; correct it by hand."
        reason = f"Rollback of import {ctx.job.pk}"
        if row.action == "create":
            asset_services.archive(ctx.request, asset, reason, asset.version)
            return True, "Archived (created by the import)."
        restore = {}
        custom = dict(asset.custom_fields)
        for name, change in row.changes.items():
            before = change.get("before_raw", change.get("before"))
            if name.startswith("cf."):
                if before is None:
                    custom.pop(name[3:], None)
                else:
                    custom[name[3:]] = before
            elif name in REF_FIELDS:
                model = {"site": Site, "location": Location, "department": Department}.get(name)
                if name == "owner":
                    from django.contrib.auth import get_user_model

                    model = get_user_model()
                restore[name] = model.objects.get(pk=before) if before else None
            else:
                restore[name] = before if before is not None else ""
        if custom != asset.custom_fields:
            restore["custom_fields"] = custom
        asset_services.update_asset(ctx.request, asset, restore, asset.version)
        return True, "Previous values restored."


def _show(value):
    """Readable value for previews; FK objects become their name/code (pk kept for rollback)."""
    if value is None or isinstance(value, str | int | float | bool | dict | list):
        return value
    for attr in ("code", "username", "name"):
        if getattr(value, attr, ""):
            return str(getattr(value, attr))
    return str(value)
