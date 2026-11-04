"""Location, group and static group membership import families."""

import json
import uuid

from rest_framework import serializers

from apps.accounts import catalog
from apps.assets.models import Asset
from apps.groups import services as group_services
from apps.groups.models import AssetGroup, AssetGroupMembership
from apps.organizations import scope
from apps.organizations import services as org_services
from apps.organizations.models import Location, Site

from .base import Column, Context, Family, Plan, RowError, check_formulas, choice, find_user, text


def _detail(exc: serializers.ValidationError) -> str:
    detail = exc.detail
    if isinstance(detail, dict):
        return "; ".join(f"{k}: {' '.join(map(str, v))}" for k, v in detail.items())
    return " ".join(map(str, detail))


# --- Locations --------------------------------------------------------------------------------


class LocationFamily(Family):
    code = "location"
    label = "Locations"
    version = 1
    description = "Create or update buildings, floors, rooms and racks inside sites."
    match_help = "Matches on site code + location name (case-insensitive)."
    permission = catalog.SITES_MANAGE
    columns = (
        Column("site", "Site", "always", "Site code.", "HQ"),
        Column("name", "Name", "always", "Unique within the site.", "Server room"),
        Column("kind", "Kind", "", "building, floor, room, rack or other.", "room"),
        Column("parent", "Inside location", "", "Name of the parent location in the site.", ""),
    )

    def plan(self, ctx: Context, values: dict, row_number: int) -> Plan:
        plan = Plan(action="error")
        try:
            check_formulas(values)
            site_code, name = text(values, "site", 32), text(values, "name", 150)
            if not site_code or not name:
                raise RowError("site and name are required.")
            site = (
                scope.restrict(Site.objects.all(), ctx.user, field="pk")
                .filter(code__iexact=site_code)
                .first()
            )
            if site is None:
                raise RowError(f"Site {site_code!r} not found in your sites.")
            plan.key = f"{site.code}:{name.lower()}"
            first = ctx.remember(plan.key, row_number)
            if first is not None:
                plan.action = "conflict"
                plan.messages.append(f"Same location as row {first}.")
                return plan
            data = {"site": site, "name": name}
            if value := text(values, "kind", 20):
                data["kind"] = choice(value, Location.Kind.choices, "kind")
            if value := text(values, "parent", 150):
                parent = Location.objects.filter(site=site, name__iexact=value).first()
                if parent is None:
                    raise RowError(f"Parent location {value!r} not found in site {site.code}.")
                data["parent"] = parent
            existing = Location.objects.filter(site=site, name__iexact=name).first()
            if existing is None:
                if ctx.mode == "update_matched":
                    plan.action = "skip"
                    plan.messages.append("No matching location (update only).")
                    return plan
                plan.action, plan.data, plan.target_label = "create", data, name
                plan.changes = {k: {"before": None, "after": str(v)} for k, v in data.items()}
                return plan
            plan.target, plan.target_id, plan.target_label = (
                existing,
                str(existing.pk),
                existing.name,
            )
            if ctx.mode == "create_only":
                plan.action = "skip"
                plan.messages.append("Exists already (create only).")
                return plan
            changes = {}
            for key in ("kind", "parent"):
                if key in data and getattr(existing, key) != data[key]:
                    before = getattr(existing, key)
                    changes[key] = {
                        "before": str(before) if before else None,
                        "after": str(data[key]),
                        "before_raw": str(before.pk) if key == "parent" and before else before,
                    }
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
                location = org_services.create_location(ctx.request, plan.data)
            else:
                location = org_services.update_location(
                    ctx.request, plan.target, plan.data, plan.target.version
                )
        except serializers.ValidationError as exc:
            raise RowError(_detail(exc)) from exc
        return str(location.pk), location.name, location.version

    def rollback(self, ctx: Context, row) -> tuple[bool, str]:
        location = Location.objects.filter(pk=row.target_id).first()
        if location is None or location.version != row.version_after:
            return False, "The location changed after the import; correct it by hand."
        if row.action == "create":
            if location.assets.exists():
                return False, "Assets now use this location; deactivate it by hand."
            org_services.update_location(
                ctx.request, location, {"is_active": False}, location.version
            )
            return True, "Deactivated (created by the import)."
        restore = {}
        for key, change in row.changes.items():
            raw = change.get("before_raw")
            restore[key] = Location.objects.get(pk=raw) if key == "parent" and raw else raw
        org_services.update_location(ctx.request, location, restore, location.version)
        return True, "Previous values restored."


# --- Groups -----------------------------------------------------------------------------------


class GroupFamily(Family):
    code = "group"
    label = "Groups"
    version = 1
    description = "Create or update static and dynamic groups (rules are validated)."
    match_help = "Matches on the group name (case-insensitive) among live groups."
    permission = catalog.GROUPS_MANAGE
    columns = (
        Column("name", "Name", "always", "", "Refresh 2027"),
        Column("kind", "Kind", "create", "static or dynamic.", "static"),
        Column("description", "Description", "", "", ""),
        Column("parent", "Inside group", "", "Name of the parent group.", ""),
        Column("owner", "Owner", "", "Username or e-mail.", ""),
        Column("rule", "Rule", "", "Dynamic groups: rule as JSON (see Groups → rule builder).", ""),
    )

    def plan(self, ctx: Context, values: dict, row_number: int) -> Plan:
        plan = Plan(action="error")
        try:
            check_formulas({k: v for k, v in values.items() if k != "rule"})
            name = text(values, "name", 120)
            if not name:
                raise RowError("name is required.")
            plan.key = name.lower()
            first = ctx.remember(plan.key, row_number)
            if first is not None:
                plan.action = "conflict"
                plan.messages.append(f"Same group as row {first}.")
                return plan
            data: dict = {}
            if value := text(values, "kind", 10):
                data["kind"] = choice(value, AssetGroup.Kind.choices, "kind")
            if "description" in values and values["description"]:
                data["description"] = text(values, "description", 500)
            if value := text(values, "parent", 120):
                parent = AssetGroup.objects.filter(
                    name__iexact=value, archived_at__isnull=True
                ).first()
                if parent is None:
                    raise RowError(f"Parent group {value!r} not found.")
                data["parent"] = parent
            if value := text(values, "owner", 254):
                data["owner"] = find_user(ctx, value)
            if raw := (values.get("rule") or "").strip():
                try:
                    rule = json.loads(raw)
                except ValueError as exc:
                    raise RowError("rule: not valid JSON.") from exc
                try:
                    data["rule"] = group_services.clean_rule(rule)
                except serializers.ValidationError as exc:
                    raise RowError(_detail(exc)) from exc
            existing = AssetGroup.objects.filter(
                name__iexact=name, archived_at__isnull=True
            ).first()
            if existing is None:
                if ctx.mode == "update_matched":
                    plan.action = "skip"
                    plan.messages.append("No matching group (update only).")
                    return plan
                if "kind" not in data:
                    raise RowError("kind is required for new groups.")
                if data["kind"] == "dynamic" and "rule" not in data:
                    raise RowError("Dynamic groups need a rule.")
                if data["kind"] == "static" and "rule" in data:
                    raise RowError("Static groups have no rule.")
                plan.action, plan.target_label = "create", name
                plan.data = {"name": name, **data}
                plan.changes = {k: {"before": None, "after": str(v)} for k, v in plan.data.items()}
                return plan
            plan.target, plan.target_id, plan.target_label = (
                existing,
                str(existing.pk),
                existing.name,
            )
            if ctx.mode == "create_only":
                plan.action = "skip"
                plan.messages.append("Exists already (create only).")
                return plan
            if data.get("kind", existing.kind) != existing.kind:
                plan.action = "conflict"
                plan.messages.append("The kind of an existing group cannot change.")
                return plan
            data.pop("kind", None)
            changes = {}
            for key, value in data.items():
                current = getattr(existing, key)
                if current != value:
                    changes[key] = {
                        "before": str(current) if current is not None else None,
                        "after": str(value),
                        "before_raw": (
                            current
                            if key in ("description", "rule")
                            else (str(current.pk) if current is not None else None)
                        ),
                    }
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
        reason = f"Imported from {ctx.job.filename}"
        try:
            if plan.action == "create":
                group = group_services.create_group(ctx.request, {**plan.data, "reason": reason})
            else:
                data = dict(plan.data)
                if "rule" in data:
                    data["reason"] = reason
                group = group_services.update_group(
                    ctx.request, plan.target, data, plan.target.version
                )
        except serializers.ValidationError as exc:
            raise RowError(_detail(exc)) from exc
        group.refresh_from_db()
        return str(group.pk), group.name, group.version

    def rollback(self, ctx: Context, row) -> tuple[bool, str]:
        group = AssetGroup.objects.filter(pk=row.target_id, archived_at__isnull=True).first()
        if group is None or group.version != row.version_after:
            return False, "The group changed after the import; correct it by hand."
        reason = f"Rollback of import {ctx.job.pk}"
        if row.action == "create":
            group_services.archive_group(ctx.request, group, reason, group.version)
            return True, "Archived (created by the import)."
        restore: dict = {}
        for key, change in row.changes.items():
            raw = change.get("before_raw")
            if key == "parent":
                restore[key] = AssetGroup.objects.get(pk=raw) if raw else None
            elif key == "owner":
                from django.contrib.auth import get_user_model

                restore[key] = get_user_model().objects.get(pk=raw) if raw else None
            else:
                restore[key] = raw if raw is not None else ""
        if "rule" in restore:
            restore["reason"] = reason
        group_services.update_group(ctx.request, group, restore, group.version)
        return True, "Previous values restored."


# --- Static group memberships ---------------------------------------------------------------


class MembershipFamily(Family):
    code = "group_membership"
    label = "Static group members"
    version = 1
    description = "Add assets to static groups. Rows never remove members."
    match_help = "Group by name; asset by id or asset tag (never hostname or IP)."
    permission = catalog.GROUPS_MEMBERS
    columns = (
        Column("group", "Group", "always", "Name of a static group.", "Refresh 2027"),
        Column("asset_id", "Asset ID", "match", "Asset UUID, or give asset_tag.", ""),
        Column("asset_tag", "Asset tag", "match", "", "IT-000123"),
        Column("reason", "Reason", "", "Stored with the membership.", "Out of warranty"),
    )

    def plan(self, ctx: Context, values: dict, row_number: int) -> Plan:
        plan = Plan(action="error")
        try:
            check_formulas(values)
            group_name = text(values, "group", 120)
            if not group_name:
                raise RowError("group is required.")
            group = AssetGroup.objects.filter(
                name__iexact=group_name, archived_at__isnull=True
            ).first()
            if group is None:
                raise RowError(f"Group {group_name!r} not found.")
            if group.kind != AssetGroup.Kind.STATIC:
                raise RowError("Members of dynamic groups come from their rule.")
            visible = scope.restrict(Asset.objects.all(), ctx.user, field="site")
            asset = None
            if raw := text(values, "asset_id", 40):
                try:
                    asset = visible.filter(pk=uuid.UUID(raw)).first()
                except ValueError as exc:
                    raise RowError("asset_id: not a valid asset ID.") from exc
            elif raw := text(values, "asset_tag", 64):
                asset = visible.filter(asset_tag=raw.upper()).first()
            else:
                raise RowError("Give asset_id or asset_tag.")
            if asset is None:
                raise RowError("No such asset in your sites.")
            if asset.archived_at is not None:
                raise RowError("The asset is archived.")
            plan.key = f"{group.pk}:{asset.pk}"
            plan.target_id, plan.target_label = plan.key, f"{group.name} ← {asset.name}"
            first = ctx.remember(plan.key, row_number)
            if first is not None:
                plan.action = "skip"
                plan.messages.append(f"Same membership as row {first}.")
                return plan
            if AssetGroupMembership.objects.filter(
                group=group, asset=asset, removed_at__isnull=True
            ).exists():
                plan.action = "skip"
                plan.messages.append("Already a member.")
                return plan
            if ctx.mode == "update_matched":
                plan.action = "skip"
                plan.messages.append("Memberships are only added (create).")
                return plan
            plan.action = "create"
            plan.data = {"group": group, "asset": asset, "reason": text(values, "reason", 500)}
            plan.changes = {"member": {"before": None, "after": asset.name}}
            return plan
        except RowError as exc:
            plan.messages.append(str(exc))
            return plan

    def apply(self, ctx: Context, plan: Plan, values: dict):
        group, asset = plan.data["group"], plan.data["asset"]
        group_services.change_members(
            ctx.request,
            group,
            [asset],
            [],
            plan.data["reason"] or f"Imported from {ctx.job.filename}",
        )
        return plan.key, plan.target_label, None

    def rollback(self, ctx: Context, row) -> tuple[bool, str]:
        group_id, asset_id = row.target_id.split(":")
        membership = (
            AssetGroupMembership.objects.filter(
                group_id=group_id,
                asset_id=asset_id,
                removed_at__isnull=True,
                added_at__gte=ctx.job.committed_at,
            )
            .select_related("group", "asset")
            .first()
        )
        if membership is None:
            return False, "The membership changed after the import."
        group_services.change_members(
            ctx.request,
            membership.group,
            [],
            [membership.asset],
            f"Rollback of import {ctx.job.pk}",
        )
        return True, "Membership removed."
