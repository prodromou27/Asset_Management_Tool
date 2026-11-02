"""Site, location, department and site-grant services. All mutations audited."""

from django.db import transaction
from django.db.models import F
from rest_framework import serializers, status

from apps.audit import services as audit
from config.api import ApiError

from .models import Department, Location, Site, UserSiteGrant


def check_version(obj, expected: int | None) -> None:
    if expected is None:
        raise ApiError(
            "PRECONDITION_REQUIRED",
            "If-Match header with the current version is required.",
            status.HTTP_428_PRECONDITION_REQUIRED,
        )
    if obj.version != expected:
        raise ApiError(
            "VERSION_MISMATCH",
            "This record was changed by someone else. Reload and try again.",
            status.HTTP_409_CONFLICT,
        )


def _snapshot(obj, fields) -> dict:
    out = {}
    for field in fields:
        value = getattr(obj, field)
        if hasattr(value, "pk"):
            value = str(value)
        out[field] = value
    return out


def _save_with_audit(request, obj, before, fields, action, object_type):
    after = _snapshot(obj, fields)
    if before is not None and after == before:
        return obj
    if before is not None:
        obj.version = F("version") + 1
    obj.save()
    obj.refresh_from_db()
    audit.record(
        action=action,
        actor=request.user,
        request=request,
        object_type=object_type,
        object_id=obj.pk,
        object_label=str(obj),
        before=before,
        after=after,
    )
    return obj


def _ancestor_ids(model, start):
    seen = set()
    node = start
    while node is not None:
        if node.pk in seen:
            break
        seen.add(node.pk)
        node = model.objects.filter(pk=node.parent_id).first() if node.parent_id else None
    return seen


# --- Sites --------------------------------------------------------------------

SITE_FIELDS = ("code", "name", "parent", "description", "is_active")


def _validate_site_parent(site: Site | None, parent: Site | None) -> None:
    if parent is None:
        return
    if site is not None and site.pk in _ancestor_ids(Site, parent):
        raise serializers.ValidationError({"parent": ["A site cannot be its own ancestor."]})


def create_site(request, data: dict) -> Site:
    _validate_site_parent(None, data.get("parent"))
    site = Site(**data)
    with transaction.atomic():
        return _save_with_audit(request, site, None, SITE_FIELDS, "sites.create", "site")


def update_site(request, site: Site, changes: dict, expected_version: int | None) -> Site:
    with transaction.atomic():
        site = Site.objects.select_for_update().get(pk=site.pk)
        check_version(site, expected_version)
        before = _snapshot(site, SITE_FIELDS)
        if "parent" in changes:
            _validate_site_parent(site, changes["parent"])
        for field, value in changes.items():
            setattr(site, field, value)
        return _save_with_audit(request, site, before, SITE_FIELDS, "sites.update", "site")


# --- Locations ----------------------------------------------------------------

LOCATION_FIELDS = ("site", "parent", "name", "kind", "is_active")


def _validate_location(location: Location | None, site: Site, parent: Location | None) -> None:
    if parent is None:
        return
    if parent.site_id != site.pk:
        raise serializers.ValidationError(
            {"parent": ["The parent location must belong to the same site."]}
        )
    if location is not None and location.pk in _ancestor_ids(Location, parent):
        raise serializers.ValidationError({"parent": ["A location cannot be its own ancestor."]})


def create_location(request, data: dict) -> Location:
    _validate_location(None, data["site"], data.get("parent"))
    location = Location(**data)
    with transaction.atomic():
        return _save_with_audit(
            request, location, None, LOCATION_FIELDS, "locations.create", "location"
        )


def update_location(
    request, location: Location, changes: dict, expected_version: int | None
) -> Location:
    if "site" in changes and changes["site"].pk != location.site_id:
        raise serializers.ValidationError(
            {"site": ["A location cannot move to another site; create a new one instead."]}
        )
    with transaction.atomic():
        location = Location.objects.select_for_update().get(pk=location.pk)
        check_version(location, expected_version)
        before = _snapshot(location, LOCATION_FIELDS)
        if "parent" in changes:
            _validate_location(location, location.site, changes["parent"])
        for field, value in changes.items():
            setattr(location, field, value)
        return _save_with_audit(
            request, location, before, LOCATION_FIELDS, "locations.update", "location"
        )


# --- Departments --------------------------------------------------------------

DEPARTMENT_FIELDS = ("name", "code", "is_active")


def create_department(request, data: dict) -> Department:
    department = Department(**data)
    with transaction.atomic():
        return _save_with_audit(
            request, department, None, DEPARTMENT_FIELDS, "departments.create", "department"
        )


def update_department(
    request, department: Department, changes: dict, expected_version: int | None
) -> Department:
    with transaction.atomic():
        department = Department.objects.select_for_update().get(pk=department.pk)
        check_version(department, expected_version)
        before = _snapshot(department, DEPARTMENT_FIELDS)
        for field, value in changes.items():
            setattr(department, field, value)
        return _save_with_audit(
            request, department, before, DEPARTMENT_FIELDS, "departments.update", "department"
        )


# --- User site grants ---------------------------------------------------------


def site_codes_for(user) -> list[str]:
    return sorted(UserSiteGrant.objects.filter(user=user).values_list("site__code", flat=True))


def set_user_sites(user, sites: list[Site], granted_by) -> None:
    wanted = {site.pk for site in sites}
    current = set(UserSiteGrant.objects.filter(user=user).values_list("site_id", flat=True))
    UserSiteGrant.objects.filter(user=user, site_id__in=current - wanted).delete()
    UserSiteGrant.objects.bulk_create(
        [
            UserSiteGrant(user=user, site_id=site_id, granted_by=granted_by)
            for site_id in wanted - current
        ]
    )
