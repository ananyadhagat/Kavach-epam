"""Civic incident categories, loaded from JSON so a new category needs no code
change. Every category uses the same incident model and the same location
verification; only wording and worker instructions differ."""

import json
from pathlib import Path


class CategoryRegistry:
    def __init__(self, items: list[dict]) -> None:
        ids = [c["id"] for c in items]
        if len(set(ids)) != len(ids):
            raise ValueError("Duplicate category id")
        if "other" not in ids:
            raise ValueError("An 'other' category is required")
        self.items = items
        self._by_id = {c["id"]: c for c in items}

    def get(self, category_id: str) -> dict | None:
        return self._by_id.get(category_id)

    def label(self, category_id: str) -> str:
        return (self._by_id.get(category_id) or {}).get("label", category_id)


def load_categories(path: Path) -> CategoryRegistry:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    return CategoryRegistry(raw["categories"])
