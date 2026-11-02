"""Site scope resolution. Every site-scoped queryset must go through here.

A user sees a site when they have `all_sites`, or a grant on that site or on any
of its ancestors. Resolved from the database on every request, so grant changes
apply on the next request.
"""

from collections import defaultdict
from uuid import UUID

from .models import Site, UserSiteGrant

ALL = None  # sentinel: unrestricted
_CACHE_ATTR = "_itam_site_scope"


def descendants(site_ids: set[UUID]) -> set[UUID]:
    children: dict[UUID | None, list[UUID]] = defaultdict(list)
    for site_id, parent_id in Site.objects.values_list("id", "parent_id"):
        children[parent_id].append(site_id)
    result: set[UUID] = set()
    stack = list(site_ids)
    while stack:
        current = stack.pop()
        if current in result:
            continue
        result.add(current)
        stack.extend(children.get(current, []))
    return result


def accessible_site_ids(user) -> set[UUID] | None:
    """Return the set of visible site IDs, or ALL (None) for unrestricted users."""
    if user is None or not user.is_authenticated or not user.is_active:
        return set()
    cached = getattr(user, _CACHE_ATTR, False)
    if cached is not False:
        return cached
    if user.all_sites:
        scope = ALL
    else:
        granted = set(UserSiteGrant.objects.filter(user=user).values_list("site_id", flat=True))
        scope = descendants(granted) if granted else set()
    setattr(user, _CACHE_ATTR, scope)
    return scope


def restrict(queryset, user, field: str = "site"):
    """Filter any queryset with a site FK to the user's scope."""
    scope = accessible_site_ids(user)
    if scope is ALL:
        return queryset
    return queryset.filter(**{f"{field}__in": scope})


def can_access_site(user, site_id) -> bool:
    scope = accessible_site_ids(user)
    return scope is ALL or site_id in scope
