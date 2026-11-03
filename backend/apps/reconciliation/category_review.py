"""Category mismatch review (Task 011, docs/01 "Reclassify").

A linked source's device type maps to a category (observations.normalize
DEVICE_TYPE_TO_CATEGORY). When that category differs from the asset's, a CategoryReview is
opened instead of changing the asset: category is business data and is only changed by a
person, through the audited reclassification service with its template impact preview.

No review when the source agrees, or when it is less specific than the asset (the
suggestion is an ancestor of the asset's category, e.g. "Workstations" for a laptop).
"""

from django.db import transaction
from django.db.models import F
from django.utils import timezone
from rest_framework import serializers

from apps.assets import services as asset_services
from apps.assets.models import Asset, AssetCategory
from apps.assets.tree import CategoryTree
from apps.audit import services as audit
from apps.organizations.services import check_version
from config.api import ApiError

from .models import CategoryReview

Review = CategoryReview


def kind_of(tree: CategoryTree, current_id, suggested_id) -> str | None:
    """None when no review is needed."""
    if current_id == suggested_id or suggested_id in tree.lineage(current_id):
        return None
    if current_id in tree.lineage(suggested_id):
        return Review.Kind.MORE_SPECIFIC
    if tree.lineage(current_id)[0] != tree.lineage(suggested_id)[0]:
        return Review.Kind.DIFFERENT_CLASS
    return Review.Kind.DIFFERENT_TYPE


def _close(reviews, status, user=None, reason="") -> int:
    return reviews.update(
        status=status,
        resolved_by=user,
        resolved_at=timezone.now(),
        resolution_reason=reason[:500],
        version=F("version") + 1,
    )


def review_observation(asset: Asset, link, observation) -> None:
    """Open, refresh or close the review for one source link after an observation."""
    normalized = observation.normalized
    open_reviews = Review.objects.filter(
        asset=asset, instance=link.instance, status=Review.Status.OPEN
    )
    code = normalized.get("category_code")
    suggested = AssetCategory.objects.filter(code=code, is_active=True).first() if code else None
    if suggested is None:
        _close(open_reviews, Review.Status.RESOLVED, reason="The source no longer reports a type.")
        return
    tree = CategoryTree()
    kind = kind_of(tree, asset.category_id, suggested.pk)
    if kind is None:
        _close(open_reviews, Review.Status.RESOLVED, reason="The source now agrees.")
        return
    existing = open_reviews.first()
    if existing is not None:
        if (
            existing.suggested_category_id != suggested.pk
            or existing.observation_id != observation.pk
        ):
            existing.suggested_category = suggested
            existing.current_category_id = asset.category_id
            existing.kind = kind
            existing.observation = observation
            existing.reported_type = str(normalized.get("device_type") or "")[:40]
            existing.version = F("version") + 1
            existing.save()
        return
    kept = Review.objects.filter(
        asset=asset,
        instance=link.instance,
        status=Review.Status.DISMISSED,
        suggested_category=suggested,
        current_category_id=asset.category_id,
    ).exists()
    if kept:
        return  # a reviewer already kept the current category for this suggestion
    Review.objects.create(
        asset=asset,
        instance=link.instance,
        external_id=link.external_id,
        observation=observation,
        current_category_id=asset.category_id,
        suggested_category=suggested,
        reported_type=str(normalized.get("device_type") or "")[:40],
        kind=kind,
    )


def on_reclassified(sender, asset, request, reason, **kwargs) -> None:
    """Any reclassification (review, asset page, link-time) settles open reviews."""
    tree = CategoryTree()
    for review in Review.objects.filter(asset=asset, status=Review.Status.OPEN):
        if review.suggested_category_id == asset.category_id:
            _close(
                Review.objects.filter(pk=review.pk),
                Review.Status.RECLASSIFIED,
                getattr(request, "user", None),
                reason,
            )
        elif kind_of(tree, asset.category_id, review.suggested_category_id) is None:
            _close(
                Review.objects.filter(pk=review.pk),
                Review.Status.RESOLVED,
                reason="The new category agrees with the source.",
            )
        else:
            Review.objects.filter(pk=review.pk).update(
                current_category_id=asset.category_id,
                kind=kind_of(tree, asset.category_id, review.suggested_category_id),
                version=F("version") + 1,
            )


def _decidable(review: Review, expected_version) -> Review:
    review = Review.objects.select_for_update().get(pk=review.pk)
    check_version(review, expected_version)
    if review.status != Review.Status.OPEN:
        raise ApiError("REVIEW_CLOSED", "This category review is already resolved.", 409)
    return review


def reclassify(request, review: Review, reason: str, custom_fields, expected_version) -> Review:
    with transaction.atomic():
        review = _decidable(review, expected_version)
        asset = Asset.objects.get(pk=review.asset_id)
        if not review.suggested_category.is_active:
            raise serializers.ValidationError({"category": ["The suggested category is inactive."]})
        asset_services.reclassify(
            request, asset, review.suggested_category, reason, custom_fields, asset.version
        )  # sends asset_reclassified → closes this review as RECLASSIFIED
        review.refresh_from_db()
    return review


def dismiss(request, review: Review, reason: str, expected_version) -> Review:
    with transaction.atomic():
        review = _decidable(review, expected_version)
        _close(Review.objects.filter(pk=review.pk), Review.Status.DISMISSED, request.user, reason)
        review.refresh_from_db()
        audit.record(
            action="reconciliation.category_review_dismiss",
            actor=request.user,
            request=request,
            object_type="asset",
            object_id=review.asset_id,
            object_label=review.asset.name,
            after={
                "kept": review.current_category.name,
                "suggested": review.suggested_category.name,
                "source": review.instance.name,
            },
            detail=reason,
        )
    return review
