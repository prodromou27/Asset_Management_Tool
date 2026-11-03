"""Reconciliation queue triage (Task 011): assignment and bulk hold/reject/assign.

Bulk actions never link or create assets: those decisions stay one candidate at a time
with the evidence on screen. Each item in a bulk request is decided independently (own
transaction, audit entry and result); one failure never undoes the others.
"""

from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import F
from django.utils import timezone
from rest_framework import serializers

from apps.accounts import catalog
from apps.audit import services as audit
from apps.organizations import scope
from apps.organizations.services import check_version
from config.api import ApiError

from . import services
from .models import ReconciliationCandidate as Candidate

MAX_BULK = 200


def validate_assignee(user_id, site_ids) -> object | None:
    """An assignee must be an active user who may decide candidates in every given site."""
    if user_id is None:
        return None
    user = get_user_model().objects.filter(pk=user_id, is_active=True).first()
    if user is None:
        raise serializers.ValidationError({"assignee": ["User not found or disabled."]})
    if catalog.RECONCILIATION_DECIDE not in user.permission_codes():
        raise serializers.ValidationError(
            {"assignee": ["This user cannot decide reconciliation items."]}
        )
    if not all(scope.can_access_site(user, site_id) for site_id in site_ids):
        raise serializers.ValidationError({"assignee": ["This user has no access to the site."]})
    return user


def assign(request, candidate: Candidate, assignee, expected_version=None) -> Candidate:
    with transaction.atomic():
        candidate = Candidate.objects.select_for_update().get(pk=candidate.pk)
        if expected_version is not None:
            check_version(candidate, expected_version)
        if candidate.status not in Candidate.OPEN_STATES:
            raise ApiError("CANDIDATE_CLOSED", "This candidate has already been decided.", 409)
        before = candidate.assignee.username if candidate.assignee else None
        candidate.assignee = assignee
        candidate.assigned_at = timezone.now() if assignee else None
        candidate.version = F("version") + 1
        candidate.save()
        candidate.refresh_from_db()
        audit.record(
            action="reconciliation.assign",
            actor=request.user,
            request=request,
            object_type="reconciliation_candidate",
            object_id=candidate.pk,
            object_label=f"{candidate.instance.name} / {candidate.external_id}",
            before={"assignee": before},
            after={"assignee": assignee.username if assignee else None},
        )
    return candidate


def bulk(request, items: list[tuple[Candidate, int]], action: str, reason: str, assignee):
    """items: (candidate, version the reviewer saw). A changed candidate is skipped with
    VERSION_MISMATCH instead of being decided on stale evidence."""
    results = []
    for candidate, version in items:
        try:
            if action == "hold":
                services.hold(request, candidate, reason, version)
            elif action == "reject":
                services.reject(request, candidate, reason, version)
            elif action == "assign":
                assign(request, candidate, assignee, version)
            else:  # validated by the serializer
                raise ValueError(action)
            results.append({"id": str(candidate.pk), "ok": True, "error": ""})
        except ApiError as exc:
            results.append({"id": str(candidate.pk), "ok": False, "error": str(exc.detail)})
        except serializers.ValidationError as exc:
            results.append({"id": str(candidate.pk), "ok": False, "error": str(exc.detail)[:300]})
    return results
