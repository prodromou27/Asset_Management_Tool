"""Store Microsoft 365 license data read by the M365 adapter (Task 010).

Rules (docs/06):
- One allocation per user and SKU, whatever the number of assignment paths: a user with
  the same SKU directly and through one or more groups is counted once.
- Only a complete listing may end allocations, flag users or SKUs missing, or produce
  ITAM's assigned-user counts. Nothing is ever deleted.
- Quantity snapshots are append-only: a new snapshot is written when any reported or
  counted value changes; otherwise the latest one is confirmed.
"""

from collections import Counter

from django.db import transaction
from django.utils import timezone

from .models import (
    DirectoryGroup,
    DirectoryUser,
    LicenseAllocation,
    LicenseSku,
    SubscriptionSnapshot,
)

State = LicenseAllocation.State
# Most favourable state wins when one user holds a SKU through several paths.
STATE_ORDER = (State.ACTIVE, State.ACTIVE_WITH_ERROR, State.ERROR, State.DISABLED)
SNAPSHOT_FIELDS = (
    "capability_status",
    "enabled_units",
    "warning_units",
    "suspended_units",
    "locked_out_units",
    "consumed_units",
    "assigned_users",
    "direct_users",
    "group_users",
)


def _int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _sku_key(value) -> str:
    return str(value or "").strip().lower()


def _summarise(paths: list[dict]) -> str:
    states = {str(p.get("state") or "") for p in paths}
    for state in STATE_ORDER:
        if state in states:
            return state
    return State.UNKNOWN


def user_allocations(user: dict) -> dict[str, dict]:
    """sku_id → {assigned_directly, group_ids, state, paths} for one Graph user."""
    by_sku: dict[str, list[dict]] = {}
    for entry in user.get("licenseAssignmentStates") or []:
        if not isinstance(entry, dict) or not entry.get("skuId"):
            continue
        by_sku.setdefault(_sku_key(entry["skuId"]), []).append(
            {
                "assignedByGroup": entry.get("assignedByGroup"),
                "state": entry.get("state"),
                "error": entry.get("error"),
                "disabledPlans": len(entry.get("disabledPlans") or []),
                "lastUpdatedDateTime": entry.get("lastUpdatedDateTime"),
            }
        )
    # assignedLicenses without a matching state entry: an assignment of unknown path.
    for entry in user.get("assignedLicenses") or []:
        if isinstance(entry, dict) and entry.get("skuId"):
            by_sku.setdefault(_sku_key(entry["skuId"]), [])
    out = {}
    for sku_id, paths in by_sku.items():
        groups = sorted({str(p["assignedByGroup"]) for p in paths if p.get("assignedByGroup")})
        out[sku_id] = {
            "assigned_directly": any(not p.get("assignedByGroup") for p in paths) or not paths,
            "group_ids": groups,
            "state": _summarise(paths),
            "paths": sorted(paths, key=lambda p: str(p.get("assignedByGroup") or "")),
        }
    return out


def _sku_values(row: dict) -> dict:
    prepaid = row.get("prepaidUnits") or {}
    plans = sorted(
        str(p.get("servicePlanName"))
        for p in row.get("servicePlans") or []
        if isinstance(p, dict) and p.get("servicePlanName")
    )
    return {
        "sku_part_number": str(row.get("skuPartNumber") or "")[:120],
        "applies_to": str(row.get("appliesTo") or "")[:20],
        "capability_status": str(row.get("capabilityStatus") or "")[:30],
        "service_plans": plans,
        "snapshot": {
            "capability_status": str(row.get("capabilityStatus") or "")[:30],
            "enabled_units": _int(prepaid.get("enabled")),
            "warning_units": _int(prepaid.get("warning")),
            "suspended_units": _int(prepaid.get("suspended")),
            "locked_out_units": _int(prepaid.get("lockedOut")),
            "consumed_units": _int(row.get("consumedUnits")),
        },
        "original": {k: v for k, v in row.items() if k != "servicePlans"},
    }


def store_license_data(instance, run, records, complete, adapter) -> None:
    now = timezone.now()
    tenant = instance.tenant_id
    with transaction.atomic():
        skus = {s.sku_id: s for s in LicenseSku.objects.filter(instance=instance)}
        sku_values: dict[str, dict] = {}

        # --- Subscribed SKUs -------------------------------------------------------------
        for row in adapter.skus:
            sku_id = _sku_key(row.get("skuId"))
            values = _sku_values(row)
            sku_values[sku_id] = values
            sku = skus.get(sku_id) or LicenseSku(
                instance=instance, sku_id=sku_id, first_seen_at=now
            )
            sku.tenant_id = tenant
            sku.sku_part_number = values["sku_part_number"]
            sku.applies_to = values["applies_to"]
            sku.capability_status = values["capability_status"]
            sku.service_plans = values["service_plans"]
            sku.subscribed = True
            sku.last_seen_at = now
            sku.missing_since = None
            sku.save()
            skus[sku_id] = sku
        if adapter.skus_complete:
            LicenseSku.objects.filter(
                instance=instance, subscribed=True, missing_since=None
            ).exclude(sku_id__in=sku_values).update(missing_since=now)

        # --- Users and allocations -------------------------------------------------------
        users = {u.object_id: u for u in DirectoryUser.objects.filter(instance=instance)}
        active = {
            (a.sku.sku_id, a.user.object_id): a
            for a in LicenseAllocation.objects.filter(
                instance=instance, ended_at__isnull=True
            ).select_related("sku", "user")
        }
        current: set[tuple[str, str]] = set()
        listed_users: set[str] = set()
        for row in adapter.users:
            object_id = str(row.get("id") or "").strip().lower()
            listed_users.add(object_id)
            assignments = user_allocations(row)
            known = users.get(object_id)
            if not assignments and known is None:
                continue  # never licensed: not stored (data minimisation)
            user = known or DirectoryUser(instance=instance, object_id=object_id, first_seen_at=now)
            user.tenant_id = tenant
            user.user_principal_name = str(row.get("userPrincipalName") or "")[:320]
            user.display_name = str(row.get("displayName") or "")[:256]
            enabled = row.get("accountEnabled")
            user.account_enabled = enabled if isinstance(enabled, bool) else None
            user.last_seen_at = now
            user.missing_since = None
            user.save()
            users[object_id] = user
            for sku_id, data in assignments.items():
                sku = skus.get(sku_id)
                if sku is None:  # assigned but not (or no longer) subscribed
                    sku = LicenseSku.objects.create(
                        instance=instance,
                        tenant_id=tenant,
                        sku_id=sku_id,
                        subscribed=False,
                        first_seen_at=now,
                        last_seen_at=now,
                    )
                    skus[sku_id] = sku
                key = (sku_id, object_id)
                current.add(key)
                allocation = active.get(key)
                if allocation is None:
                    LicenseAllocation.objects.create(
                        instance=instance,
                        sku=sku,
                        user=user,
                        first_seen_at=now,
                        last_seen_at=now,
                        changed_at=now,
                        **data,
                    )
                    continue
                if any(getattr(allocation, k) != v for k, v in data.items()):
                    allocation.changed_at = now
                for k, v in data.items():
                    setattr(allocation, k, v)
                allocation.last_seen_at = now
                allocation.save()

        if adapter.users_complete:
            ended = [a.pk for key, a in active.items() if key not in current]
            LicenseAllocation.objects.filter(pk__in=ended).update(ended_at=now)
            DirectoryUser.objects.filter(instance=instance, missing_since=None).exclude(
                object_id__in=listed_users
            ).update(missing_since=now)

        # --- Group names (optional permission) -----------------------------------------
        for object_id, name in getattr(adapter, "groups", {}).items():
            DirectoryGroup.objects.update_or_create(
                instance=instance,
                object_id=object_id,
                defaults={"display_name": name, "last_seen_at": now},
            )

        # --- Snapshots -------------------------------------------------------------------
        counts: dict[str, Counter] = {}
        if adapter.users_complete:
            for sku_id, direct, groups in LicenseAllocation.objects.filter(
                instance=instance, ended_at__isnull=True, state__in=LicenseAllocation.COUNTED
            ).values_list("sku__sku_id", "assigned_directly", "group_ids"):
                c = counts.setdefault(sku_id, Counter())
                c["assigned_users"] += 1
                c["direct_users"] += 1 if direct else 0
                c["group_users"] += 1 if groups else 0
        for sku_id, values in sku_values.items():
            snapshot = dict(values["snapshot"])
            if adapter.users_complete:
                c = counts.get(sku_id, Counter())
                snapshot.update(
                    assigned_users=c["assigned_users"],
                    direct_users=c["direct_users"],
                    group_users=c["group_users"],
                )
            else:
                snapshot.update(assigned_users=None, direct_users=None, group_users=None)
            sku = skus[sku_id]
            latest = sku.snapshots.order_by("-taken_at").first()
            if latest is not None and all(
                getattr(latest, k) == snapshot[k] for k in SNAPSHOT_FIELDS
            ):
                latest.last_confirmed_at = now
                latest.run = run
                latest.save(update_fields=["last_confirmed_at", "run"])
                continue
            SubscriptionSnapshot.objects.create(
                sku=sku,
                run=run,
                taken_at=now,
                last_confirmed_at=now,
                original=values["original"],
                **snapshot,
            )
    run.evidence_rows = len(current)
