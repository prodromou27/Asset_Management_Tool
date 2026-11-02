"""Typed validation of category custom field values (stored in Asset.custom_fields).

Rules:
- Applicable definitions = active definitions on the category and its ancestors.
- Writes use merge semantics: keys sent are set (null clears); others are kept.
- Values for keys that no longer apply (e.g. after reclassification) are retained
  read-only and never dropped, per docs/03 "never drop business fields".
- Required fields are enforced on create and reclassification. On ordinary edits
  only fields being written are checked, so a newly required field does not block
  unrelated changes; the detail view reports `missing_required_fields`.
"""

from datetime import date
from decimal import Decimal, InvalidOperation

from rest_framework import serializers

from .models import CustomFieldDefinition
from .tree import CategoryTree

FieldType = CustomFieldDefinition.FieldType
DEFAULT_MAX_LENGTH = {FieldType.TEXT: 255, FieldType.LONG_TEXT: 5000}


def applicable_definitions(category_id, tree: CategoryTree | None = None):
    tree = tree or CategoryTree()
    return list(
        CustomFieldDefinition.objects.filter(
            category_id__in=tree.lineage(category_id), is_active=True
        ).order_by("sort_order", "label")
    )


def _is_empty(value) -> bool:
    return value is None or (isinstance(value, str) and value.strip() == "")


def coerce(definition: CustomFieldDefinition, value):
    """Return the canonical JSON value or raise ValueError with a user message."""
    kind = definition.field_type
    if kind in (FieldType.TEXT, FieldType.LONG_TEXT):
        if not isinstance(value, str):
            raise ValueError("Enter text.")
        value = value.strip()
        limit = definition.max_length or DEFAULT_MAX_LENGTH[kind]
        if len(value) > limit:
            raise ValueError(f"Use at most {limit} characters.")
        return value
    if kind == FieldType.INTEGER:
        if isinstance(value, bool) or not isinstance(value, (int, str)):
            raise ValueError("Enter a whole number.")
        try:
            number = int(str(value).strip())
        except ValueError as exc:
            raise ValueError("Enter a whole number.") from exc
        _check_range(definition, Decimal(number))
        return number
    if kind == FieldType.DECIMAL:
        if isinstance(value, bool) or not isinstance(value, (int, float, str)):
            raise ValueError("Enter a number.")
        try:
            number = Decimal(str(value).strip())
        except InvalidOperation as exc:
            raise ValueError("Enter a number.") from exc
        if not number.is_finite():
            raise ValueError("Enter a number.")
        _check_range(definition, number)
        return str(number)  # string keeps precision in JSON
    if kind == FieldType.BOOLEAN:
        if not isinstance(value, bool):
            raise ValueError("Choose yes or no.")
        return value
    if kind == FieldType.DATE:
        try:
            return date.fromisoformat(str(value)).isoformat()
        except ValueError as exc:
            raise ValueError("Enter a date as YYYY-MM-DD.") from exc
    if kind == FieldType.CHOICE:
        if value not in definition.choices:
            raise ValueError(f"Choose one of: {', '.join(map(str, definition.choices))}.")
        return value
    raise ValueError("Unsupported field type.")


def _check_range(definition, number: Decimal) -> None:
    if definition.min_value is not None and number < definition.min_value:
        raise ValueError(f"Must be at least {definition.min_value.normalize()}.")
    if definition.max_value is not None and number > definition.max_value:
        raise ValueError(f"Must be at most {definition.max_value.normalize()}.")


def validate_values(
    definitions: list[CustomFieldDefinition],
    incoming: dict | None,
    existing: dict,
    *,
    enforce_required: bool,
) -> dict:
    """Merge `incoming` into `existing`; raise ValidationError keyed custom_fields.<key>."""
    if incoming is not None and not isinstance(incoming, dict):
        raise serializers.ValidationError(
            {"custom_fields": ["Expected an object of field values."]}
        )
    by_key = {definition.key: definition for definition in definitions}
    merged = dict(existing)
    errors: dict[str, list[str]] = {}

    for key, value in (incoming or {}).items():
        definition = by_key.get(key)
        if definition is None:
            errors[f"custom_fields.{key}"] = ["This field does not apply to the asset's category."]
            continue
        if _is_empty(value):
            merged.pop(key, None)
            continue
        try:
            merged[key] = coerce(definition, value)
        except ValueError as exc:
            errors[f"custom_fields.{key}"] = [str(exc)]

    if enforce_required:
        for definition in definitions:
            if definition.required and _is_empty(merged.get(definition.key)):
                errors.setdefault(f"custom_fields.{definition.key}", []).append(
                    f"{definition.label} is required."
                )

    if errors:
        raise serializers.ValidationError(errors)
    return merged


def missing_required(definitions, values: dict) -> list[str]:
    return [d.key for d in definitions if d.required and _is_empty(values.get(d.key))]


def retained_keys(definitions, values: dict) -> list[str]:
    applicable = {d.key for d in definitions}
    return sorted(key for key in values if key not in applicable)
