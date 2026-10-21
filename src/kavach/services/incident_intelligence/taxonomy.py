"""Allowed category / incident-type taxonomy. Unknown values degrade to OTHER / UNKNOWN, never invented."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from kavach.schemas.incident_intelligence import Category, IncidentType

TAXONOMY_VERSION = "tax-1.0"

TAXONOMY: dict[Category, tuple[IncidentType, ...]] = {
    Category.SANITATION: (IncidentType.WASTE_OVERFLOW, IncidentType.DIRTY_PUBLIC_TOILET, IncidentType.LITTERING),
    Category.ELECTRICAL: (IncidentType.BROKEN_STREETLIGHT, IncidentType.EXPOSED_WIRING),
    Category.WATER_SUPPLY: (IncidentType.BROKEN_PIPE, IncidentType.WATER_LEAKAGE),
    Category.MAINTENANCE: (IncidentType.DAMAGED_BENCH, IncidentType.ROAD_DAMAGE),
    Category.PUBLIC_SAFETY: (IncidentType.CROWD_CONGESTION, IncidentType.FIRE_HAZARD),
    Category.OTHER: (),
}

_TYPE_TO_CATEGORY = {t: c for c, types in TAXONOMY.items() for t in types}


@dataclass
class TaxonomyResult:
    category: Category
    incident_type: IncidentType
    notes: list[str] = field(default_factory=list)  # e.g. UNKNOWN_CATEGORY, CATEGORY_TYPE_MISMATCH

    @property
    def is_uncertain(self) -> bool:
        return self.category == Category.OTHER or self.incident_type == IncidentType.UNKNOWN


def _norm(raw: str | None) -> str:
    return re.sub(r"[\s\-/]+", "_", (raw or "").strip().upper())


def normalize_taxonomy(raw_category: str | None, raw_type: str | None) -> TaxonomyResult:
    notes: list[str] = []
    cat = next((c for c in Category if c.value == _norm(raw_category)), None)
    typ = next((t for t in IncidentType if t.value == _norm(raw_type) and t != IncidentType.UNKNOWN), None)

    if typ is not None:
        parent = _TYPE_TO_CATEGORY[typ]
        if cat is not None and cat != parent:
            notes.append("CATEGORY_TYPE_MISMATCH")  # trust the more specific incident type
        return TaxonomyResult(parent, typ, notes)
    if cat is not None and cat != Category.OTHER:
        notes.append("UNKNOWN_INCIDENT_TYPE")
        return TaxonomyResult(cat, IncidentType.UNKNOWN, notes)
    notes.append("UNKNOWN_CATEGORY")
    return TaxonomyResult(Category.OTHER, IncidentType.UNKNOWN, notes)


def render_taxonomy_for_prompt() -> str:
    lines = [f"- {c.value}: {', '.join(t.value for t in types) or '(use incident_type UNKNOWN)'}"
             for c, types in TAXONOMY.items()]
    return "\n".join(lines)
