"""Core comparison algorithms for the Duplicate Detection Agent (Phase 3).

Each comparator evaluates one piece of evidence between a new complaint and an
existing candidate complaint and returns a shared
:class:`~app.schemas.duplicate_response.SignalResult`. Comparators are advisory
and never decide the final outcome; the weighted scoring engine and decision
policy live in Phase 4 (``app/scoring/``).
"""

from app.comparators.base import (
    Comparator,
    available_signal,
    clamp_unit_score,
    error_signal,
    invalid_signal,
    unavailable_signal,
)
from app.comparators.category_comparator import CategoryComparator
from app.comparators.location_comparator import LocationComparator, haversine_meters
from app.comparators.text_comparator import TextComparator
from app.comparators.time_comparator import TimeComparator

__all__ = [
    "CategoryComparator",
    "Comparator",
    "LocationComparator",
    "TextComparator",
    "TimeComparator",
    "available_signal",
    "clamp_unit_score",
    "error_signal",
    "haversine_meters",
    "invalid_signal",
    "unavailable_signal",
]
