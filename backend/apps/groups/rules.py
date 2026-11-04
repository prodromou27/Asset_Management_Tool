"""Dynamic group rules: a validated JSON tree compiled to parameterised ORM conditions.

Grammar (docs/03): operators eq, in, contains, before, after; combinators and, or, not.

    node      := group | negation | condition
    group     := {"op": "and" | "or", "rules": [node, ...]}        (1..20 children)
    negation  := {"op": "not", "rule": node}
    condition := {"field": <field>, "operator": <operator>, "value": <value>}

Only fields in ``FIELDS`` are accepted, each with its own operators and value type. Values
are bound as ORM parameters, never interpolated; nothing from the browser is executed.
Limits: depth 5, 50 nodes, 100 values per ``in``, 200 characters per string.
``eq`` with ``null`` means "not set" (for example no owner).
"""

from dataclasses import dataclass
from datetime import date
from uuid import UUID

from django.db.models import Exists, OuterRef, Q

from apps.assets.models import Asset, AssetHostname
from apps.assets.tree import CategoryTree
from apps.organizations import scope

MAX_DEPTH = 5
MAX_NODES = 50
MAX_CHILDREN = 20
MAX_IN = 100
MAX_TEXT = 200


class RuleError(ValueError):
    def __init__(self, path: str, message: str):
        super().__init__(f"{path}: {message}")
        self.path = path
        self.message = message


@dataclass(frozen=True)
class Field:
    label: str
    kind: str  # text | enum | ref | date
    operators: tuple[str, ...]
    choices: tuple[tuple[str, str], ...] = ()
    ref: str = ""  # what a ref points at (for the editor's pickers)


TEXT_OPS = ("eq", "contains", "in")
FIELDS: dict[str, Field] = {
    "name": Field("Name", "text", TEXT_OPS),
    "asset_tag": Field("Asset tag", "text", TEXT_OPS),
    "hostname": Field("Hostname", "text", ("eq", "contains")),
    "manufacturer": Field("Manufacturer", "text", TEXT_OPS),
    "model": Field("Model", "text", TEXT_OPS),
    "serial_number": Field("Serial number", "text", TEXT_OPS),
    "os_name": Field("Operating system", "text", TEXT_OPS),
    "os_version": Field("OS version", "text", TEXT_OPS),
    "firmware_version": Field("Firmware", "text", TEXT_OPS),
    "category": Field("Category (including subcategories)", "ref", ("eq", "in"), ref="category"),
    "site": Field("Site (including child sites)", "ref", ("eq", "in"), ref="site"),
    "location": Field("Location", "ref", ("eq", "in"), ref="location"),
    "department": Field("Department", "ref", ("eq", "in"), ref="department"),
    "owner": Field("Owner", "ref", ("eq", "in"), ref="user"),
    "source": Field("Reported by integration", "ref", ("eq", "in"), ref="integration"),
    "member_of": Field("Member of group", "ref", ("eq", "in"), ref="group"),
    "business_status": Field(
        "Business status", "enum", ("eq", "in"), tuple(Asset.BusinessStatus.choices)
    ),
    "support_status": Field(
        "Support status", "enum", ("eq", "in"), tuple(Asset.SupportStatus.choices)
    ),
    "observation_status": Field(
        "Observation status", "enum", ("eq", "in"), tuple(Asset.ObservationStatus.choices)
    ),
    "created_at": Field("Registered", "date", ("before", "after")),
    "last_seen": Field("Last reported by any source", "date", ("before", "after")),
}
NULLABLE_REFS = {"location", "department", "owner"}


# --- Validation ---------------------------------------------------------------------------


def _uuid(value, path) -> str:
    try:
        return str(UUID(str(value)))
    except (ValueError, TypeError) as exc:
        raise RuleError(path, "Expected an ID.") from exc


def _scalar(field_name: str, field: Field, value, path: str):
    if field.kind == "text":
        if not isinstance(value, str) or len(value) > MAX_TEXT:
            raise RuleError(path, f"Expected text up to {MAX_TEXT} characters.")
        return value.strip()
    if field.kind == "enum":
        allowed = {c[0] for c in field.choices}
        if value not in allowed:
            raise RuleError(path, f"Expected one of {', '.join(sorted(allowed))}.")
        return value
    if field.kind == "ref":
        if value is None and field_name in NULLABLE_REFS:
            return None
        return _uuid(value, path)
    raise RuleError(path, "Unsupported value.")


def _validate(node, path: str, depth: int, counter: list[int]) -> dict:
    counter[0] += 1
    if counter[0] > MAX_NODES:
        raise RuleError(path, f"A rule may have at most {MAX_NODES} parts.")
    if depth > MAX_DEPTH:
        raise RuleError(path, f"Rules may be nested at most {MAX_DEPTH} levels deep.")
    if not isinstance(node, dict):
        raise RuleError(path, "Expected an object.")
    op = node.get("op")
    if op in ("and", "or"):
        children = node.get("rules")
        if not isinstance(children, list) or not 1 <= len(children) <= MAX_CHILDREN:
            raise RuleError(path, f"'{op}' needs 1 to {MAX_CHILDREN} rules.")
        return {
            "op": op,
            "rules": [
                _validate(child, f"{path}.rules[{n}]", depth + 1, counter)
                for n, child in enumerate(children)
            ],
        }
    if op == "not":
        return {
            "op": "not",
            "rule": _validate(node.get("rule"), f"{path}.rule", depth + 1, counter),
        }
    if op is not None:
        raise RuleError(path, f"Unknown combinator {op!r}.")

    name = node.get("field")
    field = FIELDS.get(name)
    if field is None:
        raise RuleError(path, f"Unknown field {name!r}.")
    operator = node.get("operator")
    if operator not in field.operators:
        raise RuleError(path, f"{field.label} supports {', '.join(field.operators)}.")
    value = node.get("value")
    vpath = f"{path}.value"
    if field.kind == "date":
        try:
            value = date.fromisoformat(str(value)).isoformat()
        except ValueError as exc:
            raise RuleError(vpath, "Expected a date (YYYY-MM-DD).") from exc
    elif operator == "in":
        if not isinstance(value, list) or not 1 <= len(value) <= MAX_IN:
            raise RuleError(vpath, f"Expected a list of 1 to {MAX_IN} values.")
        value = [_scalar(name, field, v, f"{vpath}[{n}]") for n, v in enumerate(value)]
    elif value is None and operator == "eq" and field.kind == "text":
        value = ""
    else:
        value = _scalar(name, field, value, vpath)
    return {"field": name, "operator": operator, "value": value}


def validate(rule) -> dict:
    """Return a normalised copy of the rule or raise RuleError."""
    return _validate(rule, "rule", 1, [0])


def referenced_groups(rule: dict) -> set[str]:
    out: set[str] = set()
    if not rule:
        return out
    if rule.get("op") in ("and", "or"):
        for child in rule["rules"]:
            out |= referenced_groups(child)
    elif rule.get("op") == "not":
        out |= referenced_groups(rule["rule"])
    elif rule.get("field") == "member_of":
        value = rule["value"]
        out |= set(value if isinstance(value, list) else [value])
    return out


# --- Compilation --------------------------------------------------------------------------


class _Compiler:
    def __init__(self):
        self._tree: CategoryTree | None = None

    @property
    def tree(self) -> CategoryTree:
        if self._tree is None:
            self._tree = CategoryTree()
        return self._tree

    def node(self, node: dict) -> Q:
        op = node.get("op")
        if op == "and":
            q = Q()
            for child in node["rules"]:
                q &= self.node(child)
            return q
        if op == "or":
            q = Q(pk__in=[])
            for child in node["rules"]:
                q |= self.node(child)
            return q
        if op == "not":
            return ~self.node(node["rule"])
        return self.condition(node["field"], node["operator"], node["value"])

    def condition(self, name: str, operator: str, value) -> Q:
        values = value if operator == "in" else [value]
        field = FIELDS[name]
        if name == "hostname":
            lookup = "hostname__icontains" if operator == "contains" else "hostname__iexact"
            return Q(
                Exists(
                    AssetHostname.objects.filter(asset=OuterRef("pk"), **{lookup: value.lower()})
                )
            )
        if field.kind == "text":
            if operator == "contains":
                return Q(**{f"{name}__icontains": value})
            q = Q(pk__in=[])
            for v in values:
                q |= Q(**{name: ""}) if v == "" else Q(**{f"{name}__iexact": v})
            return q
        if field.kind == "enum":
            return Q(**{f"{name}__in": values})
        if field.kind == "date":
            day = date.fromisoformat(value)
            if name == "created_at":
                lookup = "created_at__date__lt" if operator == "before" else "created_at__date__gt"
                return Q(**{lookup: day})
            return self._last_seen(operator, day)
        return self.reference(name, values)

    def reference(self, name: str, values: list) -> Q:
        ids = [UUID(v) for v in values if v is not None]
        q = Q(pk__in=[])
        if None in values:
            q |= Q(**{f"{name}__isnull": True})
        if name == "category":
            subtree: set = set()
            for cid in ids:
                subtree |= self.tree.descendants(cid)
            return q | Q(category_id__in=subtree)
        if name == "site":
            return q | Q(site_id__in=scope.descendants(set(ids)))
        if name in ("location", "department", "owner"):
            return q | Q(**{f"{name}_id__in": ids})
        if name == "source":
            from apps.reconciliation.models import SourceLink

            return q | Q(
                Exists(
                    SourceLink.objects.filter(asset=OuterRef("pk"), instance_id__in=ids).exclude(
                        status=SourceLink.Status.UNLINKED
                    )
                )
            )
        if name == "member_of":
            from .models import AssetGroupMembership

            return q | Q(
                Exists(
                    AssetGroupMembership.objects.filter(
                        asset=OuterRef("pk"), group_id__in=ids, removed_at__isnull=True
                    )
                )
            )
        raise RuleError(name, "Unsupported field.")

    @staticmethod
    def _last_seen(operator: str, day: date) -> Q:
        from apps.reconciliation.models import SourceLink

        links = SourceLink.objects.filter(asset=OuterRef("pk")).exclude(
            status=SourceLink.Status.UNLINKED
        )
        if operator == "after":
            return Q(Exists(links.filter(last_seen_at__date__gt=day)))
        # before: has source links, and none reported on or after the day
        return Q(Exists(links)) & ~Q(Exists(links.filter(last_seen_at__date__gte=day)))


def compile_rule(rule: dict) -> Q:
    """Q for live (non-archived) assets matching a validated rule."""
    return Q(archived_at__isnull=True) & _Compiler().node(rule)


def field_catalogue() -> list[dict]:
    return [
        {
            "field": name,
            "label": f.label,
            "kind": f.kind,
            "operators": list(f.operators),
            "choices": [{"value": v, "label": label} for v, label in f.choices],
            "ref": f.ref,
            "nullable": name in NULLABLE_REFS or f.kind == "text",
        }
        for name, f in FIELDS.items()
    ]
