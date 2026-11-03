"""Asset domain services. Views stay thin; every mutation writes history + audit.

Concurrency: mutations lock the row (SELECT ... FOR UPDATE) and compare the
client's If-Match version inside the transaction, so two writers holding the same
version cannot both succeed.
"""

from django.db import IntegrityError, transaction
from django.db.models import F
from django.utils import timezone
from django.utils.text import slugify
from rest_framework import serializers, status

from apps.audit import services as audit
from apps.organizations.models import Department, Location, Site
from apps.organizations.services import check_version
from config.api import ApiError
from config.request_context import get_request_id

from . import custom_fields as cf
from .models import (
    TECHNICAL_FIELDS,
    Asset,
    AssetCategory,
    AssetHistoryEntry,
    AssetHostname,
    AssetInterface,
    AssetIPAddress,
    CustomFieldDefinition,
    FieldLock,
    FieldProvenance,
    Source,
)
from .signals import asset_reclassified
from .tree import CategoryTree

SCALAR_FIELDS = (
    "name",
    "asset_tag",
    "manufacturer",
    "model",
    "serial_number",
    "os_name",
    "os_version",
    "firmware_version",
    "site",
    "location",
    "department",
    "owner",
    "business_status",
    "notes",
)
REASSIGNMENT_FIELDS = {"site", "location", "department", "owner"}
NETWORK_KEYS = ("hostnames", "interfaces", "ip_addresses")
MAX_CATEGORY_DEPTH = 5


# --- Snapshots and history ----------------------------------------------------


def _label(value):
    """Human-readable, stable representation for history/audit."""
    if isinstance(value, Site):
        return value.code
    if isinstance(value, (Location, Department)):
        return value.name
    if hasattr(value, "username"):
        return value.username
    return value


def network_snapshot(asset: Asset) -> dict:
    def suffix(row):
        parts = []
        if getattr(row, "is_primary", False):
            parts.append("primary")
        if row.source != Source.MANUAL:
            parts.append(row.source)
        return f" ({', '.join(parts)})" if parts else ""

    return {
        "hostnames": sorted(f"{h.hostname}{suffix(h)}" for h in asset.hostnames.all()),
        "interfaces": sorted(
            f"{i.name}{' ' + i.mac_address if i.mac_address else ''}{suffix(i)}"
            for i in asset.interfaces.all()
        ),
        "ip_addresses": sorted(
            f"{a.address}{' on ' + a.interface.name if a.interface_id else ''}{suffix(a)}"
            for a in asset.ip_addresses.select_related("interface")
        ),
    }


def snapshot(asset: Asset, tree: CategoryTree | None = None) -> dict:
    tree = tree or CategoryTree()
    data = {field: _label(getattr(asset, field)) for field in SCALAR_FIELDS}
    data["category"] = tree.path(asset.category_id) if asset.category_id else None
    data["custom_fields"] = dict(sorted(asset.custom_fields.items()))
    data.update(network_snapshot(asset))
    data["archived"] = asset.archived_at is not None
    return data


def diff(before: dict, after: dict) -> dict:
    return {
        key: {"before": before.get(key), "after": after.get(key)}
        for key in sorted(set(before) | set(after))
        if before.get(key) != after.get(key)
    }


def _record(request, asset, change_type, changes, reason="", action=None, before=None, after=None):
    actor = request.user if request is not None else None
    AssetHistoryEntry.objects.create(
        asset=asset,
        actor=actor,
        actor_label=actor.username if actor is not None else "system",
        change_type=change_type,
        changes=changes,
        reason=reason,
        version=asset.version,
        request_id=get_request_id() or "",
    )
    audit.record(
        action=action or f"assets.{change_type}",
        actor=actor,
        request=request,
        object_type="asset",
        object_id=asset.pk,
        object_label=asset.name,
        before=before,
        after=after,
        detail=reason,
    )


def _locked(asset: Asset, expected_version: int | None, *, allow_archived=False) -> Asset:
    asset = Asset.objects.select_for_update().get(pk=asset.pk)
    check_version(asset, expected_version)
    if asset.archived_at is not None and not allow_archived:
        raise ApiError(
            "ASSET_ARCHIVED",
            "This asset is archived. Restore it before making changes.",
            status.HTTP_409_CONFLICT,
        )
    return asset


def _save(asset: Asset) -> None:
    try:
        with transaction.atomic():
            asset.save()
    except IntegrityError as exc:
        if "asset_tag" in str(exc):
            raise serializers.ValidationError(
                {"asset_tag": ["This asset tag is already in use."]}
            ) from exc
        raise


# --- Network identifiers ------------------------------------------------------


def _validate_network(asset: Asset | None, network: dict) -> None:
    errors: dict[str, list[str]] = {}
    for key, value_key in (
        ("hostnames", "hostname"),
        ("interfaces", "name"),
        ("ip_addresses", "address"),
    ):
        rows = network.get(key)
        if rows is None:
            continue
        seen = set()
        primaries = 0
        for index, row in enumerate(rows):
            value = row[value_key]
            if value in seen:
                errors[f"{key}.{index}.{value_key}"] = ["Duplicate entry."]
            seen.add(value)
            primaries += 1 if row.get("is_primary") else 0
        if primaries > 1:
            errors[key] = ["Mark at most one entry as primary."]

    if network.get("ip_addresses") is not None:
        if network.get("interfaces") is not None:
            names = {row["name"] for row in network["interfaces"]}
        elif asset is not None:
            names = set(
                asset.interfaces.filter(source=Source.MANUAL).values_list("name", flat=True)
            )
        else:
            names = set()
        if asset is not None:
            names |= set(
                asset.interfaces.exclude(source=Source.MANUAL).values_list("name", flat=True)
            )
        for index, row in enumerate(network["ip_addresses"]):
            name = row.get("interface_name")
            if name and name not in names:
                errors[f"ip_addresses.{index}.interface_name"] = [
                    "No interface with this name on the asset."
                ]
    if errors:
        raise serializers.ValidationError(errors)


def _apply_network(asset: Asset, network: dict) -> None:
    """Replace the asset's manual identifiers. Discovered rows are never touched."""
    if network.get("interfaces") is not None:
        wanted = {row["name"]: row.get("mac_address", "") for row in network["interfaces"]}
        manual = asset.interfaces.filter(source=Source.MANUAL)
        manual.exclude(name__in=wanted).delete()
        existing = {i.name: i for i in manual}
        for name, mac in wanted.items():
            if name in existing:
                if existing[name].mac_address != mac:
                    existing[name].mac_address = mac
                    existing[name].save(update_fields=["mac_address"])
            else:
                AssetInterface.objects.create(asset=asset, name=name, mac_address=mac)

    if network.get("hostnames") is not None:
        asset.hostnames.filter(source=Source.MANUAL).delete()
        AssetHostname.objects.bulk_create(
            AssetHostname(
                asset=asset, hostname=row["hostname"], is_primary=row.get("is_primary", False)
            )
            for row in network["hostnames"]
        )

    if network.get("ip_addresses") is not None:
        interfaces = {}
        for interface in asset.interfaces.order_by("source"):  # "manual" wins on name clash
            interfaces.setdefault(interface.name, interface)
            if interface.source == Source.MANUAL:
                interfaces[interface.name] = interface
        asset.ip_addresses.filter(source=Source.MANUAL).delete()
        AssetIPAddress.objects.bulk_create(
            AssetIPAddress(
                asset=asset,
                address=row["address"],
                interface=interfaces.get(row.get("interface_name") or ""),
                is_primary=row.get("is_primary", False),
            )
            for row in network["ip_addresses"]
        )


# --- Field-level authority (ASM-09) -----------------------------------------

EDIT = "assets.edit"
EDIT_TECHNICAL = "assets.edit_technical"


def _field_denied(fields: dict) -> ApiError:
    return ApiError(
        "FIELD_PERMISSION_DENIED",
        "You do not have permission to change some of these fields.",
        status.HTTP_403_FORBIDDEN,
        fields,
    )


def check_field_permissions(request, asset: Asset, data: dict, custom_changed: bool) -> list[str]:
    """Business fields need assets.edit. Technical fields need assets.edit_technical
    once a discovery source has supplied them; values that were only ever entered
    manually stay editable by assets.edit. Returns the technical fields changed."""
    granted = request.user.permission_codes()
    technical = [f for f in TECHNICAL_FIELDS if f in data and data[f] != getattr(asset, f)]
    business = [
        f
        for f in data
        if f not in TECHNICAL_FIELDS and f not in NETWORK_KEYS and data[f] != getattr(asset, f)
    ]
    if custom_changed:
        business.append("custom_fields")
    denied = {}
    if business and EDIT not in granted:
        for field in business:
            denied[field] = ["Business fields require the asset edit permission."]
    if technical and EDIT_TECHNICAL not in granted:
        discovered = set(
            FieldProvenance.objects.filter(
                asset=asset, field__in=technical, kind=FieldProvenance.Kind.DISCOVERY
            ).values_list("field", flat=True)
        )
        for field in technical:
            if field in discovered or EDIT not in granted:
                denied[field] = [
                    "This value comes from a discovery source; "
                    "changing it needs technical edit rights."
                ]
    if denied:
        raise _field_denied(denied)
    return technical


def record_manual_values(request, asset: Asset, fields, reason: str) -> None:
    """A manual technical value is approved: record provenance and lock it so
    discovery cannot overwrite it silently."""
    for field in fields:
        FieldProvenance.objects.update_or_create(
            asset=asset,
            field=field,
            defaults={
                "kind": FieldProvenance.Kind.MANUAL,
                "instance": None,
                "observation": None,
                "value": getattr(asset, field) or "",
                "observed_at": None,
                "recorded_by": request.user,
            },
        )
        if getattr(asset, field):
            FieldLock.objects.get_or_create(
                asset=asset, field=field, defaults={"locked_by": request.user, "reason": reason}
            )
        else:
            FieldLock.objects.filter(asset=asset, field=field).delete()


# --- Assets -------------------------------------------------------------------


def _check_assignable(data: dict, current: Asset | None = None) -> None:
    """New assignments must reference active records; unchanged ones may stay inactive."""
    errors = {}
    for field, label in (("site", "site"), ("location", "location"), ("department", "department")):
        value = data.get(field)
        if value is not None and not value.is_active:
            if current is None or getattr(current, f"{field}_id") != value.pk:
                errors[field] = [f"This {label} is inactive."]
    owner = data.get("owner")
    if owner is not None and not owner.is_active:
        if current is None or current.owner_id != owner.pk:
            errors["owner"] = ["This user is disabled."]
    site = data.get("site", current.site if current else None)
    location = data["location"] if "location" in data else (current.location if current else None)
    if location is not None and site is not None and location.site_id != site.pk:
        errors["location"] = ["The location must belong to the selected site."]
    if errors:
        raise serializers.ValidationError(errors)


def create_asset(request, data: dict) -> Asset:
    data = dict(data)
    network = {key: data.pop(key) for key in NETWORK_KEYS if key in data}
    incoming_custom = data.pop("custom_fields", None)
    category: AssetCategory = data["category"]
    if not category.is_active:
        raise serializers.ValidationError({"category": ["This category is inactive."]})
    _check_assignable(data)
    _validate_network(None, network)
    tree = CategoryTree()
    definitions = cf.applicable_definitions(category.pk, tree)
    values = cf.validate_values(definitions, incoming_custom, {}, enforce_required=True)

    with transaction.atomic():
        asset = Asset(
            **data, custom_fields=values, created_by=request.user, modified_by=request.user
        )
        _save(asset)
        _apply_network(asset, network)
        record_manual_values(
            request,
            asset,
            [f for f in TECHNICAL_FIELDS if getattr(asset, f)],
            "Entered at registration",
        )
        after = snapshot(asset, tree)
        changes = {
            key: {"before": None, "after": value}
            for key, value in after.items()
            if value not in (None, "", [], {}, False)
        }
        _record(
            request,
            asset,
            AssetHistoryEntry.ChangeType.CREATED,
            changes,
            after=after,
            action="assets.create",
        )
    return asset


def update_asset(request, asset: Asset, data: dict, expected_version: int | None) -> Asset:
    data = dict(data)
    network = {key: data.pop(key) for key in NETWORK_KEYS if key in data}
    incoming_custom = data.pop("custom_fields", None)

    with transaction.atomic():
        asset = _locked(asset, expected_version)
        _check_assignable(data, asset)
        _validate_network(asset, network)
        tree = CategoryTree()
        before = snapshot(asset, tree)

        new_custom = None
        if incoming_custom is not None:
            definitions = cf.applicable_definitions(asset.category_id, tree)
            new_custom = cf.validate_values(
                definitions, incoming_custom, asset.custom_fields, enforce_required=False
            )
        technical_changed = check_field_permissions(
            request, asset, data, new_custom is not None and new_custom != asset.custom_fields
        )
        for field, value in data.items():
            setattr(asset, field, value)
        if new_custom is not None:
            asset.custom_fields = new_custom
        _apply_network(asset, network)
        after = snapshot(asset, tree)
        changes = diff(before, after)
        if not changes:
            return asset
        asset.version = F("version") + 1
        asset.modified_by = request.user
        _save(asset)
        asset.refresh_from_db()
        record_manual_values(request, asset, technical_changed, "Manual edit")

        reassigned = bool(REASSIGNMENT_FIELDS & set(changes))
        change_type = (
            AssetHistoryEntry.ChangeType.REASSIGNED
            if reassigned
            else AssetHistoryEntry.ChangeType.UPDATED
        )
        _record(
            request,
            asset,
            change_type,
            changes,
            action="assets.reassign" if reassigned else "assets.update",
            before={k: v["before"] for k, v in changes.items()},
            after={k: v["after"] for k, v in changes.items()},
        )
    return asset


def classification_impact(asset: Asset, category: AssetCategory, incoming_custom=None) -> dict:
    tree = CategoryTree()
    old = cf.applicable_definitions(asset.category_id, tree)
    new = cf.applicable_definitions(category.pk, tree)
    old_keys, new_keys = {d.key for d in old}, {d.key for d in new}
    values = {**asset.custom_fields, **(incoming_custom or {})}
    return {
        "from_category": tree.path(asset.category_id),
        "to_category": tree.path(category.pk),
        "fields_added": [
            {"key": d.key, "label": d.label, "required": d.required}
            for d in new
            if d.key not in old_keys
        ],
        "fields_kept": sorted(old_keys & new_keys),
        "values_retained_read_only": sorted(k for k in asset.custom_fields if k not in new_keys),
        "required_missing": cf.missing_required(new, values),
    }


def reclassify(
    request, asset: Asset, category: AssetCategory, reason: str, incoming_custom, expected_version
) -> Asset:
    if not category.is_active:
        raise serializers.ValidationError({"category": ["This category is inactive."]})
    with transaction.atomic():
        asset = _locked(asset, expected_version)
        if asset.category_id == category.pk:
            raise serializers.ValidationError(
                {"category": ["The asset is already in this category."]}
            )
        tree = CategoryTree()
        before = snapshot(asset, tree)
        definitions = cf.applicable_definitions(category.pk, tree)
        asset.custom_fields = cf.validate_values(
            definitions, incoming_custom, asset.custom_fields, enforce_required=True
        )
        asset.category = category
        asset.version = F("version") + 1
        asset.modified_by = request.user
        _save(asset)
        asset.refresh_from_db()
        changes = diff(before, snapshot(asset, tree))
        _record(
            request,
            asset,
            AssetHistoryEntry.ChangeType.RECLASSIFIED,
            changes,
            reason=reason,
            before={k: v["before"] for k, v in changes.items()},
            after={k: v["after"] for k, v in changes.items()},
            action="assets.reclassify",
        )
        asset_reclassified.send(sender=Asset, asset=asset, request=request, reason=reason)
    return asset


def archive(request, asset: Asset, reason: str, expected_version) -> Asset:
    with transaction.atomic():
        asset = _locked(asset, expected_version)
        asset.archived_at = timezone.now()
        asset.archived_by = request.user
        asset.archive_reason = reason
        asset.version = F("version") + 1
        asset.modified_by = request.user
        _save(asset)
        asset.refresh_from_db()
        _record(
            request,
            asset,
            AssetHistoryEntry.ChangeType.ARCHIVED,
            {"archived": {"before": False, "after": True}},
            reason=reason,
            action="assets.archive",
        )
    return asset


def restore(request, asset: Asset, expected_version) -> Asset:
    with transaction.atomic():
        asset = _locked(asset, expected_version, allow_archived=True)
        if asset.archived_at is None:
            raise ApiError("NOT_ARCHIVED", "This asset is not archived.", status.HTTP_409_CONFLICT)
        if not asset.site.is_active:
            raise ApiError(
                "SITE_INACTIVE",
                "The asset's site is inactive. Reactivate the site first.",
                status.HTTP_409_CONFLICT,
            )
        asset.archived_at = None
        asset.archived_by = None
        asset.archive_reason = ""
        asset.version = F("version") + 1
        asset.modified_by = request.user
        _save(asset)
        asset.refresh_from_db()
        _record(
            request,
            asset,
            AssetHistoryEntry.ChangeType.RESTORED,
            {"archived": {"before": True, "after": False}},
            action="assets.restore",
        )
    return asset


# --- Categories ---------------------------------------------------------------

CATEGORY_FIELDS = ("code", "name", "parent", "description", "is_active", "sort_order")


def _category_snapshot(category) -> dict:
    return {
        field: (
            str(getattr(category, field))
            if field == "parent" and category.parent_id
            else getattr(category, field)
        )
        for field in CATEGORY_FIELDS
    }


def _validate_category_parent(category: AssetCategory | None, parent: AssetCategory | None) -> None:
    if parent is None:
        return
    tree = CategoryTree()
    if category is not None and parent.pk in tree.descendants(category.pk):
        raise serializers.ValidationError({"parent": ["A category cannot be moved under itself."]})
    subtree_height = 0
    if category is not None:
        subtree_height = max(
            tree.depth(d) - tree.depth(category.pk) for d in tree.descendants(category.pk)
        )
    if tree.depth(parent.pk) + 1 + subtree_height >= MAX_CATEGORY_DEPTH:
        raise serializers.ValidationError(
            {"parent": [f"Categories can be at most {MAX_CATEGORY_DEPTH} levels deep."]}
        )


def _unique_code(name: str, parent: AssetCategory | None) -> str:
    base = slugify(f"{parent.code}-{name}" if parent else name)[:60] or "category"
    code, n = base, 2
    while AssetCategory.objects.filter(code=code).exists():
        code, n = f"{base[:57]}-{n}", n + 1
    return code


def create_category(request, data: dict) -> AssetCategory:
    parent = data.get("parent")
    _validate_category_parent(None, parent)
    data = dict(data)
    data["code"] = data.get("code") or _unique_code(data["name"], parent)
    with transaction.atomic():
        category = AssetCategory.objects.create(**data)
        audit.record(
            action="categories.create",
            actor=request.user,
            request=request,
            object_type="asset_category",
            object_id=category.pk,
            object_label=category.name,
            after=_category_snapshot(category),
        )
    return category


def update_category(
    request, category: AssetCategory, changes: dict, expected_version
) -> AssetCategory:
    with transaction.atomic():
        category = AssetCategory.objects.select_for_update().get(pk=category.pk)
        check_version(category, expected_version)
        if "parent" in changes:
            _validate_category_parent(category, changes["parent"])
        before = _category_snapshot(category)
        for field, value in changes.items():
            setattr(category, field, value)
        after = _category_snapshot(category)
        if after == before:
            return category
        category.version = F("version") + 1
        category.save()
        category.refresh_from_db()
        action = "categories.move" if before["parent"] != after["parent"] else "categories.update"
        audit.record(
            action=action,
            actor=request.user,
            request=request,
            object_type="asset_category",
            object_id=category.pk,
            object_label=category.name,
            before=before,
            after=after,
        )
    return category


# --- Custom field definitions -------------------------------------------------

FIELD_FIELDS = (
    "key",
    "label",
    "field_type",
    "required",
    "choices",
    "help_text",
    "min_value",
    "max_value",
    "max_length",
    "sort_order",
    "is_active",
)


def _field_snapshot(definition) -> dict:
    out = {}
    for field in FIELD_FIELDS:
        value = getattr(definition, field)
        out[field] = (
            str(value) if field in ("min_value", "max_value") and value is not None else value
        )
    return out


def _validate_field_settings(field_type: str, settings: dict) -> None:
    errors = {}
    choices = settings.get("choices") or []
    if field_type == CustomFieldDefinition.FieldType.CHOICE:
        if not choices:
            errors["choices"] = ["Add at least one choice."]
        elif len(set(choices)) != len(choices) or any(not str(c).strip() for c in choices):
            errors["choices"] = ["Choices must be unique and non-empty."]
    elif choices:
        errors["choices"] = ["Choices apply only to choice fields."]
    numeric = field_type in (
        CustomFieldDefinition.FieldType.INTEGER,
        CustomFieldDefinition.FieldType.DECIMAL,
    )
    if not numeric and (
        settings.get("min_value") is not None or settings.get("max_value") is not None
    ):
        errors["min_value"] = ["Minimum and maximum apply only to number fields."]
    if (
        settings.get("min_value") is not None
        and settings.get("max_value") is not None
        and settings["min_value"] > settings["max_value"]
    ):
        errors["max_value"] = ["Maximum must be greater than or equal to minimum."]
    text = field_type in (
        CustomFieldDefinition.FieldType.TEXT,
        CustomFieldDefinition.FieldType.LONG_TEXT,
    )
    if settings.get("max_length") is not None and not text:
        errors["max_length"] = ["Maximum length applies only to text fields."]
    if errors:
        raise serializers.ValidationError(errors)


def create_field(request, category: AssetCategory, data: dict) -> CustomFieldDefinition:
    tree = CategoryTree()
    related = set(tree.lineage(category.pk)) | tree.descendants(category.pk)
    if CustomFieldDefinition.objects.filter(category_id__in=related, key=data["key"]).exists():
        raise serializers.ValidationError(
            {
                "key": [
                    "A field with this key already applies to this category, a parent or a child."
                ]
            }
        )
    _validate_field_settings(data["field_type"], data)
    with transaction.atomic():
        definition = CustomFieldDefinition.objects.create(category=category, **data)
        audit.record(
            action="custom_fields.create",
            actor=request.user,
            request=request,
            object_type="custom_field",
            object_id=definition.pk,
            object_label=f"{category.code}.{definition.key}",
            after=_field_snapshot(definition),
        )
    return definition


def update_field(
    request, definition: CustomFieldDefinition, changes: dict, expected_version
) -> CustomFieldDefinition:
    with transaction.atomic():
        definition = CustomFieldDefinition.objects.select_for_update().get(pk=definition.pk)
        check_version(definition, expected_version)
        before = _field_snapshot(definition)
        merged = {**before, **changes}
        merged["min_value"] = changes.get("min_value", definition.min_value)
        merged["max_value"] = changes.get("max_value", definition.max_value)
        _validate_field_settings(definition.field_type, merged)
        for field, value in changes.items():
            setattr(definition, field, value)
        after = _field_snapshot(definition)
        if after == before:
            return definition
        definition.version = F("version") + 1
        definition.save()
        definition.refresh_from_db()
        audit.record(
            action="custom_fields.update",
            actor=request.user,
            request=request,
            object_type="custom_field",
            object_id=definition.pk,
            object_label=f"{definition.category.code}.{definition.key}",
            before=before,
            after=after,
        )
    return definition
