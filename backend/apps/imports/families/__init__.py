"""Import families (docs/11 template table). Families not listed here (domains, TLS
endpoints, relationships, manufacturers/models, categories) arrive with the tasks that
create those entities."""

from .assets import AssetFamily
from .base import Column, Context, Family, Plan, RowError
from .licenses import EntitlementFamily
from .others import GroupFamily, LocationFamily, MembershipFamily

FAMILIES: dict[str, Family] = {
    f.code: f
    for f in (
        AssetFamily(),
        LocationFamily(),
        GroupFamily(),
        MembershipFamily(),
        EntitlementFamily(),
    )
}

__all__ = ["FAMILIES", "Column", "Context", "Family", "Plan", "RowError"]
