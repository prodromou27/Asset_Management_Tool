"""Asset group services (Task 012). Every change is audited; memberships keep history."""

from django.db import transaction
from django.db.models import F
from django.utils import timezone
from rest_framework import serializers

from apps.assets.models import Asset
from apps.audit import services as audit
from apps.organizations.services import check_version
from config.api import ApiError

from . import rules
from .models import AssetGroup, AssetGroupMembership, AssetGroupRuleVersion

Membership = AssetGroupMembership
MAX_MEMBER_CHANGE = 500


def _rule_error(exc: rules.RuleError):
    return serializers.ValidationError({"rule": [f"{exc.path}: {exc.message}"]})


def clean_rule(rule) -> dict:
    try:
        return rules.validate(rule)
    except rules.RuleError as exc:
        raise _rule_error(exc) from exc


def check_parent(group: AssetGroup | None, parent: AssetGroup | None) -> None:
    if parent is None:
        return
    if parent.archived_at is not None:
        raise serializers.ValidationError({"parent": ["The parent group is archived."]})
    node, seen = parent, set()
    while node is not None:
        if group is not None and node.pk == group.pk:
            raise serializers.ValidationError({"parent": ["A group cannot be inside itself."]})
        if node.pk in seen:
            break
        seen.add(node.pk)
        node = node.parent


def check_references(group: AssetGroup | None, rule: dict) -> None:
    """member_of targets must exist, be live and not lead back to this group."""
    refs = rules.referenced_groups(rule)
    if not refs:
        return
    found = {str(g.pk): g for g in AssetGroup.objects.filter(pk__in=refs, archived_at__isnull=True)}
    missing = refs - set(found)
    if missing:
        raise serializers.ValidationError(
            {"rule": ["A referenced group does not exist or is archived."]}
        )
    if group is None:
        return
    stack, seen = list(found.values()), set()
    while stack:
        current = stack.pop()
        if current.pk == group.pk:
            raise serializers.ValidationError(
                {"rule": ["This rule would make the group depend on itself (circular reference)."]}
            )
        if current.pk in seen:
            continue
        seen.add(current.pk)
        if current.kind == AssetGroup.Kind.DYNAMIC and current.rule:
            stack.extend(AssetGroup.objects.filter(pk__in=rules.referenced_groups(current.rule)))


def _snapshot(group: AssetGroup) -> dict:
    return {
        "name": group.name,
        "description": group.description,
        "kind": group.kind,
        "parent": group.parent.name if group.parent_id else None,
        "owner": group.owner.username if group.owner_id else None,
        "rule_version": group.rule_version,
    }


def _new_rule_version(group: AssetGroup, rule: dict, request, reason: str) -> None:
    group.rule = rule
    group.rule_version = (group.rule_version or 0) + 1
    AssetGroupRuleVersion.objects.create(
        group=group,
        number=group.rule_version,
        rule=rule,
        reason=reason[:500],
        created_by=getattr(request, "user", None),
    )


def create_group(request, data: dict) -> AssetGroup:
    kind = data["kind"]
    rule = data.get("rule")
    if kind == AssetGroup.Kind.DYNAMIC:
        if rule is None:
            raise serializers.ValidationError({"rule": ["A dynamic group needs a rule."]})
        rule = clean_rule(rule)
        check_references(None, rule)
    elif rule is not None:
        raise serializers.ValidationError({"rule": ["Static groups have no rule."]})
    check_parent(None, data.get("parent"))
    with transaction.atomic():
        group = AssetGroup.objects.create(
            name=data["name"],
            description=data.get("description", ""),
            kind=kind,
            parent=data.get("parent"),
            owner=data.get("owner"),
            created_by=request.user,
        )
        if kind == AssetGroup.Kind.DYNAMIC:
            _new_rule_version(group, rule, request, data.get("reason") or "Created")
            group.save(update_fields=["rule", "rule_version"])
        audit.record(
            action="groups.create",
            actor=request.user,
            request=request,
            object_type="asset_group",
            object_id=group.pk,
            object_label=group.name,
            after={**_snapshot(group), "rule": group.rule},
        )
        if kind == AssetGroup.Kind.DYNAMIC:
            evaluate(group, request=request)
    return group


def update_group(request, group: AssetGroup, data: dict, expected_version) -> AssetGroup:
    with transaction.atomic():
        group = AssetGroup.objects.select_for_update().get(pk=group.pk)
        check_version(group, expected_version)
        if group.archived_at is not None:
            raise ApiError("GROUP_ARCHIVED", "This group is archived.", 409)
        before = _snapshot(group)
        before_rule = group.rule
        for key in ("name", "description", "owner"):
            if key in data:
                setattr(group, key, data[key])
        if "parent" in data:
            check_parent(group, data["parent"])
            group.parent = data["parent"]
        rule_changed = False
        if "rule" in data:
            if group.kind != AssetGroup.Kind.DYNAMIC:
                raise serializers.ValidationError({"rule": ["Static groups have no rule."]})
            rule = clean_rule(data["rule"])
            check_references(group, rule)
            if rule != group.rule:
                if not (data.get("reason") or "").strip():
                    raise serializers.ValidationError(
                        {"reason": ["Explain why the rule changes (at least 5 characters)."]}
                    )
                _new_rule_version(group, rule, request, data["reason"].strip())
                rule_changed = True
        group.version = F("version") + 1
        group.save()
        group.refresh_from_db()
        audit.record(
            action="groups.update",
            actor=request.user,
            request=request,
            object_type="asset_group",
            object_id=group.pk,
            object_label=group.name,
            before={**before, **({"rule": before_rule} if rule_changed else {})},
            after={**_snapshot(group), **({"rule": group.rule} if rule_changed else {})},
            detail=(data.get("reason") or "")[:500],
        )
        if rule_changed:
            evaluate(group, request=request)
    return group


def archive_group(request, group: AssetGroup, reason: str, expected_version) -> AssetGroup:
    with transaction.atomic():
        group = AssetGroup.objects.select_for_update().get(pk=group.pk)
        check_version(group, expected_version)
        if group.archived_at is not None:
            raise ApiError("GROUP_ARCHIVED", "This group is already archived.", 409)
        if group.children.filter(archived_at__isnull=True).exists():
            raise ApiError("GROUP_HAS_CHILDREN", "Move or archive its child groups first.", 409)
        dependants = [
            g.name
            for g in AssetGroup.objects.filter(
                kind=AssetGroup.Kind.DYNAMIC, archived_at__isnull=True
            ).exclude(pk=group.pk)
            if str(group.pk) in rules.referenced_groups(g.rule or {})
        ]
        if dependants:
            raise ApiError(
                "GROUP_REFERENCED",
                f"Rules of other groups use this group: {', '.join(dependants[:5])}.",
                409,
            )
        group.archived_at = timezone.now()
        group.version = F("version") + 1
        group.save()
        group.refresh_from_db()
        audit.record(
            action="groups.archive",
            actor=request.user,
            request=request,
            object_type="asset_group",
            object_id=group.pk,
            object_label=group.name,
            detail=reason,
        )
    return group


# --- Evaluation ---------------------------------------------------------------------------


def evaluate(group: AssetGroup, request=None) -> dict:
    """Bring evaluated memberships in line with the current rule. Returns counts."""
    if group.kind != AssetGroup.Kind.DYNAMIC or not group.rule or group.archived_at:
        return {"added": 0, "removed": 0, "members": 0}
    now = timezone.now()
    with transaction.atomic():
        group = AssetGroup.objects.select_for_update().get(pk=group.pk)
        matching = set(
            Asset.objects.filter(rules.compile_rule(group.rule)).values_list("pk", flat=True)
        )
        active = dict(
            Membership.objects.filter(group=group, removed_at__isnull=True).values_list(
                "asset_id", "pk"
            )
        )
        added = matching - set(active)
        removed = set(active) - matching
        Membership.objects.bulk_create(
            [
                Membership(
                    group=group,
                    asset_id=asset_id,
                    source=Membership.Source.EVALUATED,
                    rule_version=group.rule_version,
                    added_at=now,
                    added_reason=f"Matches rule version {group.rule_version}",
                )
                for asset_id in added
            ],
            batch_size=1000,
        )
        Membership.objects.filter(pk__in=[active[a] for a in removed]).update(
            removed_at=now,
            removed_reason=f"No longer matches rule version {group.rule_version}",
        )
        AssetGroup.objects.filter(pk=group.pk).update(last_evaluated_at=now)
        if added or removed:
            audit.record(
                action="groups.evaluate",
                actor=getattr(request, "user", None),
                actor_label=None if request is not None else "system",
                request=request,
                object_type="asset_group",
                object_id=group.pk,
                object_label=group.name,
                after={
                    "rule_version": group.rule_version,
                    "added": len(added),
                    "removed": len(removed),
                    "members": len(matching),
                },
                source="api" if request is not None else "system",
            )
    return {"added": len(added), "removed": len(removed), "members": len(matching)}


def evaluate_all() -> int:
    """Re-evaluate every live dynamic group, referenced groups first."""
    groups = list(AssetGroup.objects.filter(kind=AssetGroup.Kind.DYNAMIC, archived_at__isnull=True))
    by_id = {str(g.pk): g for g in groups}
    done: set[str] = set()

    def visit(group, trail=()):
        key = str(group.pk)
        if key in done or key in trail:
            return
        for ref in rules.referenced_groups(group.rule or {}):
            if ref in by_id:
                visit(by_id[ref], (*trail, key))
        evaluate(group)
        done.add(key)

    for group in groups:
        visit(group)
    return len(done)


# --- Static membership ----------------------------------------------------------------------


def _check_static(group: AssetGroup) -> None:
    if group.archived_at is not None:
        raise ApiError("GROUP_ARCHIVED", "This group is archived.", 409)
    if group.kind != AssetGroup.Kind.STATIC:
        raise ApiError(
            "GROUP_IS_DYNAMIC", "Members of a dynamic group come from its rule; edit the rule.", 409
        )


def change_members(request, group: AssetGroup, add: list, remove: list, reason: str) -> dict:
    """`add`/`remove`: assets the caller may see (checked by the view)."""
    _check_static(group)
    if len(add) + len(remove) > MAX_MEMBER_CHANGE:
        raise serializers.ValidationError(
            {"assets": [f"Change at most {MAX_MEMBER_CHANGE} members at a time."]}
        )
    if remove and len(reason.strip()) < 5:
        raise serializers.ValidationError({"reason": ["Removals need a reason (5+ characters)."]})
    now = timezone.now()
    with transaction.atomic():
        AssetGroup.objects.select_for_update().get(pk=group.pk)
        current = set(
            Membership.objects.filter(group=group, removed_at__isnull=True).values_list(
                "asset_id", flat=True
            )
        )
        to_add = [a for a in add if a.pk not in current and a.archived_at is None]
        to_remove = [a for a in remove if a.pk in current]
        Membership.objects.bulk_create(
            [
                Membership(
                    group=group,
                    asset=a,
                    source=Membership.Source.EXPLICIT,
                    added_at=now,
                    added_by=request.user,
                    added_reason=reason[:500],
                )
                for a in to_add
            ]
        )
        Membership.objects.filter(
            group=group, removed_at__isnull=True, asset__in=[a.pk for a in to_remove]
        ).update(removed_at=now, removed_by=request.user, removed_reason=reason[:500])
        if to_add or to_remove:
            AssetGroup.objects.filter(pk=group.pk).update(version=F("version") + 1)
            audit.record(
                action="groups.members",
                actor=request.user,
                request=request,
                object_type="asset_group",
                object_id=group.pk,
                object_label=group.name,
                after={
                    "added": [a.name for a in to_add][:100],
                    "removed": [a.name for a in to_remove][:100],
                },
                detail=reason[:500],
            )
    return {"added": len(to_add), "removed": len(to_remove)}


# --- Preview ----------------------------------------------------------------------------------


def preview(rule: dict, visible, group: AssetGroup | None = None, sample: int = 25) -> dict:
    """What a rule would select among the assets the caller can see."""
    matching = visible.filter(rules.compile_rule(rule))
    result = {
        "count": matching.count(),
        "sample": list(matching.order_by("name")[:sample]),
        "would_add": None,
        "would_remove": None,
    }
    if group is not None:
        current = Membership.objects.filter(group=group, removed_at__isnull=True).values("asset_id")
        result["would_add"] = matching.exclude(pk__in=current).count()
        result["would_remove"] = (
            visible.filter(pk__in=current).exclude(pk__in=matching.values("pk")).count()
        )
    return result
