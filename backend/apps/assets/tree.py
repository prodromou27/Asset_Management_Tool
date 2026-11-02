"""In-memory category tree. The table is small; load once per request."""

from collections import defaultdict
from uuid import UUID

from .models import AssetCategory


class CategoryTree:
    def __init__(self, categories=None):
        rows = list(categories if categories is not None else AssetCategory.objects.all())
        self.by_id: dict[UUID, AssetCategory] = {row.pk: row for row in rows}
        self.children: dict[UUID | None, list[UUID]] = defaultdict(list)
        for row in rows:
            self.children[row.parent_id].append(row.pk)

    def ancestors(self, category_id: UUID) -> list[UUID]:
        """Root first, excluding the category itself."""
        chain = []
        seen = {category_id}
        node = self.by_id.get(category_id)
        while node is not None and node.parent_id is not None and node.parent_id not in seen:
            chain.append(node.parent_id)
            seen.add(node.parent_id)
            node = self.by_id.get(node.parent_id)
        return list(reversed(chain))

    def lineage(self, category_id: UUID) -> list[UUID]:
        return [*self.ancestors(category_id), category_id]

    def descendants(self, category_id: UUID) -> set[UUID]:
        result: set[UUID] = set()
        stack = [category_id]
        while stack:
            current = stack.pop()
            if current in result:
                continue
            result.add(current)
            stack.extend(self.children.get(current, []))
        return result

    def path(self, category_id: UUID) -> str:
        return " / ".join(self.by_id[cid].name for cid in self.lineage(category_id))

    def depth(self, category_id: UUID) -> int:
        return len(self.ancestors(category_id))
