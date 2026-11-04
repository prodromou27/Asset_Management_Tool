"""Site-scoped reads of software installations.

Discovered installations belong to a source device; they are visible when that device is
linked (active or stale, not unlinked) to an asset the user may see. Manual installations
are visible with their asset. Archived assets are excluded from inventory views.
"""

from django.db.models import Exists, OuterRef, Q, Subquery, UUIDField
from django.db.models.functions import Coalesce

from apps.assets.selectors import visible_assets
from apps.reconciliation.models import SourceLink

from .models import SoftwareInstallation


def _links(asset_ids):
    return SourceLink.objects.filter(asset__in=asset_ids).exclude(status=SourceLink.Status.UNLINKED)


def visible_installations(user, include_removed: bool = False):
    assets = visible_assets(user).filter(archived_at__isnull=True).values("pk")
    links = _links(assets).filter(
        instance_id=OuterRef("instance_id"), external_id=OuterRef("external_id")
    )
    qs = SoftwareInstallation.objects.filter(Q(asset__in=assets) | Exists(links))
    if not include_removed:
        qs = qs.filter(removed_at__isnull=True)
    return qs.annotate(
        resolved_asset_id=Coalesce(
            "asset_id", Subquery(links.values("asset_id")[:1]), output_field=UUIDField()
        )
    )


def installations_for_asset(asset, include_removed: bool = False):
    pairs = list(_links([asset.pk]).values_list("instance_id", "external_id"))
    condition = Q(asset=asset)
    for instance_id, external_id in pairs:
        condition |= Q(instance_id=instance_id, external_id=external_id)
    qs = SoftwareInstallation.objects.filter(condition)
    if not include_removed:
        qs = qs.filter(removed_at__isnull=True)
    return qs


def installations_for_assets(asset_ids):
    """(asset_id, installation) pairs for many assets (exports)."""
    links: dict[tuple, list] = {}
    for asset_id, instance_id, external_id in _links(asset_ids).values_list(
        "asset_id", "instance_id", "external_id"
    ):
        links.setdefault((instance_id, external_id), []).append(asset_id)
    rows = []
    manual = SoftwareInstallation.objects.filter(asset_id__in=asset_ids, removed_at__isnull=True)
    for row in manual.select_related("version__product"):
        rows.append((row.asset_id, row))
    if links:
        # Narrow by both columns, then keep exact (instance, device) pairs.
        discovered = SoftwareInstallation.objects.filter(
            instance_id__in={i for i, _ in links},
            external_id__in={e for _, e in links},
            removed_at__isnull=True,
        )
        for row in discovered.select_related("version__product", "instance"):
            for asset_id in links.get((row.instance_id, row.external_id), []):
                rows.append((asset_id, row))
    return rows
