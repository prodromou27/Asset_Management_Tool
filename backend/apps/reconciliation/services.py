"""Discovery ingestion, reconciliation decisions, merges, locks and freshness.

Integrity rules (docs/00, docs/03, docs/05):
- Ingestion is idempotent: an unchanged report adds no observation, link,
  candidate or asset; it only refreshes last-seen.
- Discovery never creates or deletes an asset by itself. New devices become
  candidates; a person approves creation. Missing devices become stale.
- Links are unique per (instance, external ID).
- Every decision, merge, unlink, lock and conflict resolution is audited and
  written to asset history; merges are reversible.
"""

from datetime import datetime, timedelta
from types import SimpleNamespace

from django.db import transaction
from django.db.models import F
from django.utils import timezone
from rest_framework import serializers, status

from apps.assets import services as asset_services
from apps.assets.models import (
    TECHNICAL_FIELDS,
    Asset,
    AssetHistoryEntry,
    AssetHostname,
    AssetInterface,
    AssetIPAddress,
    FieldLock,
    FieldProvenance,
    Source,
)
from apps.audit import services as audit
from apps.integrations.models import DiscoverySource, IntegrationInstance, SyncRun
from apps.observations.models import Observation
from apps.observations.normalize import NORMALIZER_VERSION, RecordError, checksum, normalize_record
from apps.organizations.services import check_version
from config.api import ApiError

from . import authority, matching
from .models import AssetMerge, FieldConflict, ReconciliationCandidate, SourceLink

Candidate = ReconciliationCandidate
MAX_ERROR_SAMPLES = 20


# --- Ingestion ----------------------------------------------------------------------


def ingest(instance: IntegrationInstance, records, *, mode: str, triggered_by: str) -> SyncRun:
    """Process one batch of source records. Each record is isolated in a savepoint so
    one bad record never aborts the run (partial results keep everything else)."""
    if mode not in SyncRun.Mode.values:
        raise ValueError(f"Unknown mode {mode!r}")
    run = SyncRun.objects.create(instance=instance, mode=mode, triggered_by=triggered_by[:150])
    seen: set[str] = set()
    touched_assets: set = set()

    for record in records:
        run.records_received += 1
        try:
            with transaction.atomic():
                external_id, asset_id = _ingest_one(instance, run, record)
            seen.add(external_id)
            if asset_id:
                touched_assets.add(asset_id)
        except (RecordError, serializers.ValidationError) as exc:
            run.errors += 1
            if len(run.error_samples) < MAX_ERROR_SAMPLES:
                ext = record.get("external_id") if isinstance(record, dict) else None
                run.error_samples.append(
                    {"external_id": str(ext)[:200] if ext else None, "error": str(exc)[:300]}
                )

    processed = run.records_received - run.errors
    if run.errors == 0:
        run.status = SyncRun.Status.SUCCEEDED
    elif processed > 0:
        run.status = SyncRun.Status.PARTIAL
    else:
        run.status = SyncRun.Status.FAILED

    # Only a complete, error-free full inventory may declare unseen devices missing.
    if mode == SyncRun.Mode.FULL and run.status == SyncRun.Status.SUCCEEDED:
        missing = SourceLink.objects.filter(
            instance=instance, status=SourceLink.Status.ACTIVE
        ).exclude(external_id__in=seen)
        affected = set(missing.values_list("asset_id", flat=True))
        run.links_marked_stale = missing.update(status=SourceLink.Status.STALE)
        touched_assets |= affected
    authority.recompute_observation_status(touched_assets)

    run.finished_at = timezone.now()
    run.save()

    instance.last_attempt_at = run.finished_at
    if run.status != SyncRun.Status.FAILED:
        instance.last_success_at = run.finished_at
        instance.last_error = ""
    else:
        instance.last_error = (
            run.error_samples[0]["error"] if run.error_samples else "Sync failed"
        )[:500]
    if instance.source.availability == DiscoverySource.Availability.AVAILABLE:
        instance.status = (
            IntegrationInstance.Status.DEGRADED
            if run.status == SyncRun.Status.FAILED
            else IntegrationInstance.Status.AVAILABLE
        )
    instance.save(
        update_fields=["last_attempt_at", "last_success_at", "last_error", "status", "modified_at"]
    )
    return run


def _ingest_one(instance, run, record):
    normalized = normalize_record(
        record, site_id=str(instance.default_site_id), default_vrf=instance.default_vrf
    )
    external_id = normalized["external_id"]
    digest = checksum(record)
    observed_at = datetime.fromisoformat(normalized["observed_at"])

    latest = (
        Observation.objects.filter(instance=instance, external_id=external_id)
        .order_by("-received_at")
        .first()
    )
    if latest is not None and latest.checksum == digest:
        observation, changed = latest, False
        run.observations_unchanged += 1
    else:
        observation = Observation.objects.create(
            instance=instance,
            sync_run=run,
            external_id=external_id,
            observed_at=observed_at,
            checksum=digest,
            payload=record,
            normalized=normalized,
            normalizer_version=NORMALIZER_VERSION,
            source_version=normalized["source_version"],
        )
        changed = True
        run.observations_created += 1

    link = (
        SourceLink.objects.select_for_update()
        .filter(instance=instance, external_id=external_id)
        .first()
    )
    if link is not None and link.asset_id and link.status != SourceLink.Status.UNLINKED:
        link.last_seen_at = max(link.last_seen_at, observed_at)
        link.status = SourceLink.Status.ACTIVE
        link.last_observation = observation
        link.save(update_fields=["last_seen_at", "status", "last_observation"])
        run.links_refreshed += 1
        if changed:
            asset = Asset.objects.select_for_update().get(pk=link.asset_id)
            result = authority.apply_observation(asset, link, observation)
            run.assets_updated += 1 if result["changes"] else 0
            run.conflicts_opened += result["conflicts_opened"]
            _flag_duplicates(instance, link, observation, run)
        return external_id, link.asset_id

    _reconcile_unlinked(instance, external_id, observation, changed, run)
    linked = (
        SourceLink.objects.filter(instance=instance, external_id=external_id, asset__isnull=False)
        .exclude(status=SourceLink.Status.UNLINKED)
        .values_list("asset_id", flat=True)
        .first()
    )
    return external_id, linked


def _flag_duplicates(instance, link, observation, run) -> None:
    """A linked device whose strong IDs now point at another asset needs review."""
    result = matching.find_matches(
        instance, observation.normalized, exclude_asset_ids=[link.asset_id]
    )
    if not result.strong_asset_ids:
        return
    result.rule = Candidate.Rule.CONFLICT
    result.proposed_asset_id = str(link.asset_id)
    result.conflicts.append(
        "This linked device's serial or hardware UUID also matches another asset "
        "(possible duplicate)."
    )
    _upsert_candidate(instance, link.external_id, observation, result, run)


def _reconcile_unlinked(instance, external_id, observation, changed, run) -> None:
    last_rejected = (
        Candidate.objects.filter(
            instance=instance, external_id=external_id, status=Candidate.Status.REJECTED
        )
        .order_by("-decided_at")
        .first()
    )
    if last_rejected is not None and last_rejected.observation.checksum == observation.checksum:
        return  # rejected and unchanged since: stay rejected
    existing = Candidate.objects.filter(
        instance=instance, external_id=external_id, status__in=Candidate.OPEN_STATES
    ).first()
    if existing is not None and not changed:
        return  # idempotent: same report, same candidate

    result = matching.find_matches(instance, observation.normalized)
    if result.auto_linkable and instance.auto_link_strong_matches:
        asset = Asset.objects.select_for_update().get(pk=result.proposed_asset_id)
        link = _link(
            instance, external_id, asset, observation, SourceLink.Method.AUTO_STRONG_MATCH, None
        )
        outcome = authority.apply_observation(asset, link, observation)
        run.assets_updated += 1 if outcome["changes"] else 0
        run.conflicts_opened += outcome["conflicts_opened"]
        if existing is not None:
            existing.status = Candidate.Status.SUPERSEDED
            existing.decision = "auto_link"
            existing.decided_at = timezone.now()
            existing.resulting_asset = asset
            existing.save()
        _history(
            asset,
            AssetHistoryEntry.ChangeType.LINKED,
            None,
            {"source": {"before": None, "after": f"{instance.name} / {external_id}"}},
            "Automatic strong match (verified manufacturer and serial or hardware UUID)",
        )
        audit.record(
            action="reconciliation.auto_link",
            actor_label="system",
            object_type="asset",
            object_id=asset.pk,
            object_label=asset.name,
            after={"instance": instance.name, "external_id": external_id, "score": result.score},
            source="system",
        )
        return
    _upsert_candidate(instance, external_id, observation, result, run)


def _upsert_candidate(instance, external_id, observation, result, run) -> Candidate:
    fields = {
        "observation": observation,
        "site_id": instance.default_site_id,
        "rule": result.rule,
        "score": result.score,
        "proposed_asset_id": result.proposed_asset_id,
        "matches": result.matches,
        "conflicts": result.conflicts,
        "suggested_category": result.suggested_category,
    }
    existing = Candidate.objects.filter(
        instance=instance, external_id=external_id, status__in=Candidate.OPEN_STATES
    ).first()
    if existing is None:
        run.candidates_opened += 1
        return Candidate.objects.create(instance=instance, external_id=external_id, **fields)
    for key, value in fields.items():
        setattr(existing, key, value)
    existing.version = F("version") + 1
    existing.save()
    run.candidates_updated += 1
    return existing


def _link(instance, external_id, asset, observation, method, user) -> SourceLink:
    observed_at = observation.observed_at
    link, _ = SourceLink.objects.update_or_create(
        instance=instance,
        external_id=external_id,
        defaults={
            "asset": asset,
            "status": SourceLink.Status.ACTIVE,
            "method": method,
            "first_seen_at": observed_at,
            "last_seen_at": observed_at,
            "last_observation": observation,
            "linked_by": user,
            "unlinked_at": None,
            "unlinked_by": None,
            "unlink_reason": "",
        },
    )
    return link


def _history(asset, change_type, user, changes, reason="") -> None:
    AssetHistoryEntry.objects.create(
        asset=asset,
        actor=user,
        actor_label=user.username if user else "system",
        change_type=change_type,
        changes=changes,
        reason=reason,
        version=Asset.objects.values_list("version", flat=True).get(pk=asset.pk),
    )


# --- Candidate decisions -------------------------------------------------------------


def _decidable(candidate: Candidate, expected_version) -> Candidate:
    candidate = Candidate.objects.select_for_update().get(pk=candidate.pk)
    check_version(candidate, expected_version)
    if candidate.status not in Candidate.OPEN_STATES:
        raise ApiError(
            "CANDIDATE_CLOSED", "This candidate has already been decided.", status.HTTP_409_CONFLICT
        )
    return candidate


def _close(candidate, user, decision, reason, new_status, asset=None) -> None:
    candidate.status = new_status
    candidate.decision = decision
    candidate.decision_reason = reason
    candidate.decided_by = user
    candidate.decided_at = timezone.now()
    candidate.resulting_asset = asset
    candidate.version = F("version") + 1
    candidate.save()
    candidate.refresh_from_db()


def _audit_decision(request, candidate, action, asset=None, reason="") -> None:
    audit.record(
        action=f"reconciliation.{action}",
        actor=request.user,
        request=request,
        object_type="reconciliation_candidate",
        object_id=candidate.pk,
        object_label=f"{candidate.instance.name} / {candidate.external_id}",
        after={
            "rule": candidate.rule,
            "score": candidate.score,
            "asset": str(asset.pk) if asset else None,
            "observation": str(candidate.observation_id),
        },
        detail=reason,
    )


def approve_link(request, candidate, asset: Asset, reason: str, expected_version) -> Candidate:
    with transaction.atomic():
        candidate = _decidable(candidate, expected_version)
        asset = Asset.objects.select_for_update().get(pk=asset.pk)
        if asset.archived_at is not None:
            raise serializers.ValidationError(
                {"asset": ["Archived assets cannot receive new source links."]}
            )
        link = _link(
            candidate.instance,
            candidate.external_id,
            asset,
            candidate.observation,
            SourceLink.Method.APPROVED_CANDIDATE,
            request.user,
        )
        _history(
            asset,
            AssetHistoryEntry.ChangeType.LINKED,
            request.user,
            {
                "source": {
                    "before": None,
                    "after": f"{candidate.instance.name} / {candidate.external_id}",
                }
            },
            reason,
        )
        authority.apply_observation(asset, link, candidate.observation)
        authority.recompute_observation_status([asset.pk])
        _close(candidate, request.user, "link", reason, Candidate.Status.LINKED, asset)
        _audit_decision(request, candidate, "link", asset, reason)
    return candidate


def approve_create(request, candidate, data: dict, reason: str, expected_version) -> Candidate:
    with transaction.atomic():
        candidate = _decidable(candidate, expected_version)
        normalized = candidate.observation.normalized
        name = (
            (data.get("name") or "").strip()
            or (normalized["short_hostnames"] or [None])[0]
            or candidate.external_id
        )
        category = data.get("category") or candidate.suggested_category
        if category is None:
            raise serializers.ValidationError(
                {"category": ["Choose a category for the new asset."]}
            )
        # Business fields only; technical values arrive with discovery provenance below.
        asset = asset_services.create_asset(
            request,
            {
                "name": name[:200],
                "category": category,
                "site": candidate.site,
                "business_status": data.get("business_status") or Asset.BusinessStatus.DEPLOYED,
            },
        )
        link = _link(
            candidate.instance,
            candidate.external_id,
            asset,
            candidate.observation,
            SourceLink.Method.CREATED_FROM_CANDIDATE,
            request.user,
        )
        _history(
            asset,
            AssetHistoryEntry.ChangeType.LINKED,
            request.user,
            {
                "source": {
                    "before": None,
                    "after": f"{candidate.instance.name} / {candidate.external_id}",
                }
            },
            reason,
        )
        authority.apply_observation(
            Asset.objects.select_for_update().get(pk=asset.pk), link, candidate.observation
        )
        authority.recompute_observation_status([asset.pk])
        _close(candidate, request.user, "create", reason, Candidate.Status.CREATED, asset)
        _audit_decision(request, candidate, "create", asset, reason)
    return candidate


def reject(request, candidate, reason: str, expected_version) -> Candidate:
    with transaction.atomic():
        candidate = _decidable(candidate, expected_version)
        _close(candidate, request.user, "reject", reason, Candidate.Status.REJECTED)
        _audit_decision(request, candidate, "reject", reason=reason)
    return candidate


def hold(request, candidate, reason: str, expected_version) -> Candidate:
    with transaction.atomic():
        candidate = Candidate.objects.select_for_update().get(pk=candidate.pk)
        check_version(candidate, expected_version)
        if candidate.status != Candidate.Status.OPEN:
            raise ApiError(
                "CANDIDATE_NOT_OPEN",
                "Only open candidates can be put on hold.",
                status.HTTP_409_CONFLICT,
            )
        candidate.status = Candidate.Status.HELD
        candidate.decision = "hold"
        candidate.decision_reason = reason
        candidate.decided_by = request.user
        candidate.decided_at = timezone.now()
        candidate.version = F("version") + 1
        candidate.save()
        candidate.refresh_from_db()
        _audit_decision(request, candidate, "hold", reason=reason)
    return candidate


# --- Links --------------------------------------------------------------------------


def unlink(request, link: SourceLink, reason: str) -> SourceLink:
    """Reverses a link: removes the source's identifiers from the asset and reopens
    the device for review. Field values and history are kept."""
    with transaction.atomic():
        link = SourceLink.objects.select_for_update().select_related("instance").get(pk=link.pk)
        if link.status == SourceLink.Status.UNLINKED or link.asset_id is None:
            raise ApiError(
                "ALREADY_UNLINKED", "This source link is already removed.", status.HTTP_409_CONFLICT
            )
        asset = Asset.objects.select_for_update().get(pk=link.asset_id)
        key = authority.link_key(link.instance, link.external_id)
        before = asset_services.network_snapshot(asset)
        for model in (AssetHostname, AssetIPAddress, AssetInterface):
            model.objects.filter(asset=asset, source_ref=key).delete()
        after = asset_services.network_snapshot(asset)
        link.status = SourceLink.Status.UNLINKED
        link.asset = None
        link.unlinked_at = timezone.now()
        link.unlinked_by = request.user
        link.unlink_reason = reason
        link.version = F("version") + 1
        link.save()
        changes = {
            "source": {"before": f"{link.instance.name} / {link.external_id}", "after": None}
        }
        changes.update(
            {k: {"before": before[k], "after": after[k]} for k in after if before[k] != after[k]}
        )
        _history(asset, AssetHistoryEntry.ChangeType.UNLINKED, request.user, changes, reason)
        authority.recompute_observation_status([asset.pk])
        if link.last_observation_id:
            counters = SimpleNamespace(candidates_opened=0, candidates_updated=0)
            result = matching.find_matches(
                link.instance, link.last_observation.normalized, exclude_asset_ids=[asset.pk]
            )
            _upsert_candidate(
                link.instance, link.external_id, link.last_observation, result, counters
            )
        audit.record(
            action="reconciliation.unlink",
            actor=request.user,
            request=request,
            object_type="asset",
            object_id=asset.pk,
            object_label=asset.name,
            before={"instance": link.instance.name, "external_id": link.external_id},
            detail=reason,
        )
    link.refresh_from_db()
    return link


# --- Merge ----------------------------------------------------------------------------


def merge(request, survivor: Asset, merged: Asset, reason: str, expected_version) -> AssetMerge:
    if survivor.pk == merged.pk:
        raise serializers.ValidationError({"source_asset": ["Choose a different asset to merge."]})
    with transaction.atomic():
        first, second = sorted([survivor.pk, merged.pk], key=str)  # stable lock order
        locked = {a.pk: a for a in Asset.objects.select_for_update().filter(pk__in=[first, second])}
        survivor, merged = locked[survivor.pk], locked[merged.pk]
        check_version(survivor, expected_version)
        if survivor.archived_at or merged.archived_at:
            raise ApiError(
                "ASSET_ARCHIVED", "Archived assets cannot be merged.", status.HTTP_409_CONFLICT
            )

        snapshot = asset_services.snapshot(merged)
        links = list(
            SourceLink.objects.filter(asset=merged).exclude(status=SourceLink.Status.UNLINKED)
        )
        moved_ids = {}
        for model, key in (
            (AssetHostname, "hostnames"),
            (AssetInterface, "interfaces"),
            (AssetIPAddress, "ip_addresses"),
        ):
            rows = model.objects.filter(asset=merged).exclude(source=Source.MANUAL)
            moved_ids[key] = [str(pk) for pk in rows.values_list("pk", flat=True)]
            rows.update(asset=survivor)
        SourceLink.objects.filter(pk__in=[link.pk for link in links]).update(asset=survivor)

        merged.archived_at = timezone.now()
        merged.archived_by = request.user
        merged.archive_reason = f"Merged into {survivor.name} ({survivor.pk}): {reason}"[:500]
        merged.version = F("version") + 1
        merged.save()
        survivor.version = F("version") + 1
        survivor.save()

        record = AssetMerge.objects.create(
            survivor=survivor,
            merged=merged,
            reason=reason,
            moved_link_ids=[str(link.pk) for link in links],
            moved_identifier_ids=moved_ids,
            merged_snapshot=snapshot,
            performed_by=request.user,
        )
        moved = [f"{link.instance.name} / {link.external_id}" for link in links]
        _history(
            survivor,
            AssetHistoryEntry.ChangeType.MERGED,
            request.user,
            {
                "merged_asset": {"before": None, "after": merged.name},
                "sources": {"before": None, "after": moved},
            },
            reason,
        )
        _history(
            merged,
            AssetHistoryEntry.ChangeType.MERGED,
            request.user,
            {
                "merged_into": {"before": None, "after": survivor.name},
                "archived": {"before": False, "after": True},
            },
            reason,
        )
        authority.recompute_observation_status([survivor.pk, merged.pk])
        audit.record(
            action="assets.merge",
            actor=request.user,
            request=request,
            object_type="asset",
            object_id=survivor.pk,
            object_label=survivor.name,
            after={"merged_asset": str(merged.pk), "merge": str(record.pk), "moved_links": moved},
            detail=reason,
        )
    return record


def revert_merge(request, record: AssetMerge, reason: str) -> AssetMerge:
    with transaction.atomic():
        record = AssetMerge.objects.select_for_update().get(pk=record.pk)
        if record.status != AssetMerge.Status.MERGED:
            raise ApiError(
                "MERGE_REVERTED", "This merge has already been reverted.", status.HTTP_409_CONFLICT
            )
        survivor = Asset.objects.select_for_update().get(pk=record.survivor_id)
        merged = Asset.objects.select_for_update().get(pk=record.merged_id)

        SourceLink.objects.filter(pk__in=record.moved_link_ids, asset=survivor).update(asset=merged)
        for model, key in (
            (AssetHostname, "hostnames"),
            (AssetInterface, "interfaces"),
            (AssetIPAddress, "ip_addresses"),
        ):
            model.objects.filter(
                pk__in=record.moved_identifier_ids.get(key, []), asset=survivor
            ).update(asset=merged)

        merged.archived_at = None
        merged.archived_by = None
        merged.archive_reason = ""
        merged.version = F("version") + 1
        merged.save()
        survivor.version = F("version") + 1
        survivor.save()

        record.status = AssetMerge.Status.REVERTED
        record.reverted_by = request.user
        record.reverted_at = timezone.now()
        record.revert_reason = reason
        record.save()
        for asset, other in ((survivor, merged), (merged, survivor)):
            _history(
                asset,
                AssetHistoryEntry.ChangeType.UNMERGED,
                request.user,
                {"merge_reverted_with": {"before": other.name, "after": None}},
                reason,
            )
        authority.recompute_observation_status([survivor.pk, merged.pk])
        audit.record(
            action="assets.merge_revert",
            actor=request.user,
            request=request,
            object_type="asset",
            object_id=survivor.pk,
            object_label=survivor.name,
            after={"restored_asset": str(merged.pk), "merge": str(record.pk)},
            detail=reason,
        )
    return record


# --- Field locks and conflicts --------------------------------------------------------


def _check_field(field: str) -> None:
    if field not in TECHNICAL_FIELDS:
        raise serializers.ValidationError(
            {"field": [f"Locks apply only to technical fields: {', '.join(TECHNICAL_FIELDS)}."]}
        )


def lock_field(request, asset: Asset, field: str, reason: str) -> FieldLock:
    _check_field(field)
    with transaction.atomic():
        lock, created = FieldLock.objects.get_or_create(
            asset=asset, field=field, defaults={"locked_by": request.user, "reason": reason}
        )
        if created:
            _history(
                asset,
                AssetHistoryEntry.ChangeType.FIELD_LOCKED,
                request.user,
                {
                    field: {
                        "before": "unlocked",
                        "after": f"locked ({getattr(asset, field) or 'empty'})",
                    }
                },
                reason,
            )
            audit.record(
                action="assets.field_lock",
                actor=request.user,
                request=request,
                object_type="asset",
                object_id=asset.pk,
                object_label=asset.name,
                after={"field": field},
                detail=reason,
            )
    return lock


def unlock_field(request, asset: Asset, field: str, reason: str) -> None:
    _check_field(field)
    with transaction.atomic():
        deleted, _ = FieldLock.objects.filter(asset=asset, field=field).delete()
        if not deleted:
            raise ApiError("NOT_LOCKED", "This field is not locked.", status.HTTP_409_CONFLICT)
        _history(
            asset,
            AssetHistoryEntry.ChangeType.FIELD_UNLOCKED,
            request.user,
            {field: {"before": "locked", "after": "unlocked"}},
            reason,
        )
        audit.record(
            action="assets.field_unlock",
            actor=request.user,
            request=request,
            object_type="asset",
            object_id=asset.pk,
            object_label=asset.name,
            after={"field": field},
            detail=reason,
        )


def resolve_conflict(
    request, conflict: FieldConflict, resolution: str, reason: str
) -> FieldConflict:
    with transaction.atomic():
        conflict = (
            FieldConflict.objects.select_for_update()
            .select_related("instance", "observation")
            .get(pk=conflict.pk)
        )
        if conflict.status != FieldConflict.Status.OPEN:
            raise ApiError(
                "CONFLICT_CLOSED",
                "This conflict has already been resolved.",
                status.HTTP_409_CONFLICT,
            )
        asset = Asset.objects.select_for_update().get(pk=conflict.asset_id)
        if resolution == "accept_observed":
            before = getattr(asset, conflict.field)
            setattr(asset, conflict.field, conflict.observed_value)
            asset.version = F("version") + 1
            asset.modified_by = request.user
            asset.save()
            asset.refresh_from_db()
            FieldLock.objects.filter(asset=asset, field=conflict.field).delete()
            FieldProvenance.objects.update_or_create(
                asset=asset,
                field=conflict.field,
                defaults={
                    "kind": FieldProvenance.Kind.DISCOVERY,
                    "instance": conflict.instance,
                    "observation": conflict.observation,
                    "value": conflict.observed_value,
                    "observed_at": conflict.observation.observed_at,
                    "recorded_by": request.user,
                },
            )
            _history(
                asset,
                AssetHistoryEntry.ChangeType.UPDATED,
                request.user,
                {conflict.field: {"before": before, "after": conflict.observed_value}},
                f"Accepted value from {conflict.instance.name}: {reason}",
            )
            conflict.status = FieldConflict.Status.ACCEPTED
        else:
            conflict.status = FieldConflict.Status.DISMISSED
        conflict.resolved_by = request.user
        conflict.resolved_at = timezone.now()
        conflict.resolution_reason = reason
        conflict.save()
        audit.record(
            action=f"reconciliation.conflict_{conflict.status}",
            actor=request.user,
            request=request,
            object_type="asset",
            object_id=asset.pk,
            object_label=asset.name,
            before={"field": conflict.field, "value": conflict.current_value},
            after={
                "field": conflict.field,
                "observed": conflict.observed_value,
                "source": conflict.instance.name,
            },
            detail=reason,
        )
    return conflict


# --- Freshness ------------------------------------------------------------------------


def refresh_freshness(now=None) -> int:
    """Mark links stale when a source has not reported a device within the instance's
    threshold. Never deletes or archives assets (docs/15 A08)."""
    now = now or timezone.now()
    total = 0
    for instance in IntegrationInstance.objects.all():
        cutoff = now - timedelta(hours=instance.stale_after_hours)
        stale = SourceLink.objects.filter(
            instance=instance, status=SourceLink.Status.ACTIVE, last_seen_at__lt=cutoff
        )
        asset_ids = set(stale.values_list("asset_id", flat=True))
        total += stale.update(status=SourceLink.Status.STALE)
        authority.recompute_observation_status(asset_ids)
    return total
