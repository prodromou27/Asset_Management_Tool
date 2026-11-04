"""Software inventory storage, manual entries and per-version lifecycle (ASM-54)."""

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.audit import services as audit
from apps.lifecycle import assessment, matching
from apps.lifecycle.matching import key
from apps.lifecycle.models import AssetLifecycleMatch, LifecycleProduct
from apps.lifecycle.services import Policy
from config.api import ApiError

from .models import SoftwareInstallation, SoftwareProduct, SoftwareVersion

BATCH = 1000


class Catalogue:
    """Get-or-create products and versions by normalised keys, cached for one sync."""

    def __init__(self):
        self.products: dict[tuple[str, str], SoftwareProduct] = {}
        self.versions: dict[tuple[int, str], SoftwareVersion] = {}
        self.created_versions: list[int] = []

    def version(self, publisher: str, name: str, version: str) -> SoftwareVersion:
        pkey = (key(publisher)[:200], key(name)[:300])
        product = self.products.get(pkey)
        if product is None:
            product, _ = SoftwareProduct.objects.get_or_create(
                publisher_key=pkey[0],
                name_key=pkey[1],
                defaults={"publisher": publisher.strip()[:200], "name": name.strip()[:300]},
            )
            self.products[pkey] = product
        vkey = (product.pk, key(version)[:100])
        found = self.versions.get(vkey)
        if found is None:
            found, created = SoftwareVersion.objects.get_or_create(
                product=product, version_key=vkey[1], defaults={"version": version.strip()[:100]}
            )
            if created:
                self.created_versions.append(found.pk)
            self.versions[vkey] = found
        return found


def clean_item(item: dict) -> dict | None:
    name = str(item.get("name") or "").strip()
    if not name:
        return None
    return {
        "name": name[:300],
        "publisher": str(item.get("publisher") or "").strip()[:200],
        "version": str(item.get("version") or "").strip()[:100],
        "source_ref": str(item.get("source_ref") or "").strip()[:200],
        "installed_on": item.get("installed_on"),
    }


def store_installations(
    instance, software: dict[str, list[dict]], complete: set[str], now=None
) -> dict:
    """Upsert the software reported per source device.

    ``software`` maps external device IDs to reported items; ``complete`` lists the
    devices whose list was read completely in this sync - only for those are rows that are
    no longer reported marked removed. Devices not in ``software`` are left untouched.
    """
    now = now or timezone.now()
    cat = Catalogue()
    counts = {"added": 0, "seen": 0, "removed": 0, "restored": 0}
    devices = list(software)
    for start in range(0, len(devices), BATCH):
        batch = devices[start : start + BATCH]
        with transaction.atomic():
            existing: dict[tuple[str, int], SoftwareInstallation] = {
                (row.external_id, row.version_id): row
                for row in SoftwareInstallation.objects.select_for_update().filter(
                    instance=instance, external_id__in=batch
                )
            }
            new_rows, seen_ids, restored = [], [], []
            for external_id in batch:
                reported: set[int] = set()
                for raw in software[external_id]:
                    item = clean_item(raw)
                    if item is None:
                        continue
                    version = cat.version(item["publisher"], item["name"], item["version"])
                    if version.pk in reported:
                        continue  # same product version reported twice for one device
                    reported.add(version.pk)
                    row = existing.get((external_id, version.pk))
                    if row is None:
                        new_rows.append(
                            SoftwareInstallation(
                                version=version,
                                instance=instance,
                                external_id=external_id,
                                raw_publisher=item["publisher"],
                                raw_name=item["name"],
                                raw_version=item["version"],
                                source_ref=item["source_ref"],
                                installed_on=item["installed_on"],
                                first_seen_at=now,
                                last_seen_at=now,
                            )
                        )
                    elif row.removed_at is not None:
                        restored.append(row.pk)
                    else:
                        seen_ids.append(row.pk)
                if external_id in complete:
                    gone = [
                        row.pk
                        for (ext, version_id), row in existing.items()
                        if ext == external_id
                        and row.removed_at is None
                        and version_id not in reported
                    ]
                    if gone:
                        counts["removed"] += SoftwareInstallation.objects.filter(
                            pk__in=gone
                        ).update(removed_at=now, removed_reason="No longer reported by the source")
            SoftwareInstallation.objects.bulk_create(new_rows, batch_size=BATCH)
            SoftwareInstallation.objects.filter(pk__in=seen_ids).update(last_seen_at=now)
            SoftwareInstallation.objects.filter(pk__in=restored).update(
                last_seen_at=now, removed_at=None, removed_reason=""
            )
            counts["added"] += len(new_rows)
            counts["seen"] += len(seen_ids)
            counts["restored"] += len(restored)
    if cat.created_versions:
        reassess_versions(cat.created_versions)
    return counts


def store_software(instance, run, records, complete, adapter=None) -> None:
    """Connector ``store_facts`` hook: only when the adapter collected software."""
    software = getattr(adapter, "software", None)
    if software is None:
        return
    counts = store_installations(instance, software, getattr(adapter, "software_complete", set()))
    run.checkpoint = (
        f"software: {counts['added']} new, {counts['seen'] + counts['restored']} seen, "
        f"{counts['removed']} removed"
    )[:200]


# --- Manual entries ------------------------------------------------------------------------


def add_manual(request, asset, data: dict) -> SoftwareInstallation:
    item = clean_item(data)
    if item is None:
        raise ApiError("VALIDATION_ERROR", "Enter the software name.", 422, {"name": ["Required."]})
    now = timezone.now()
    cat = Catalogue()
    with transaction.atomic():
        version = cat.version(item["publisher"], item["name"], item["version"])
        if SoftwareInstallation.objects.filter(
            asset=asset, version=version, instance__isnull=True, removed_at__isnull=True
        ).exists():
            raise ApiError(
                "SOFTWARE_EXISTS", "This software version is already recorded on the asset.", 409
            )
        row = SoftwareInstallation.objects.create(
            version=version,
            asset=asset,
            raw_publisher=item["publisher"],
            raw_name=item["name"],
            raw_version=item["version"],
            installed_on=data.get("installed_on"),
            first_seen_at=now,
            last_seen_at=now,
            created_by=request.user,
            note=data.get("note", "")[:500],
        )
        audit.record(
            action="software.manual.add",
            actor=request.user,
            request=request,
            object_type="asset",
            object_id=asset.pk,
            object_label=asset.name,
            after={"software": str(version), "note": row.note},
        )
    if cat.created_versions:
        reassess_versions(cat.created_versions)
    return row


def remove_manual(request, row: SoftwareInstallation, reason: str) -> SoftwareInstallation:
    if row.instance_id is not None:
        raise ApiError(
            "SOFTWARE_DISCOVERED",
            "Discovered software is removed only when its source stops reporting it.",
            409,
        )
    if row.removed_at is not None:
        raise ApiError("SOFTWARE_REMOVED", "This entry is already removed.", 409)
    with transaction.atomic():
        row.removed_at, row.removed_reason = timezone.now(), reason[:300]
        row.save(update_fields=["removed_at", "removed_reason"])
        audit.record(
            action="software.manual.remove",
            actor=request.user,
            request=request,
            object_type="asset",
            object_id=row.asset_id,
            object_label=row.asset.name,
            after={"software": str(row.version)},
            detail=reason,
        )
    return row


# --- Per-version lifecycle ------------------------------------------------------------------

State = AssetLifecycleMatch.State
Method = AssetLifecycleMatch.Method


def reassess_versions(version_ids=None, policy: Policy | None = None) -> int:
    """Match versions to catalogue software products and assess them. Reviewer approvals
    stand; rejected products are not proposed again."""
    policy = policy or Policy()
    qs = SoftwareVersion.objects.select_related("product")
    if version_ids is not None:
        qs = qs.filter(pk__in=list(version_ids))
    changed = 0
    now = timezone.now()
    for v in qs.iterator(chunk_size=BATCH):
        if not (v.lifecycle_method == Method.MANUAL and v.lifecycle_product_id):
            result = matching.match_software(
                policy.catalogue,
                v.product.publisher,
                v.product.name,
                v.version,
                set(v.lifecycle_rejected),
            )
            v.lifecycle_state = result.state
            v.lifecycle_method = result.method
            v.lifecycle_product_id = result.product_id
            v.lifecycle_candidates = result.candidates
            reason = result.reason
        else:
            reason = "Approved by a reviewer."
        before = (v.lifecycle_status, v.lifecycle_milestone_date)
        _assess(v, policy, reason)
        v.lifecycle_assessed_at = now
        v.save()
        changed += before != (v.lifecycle_status, v.lifecycle_milestone_date)
    return changed


def _assess(v: SoftwareVersion, policy: Policy, reason: str) -> None:
    product = policy.product(v.lifecycle_product_id) if v.lifecycle_product_id else None
    if v.lifecycle_state == State.CANDIDATE:
        outcome = assessment.Outcome("unverified", reasons=[reason])
    elif product is None or not product.is_active:
        outcome = assessment.Outcome("unknown", reasons=[reason])
    else:
        outcome = assessment.evaluate(
            assessment.claims_for(product),
            policy.today,
            policy.thresholds,
            policy.count_extended,
            product.support_statement,
            product.statement_verified_at is not None and product.statement_source_id is not None,
        )
        outcome.reasons.insert(0, f"{Method(v.lifecycle_method).label}: {product}.")
    v.lifecycle_status = outcome.status
    v.lifecycle_milestone_type = outcome.milestone_type
    v.lifecycle_milestone_date = outcome.milestone_date
    v.lifecycle_days_remaining = outcome.days_remaining
    v.lifecycle_evidence_quality = outcome.evidence_quality
    v.lifecycle_reasons = outcome.reasons


def reassess_all() -> int:
    """Versions currently installed somewhere, plus any with a catalogue link."""
    ids = (
        SoftwareVersion.objects.filter(
            Q(installations__removed_at__isnull=True) | Q(lifecycle_product__isnull=False)
        )
        .values_list("pk", flat=True)
        .distinct()
    )
    return reassess_versions(ids)


def _check(v: SoftwareVersion, expected) -> None:
    from apps.organizations.services import check_version

    class _Lock:
        version = v.lifecycle_version

    check_version(_Lock, expected)


def approve_version(
    request, v: SoftwareVersion, product: LifecycleProduct, remember: bool, note: str, expected
) -> SoftwareVersion:
    from apps.lifecycle.services import add_alias

    if product.kind != LifecycleProduct.Kind.SOFTWARE:
        raise ApiError(
            "VALIDATION_ERROR",
            "Choose a software product from the lifecycle catalogue.",
            422,
            {"product": ["Not a software product."]},
        )
    with transaction.atomic():
        v = SoftwareVersion.objects.select_for_update().select_related("product").get(pk=v.pk)
        _check(v, expected)
        v.lifecycle_state, v.lifecycle_method = State.MATCHED, Method.MANUAL
        v.lifecycle_product = product
        v.lifecycle_candidates = []
        v.lifecycle_rejected = [p for p in v.lifecycle_rejected if p != str(product.pk)]
        v.lifecycle_reviewed_by, v.lifecycle_reviewed_at = request.user, timezone.now()
        v.lifecycle_version += 1
        v.save()
        audit.record(
            action="software.lifecycle.approve",
            actor=request.user,
            request=request,
            object_type="software_version",
            object_id=v.pk,
            object_label=str(v)[:255],
            after={"product": str(product), "remember_alias": remember},
            detail=note,
        )
        if remember and (key(v.product.name), key(v.version)) != (
            product.name_key,
            product.release_key,
        ):
            add_alias(
                request,
                product,
                {
                    "kind": "product_name",
                    "value": v.product.name,
                    "release": v.version,
                    "note": "From an approved software match",
                },
            )
    reassess_versions([v.pk])
    v.refresh_from_db()
    return v


def reject_version(request, v: SoftwareVersion, note: str, expected) -> SoftwareVersion:
    with transaction.atomic():
        v = SoftwareVersion.objects.select_for_update().get(pk=v.pk)
        _check(v, expected)
        targets = [c["product_id"] for c in v.lifecycle_candidates] or (
            [str(v.lifecycle_product_id)] if v.lifecycle_product_id else []
        )
        if not targets:
            raise ApiError(
                "LIFECYCLE_NOTHING_TO_REJECT", "There is no suggested product to reject.", 409
            )
        v.lifecycle_rejected = sorted(set(v.lifecycle_rejected) | set(targets))
        if v.lifecycle_method == Method.MANUAL:
            v.lifecycle_method, v.lifecycle_product = Method.NONE, None
        v.lifecycle_reviewed_by, v.lifecycle_reviewed_at = request.user, timezone.now()
        v.lifecycle_version += 1
        v.save()
        audit.record(
            action="software.lifecycle.reject",
            actor=request.user,
            request=request,
            object_type="software_version",
            object_id=v.pk,
            object_label=str(v)[:255],
            after={"rejected": targets},
            detail=note,
        )
    reassess_versions([v.pk])
    v.refresh_from_db()
    return v
