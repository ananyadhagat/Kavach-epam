"""Category comparator.

Compares the category of a new complaint against an existing candidate using an
explicit, configurable compatibility mapping.

Outcomes
--------
* exact match (after trim + case-fold) ........ ``AVAILABLE`` score ``1.0``
* known-compatible pair ....................... ``AVAILABLE`` score
  ``category_compatible_score`` (default ``0.60``)
* known-incompatible pair ..................... ``AVAILABLE`` score ``0.0`` with
  ``details["conflict"] is True``
* unknown relationship ........................ ``UNAVAILABLE`` (score ``None``)
* missing/blank category on either side ....... ``UNAVAILABLE`` (score ``None``)
* non-string (malformed) category ............. ``INVALID`` (score ``None``)

Why unknown pairs are ``UNAVAILABLE`` rather than a penalty
-----------------------------------------------------------
The real KAVACH category vocabulary is a TEAM-DECISION and is not known yet.
Unknown pairs are therefore *not* evidence of difference — they are simply
unevidenced, so we never penalise a pair merely because two codes look
different. They are also never treated as compatible just because the strings
look similar. This matches the Phase 1 rule that an unknown category relation
yields no usable signal.

Replacing the sample taxonomy
-----------------------------
The mapping lives in configuration (:class:`~app.config.settings
.CategoryCompatibilityMap`), not in this module. The default groups/pairs are
clearly-fictional placeholders; swap them for KAVACH's real identifiers without
touching this comparator.
"""

from __future__ import annotations

import math
from typing import Any

from app.comparators.base import (
    Comparator,
    available_signal,
    invalid_signal,
    unavailable_signal,
)
from app.config.settings import DEFAULT_SETTINGS, CategoryCompatibilityMap
from app.schemas.complaint import Complaint
from app.schemas.duplicate_response import SignalResult

#: Sentinel returned by :func:`_normalise_category` for non-string input.
_INVALID = object()


def _normalise_category(value: object) -> str | None | object:
    """Trim and upper-case a category.

    Returns ``None`` for missing/blank input, the normalised string for usable
    input, or the ``_INVALID`` sentinel for a non-string value.
    """
    if value is None:
        return None
    if not isinstance(value, str):
        return _INVALID
    stripped = value.strip()
    return stripped.upper() if stripped else None


def _display(value: object) -> str | None:
    """Render a raw category value for the ``details`` block."""
    if value is None:
        return None
    return value if isinstance(value, str) else str(value)


class CategoryComparator(Comparator):
    """Compare complaint categories via an explicit compatibility map.

    Parameters
    ----------
    compatibility_map:
        The compatibility mapping to use. Defaults to the provisional mapping in
        :data:`app.config.settings.DEFAULT_SETTINGS`.
    compatible_score:
        Score returned for a known-compatible (but non-identical) pair. Must be
        finite and inside ``[0, 1]``. Defaults to the configured value.
    """

    name = "category"

    def __init__(
        self,
        compatibility_map: CategoryCompatibilityMap | None = None,
        compatible_score: float | None = None,
    ) -> None:
        if compatibility_map is None:
            compatibility_map = DEFAULT_SETTINGS.comparators.category_map
        if compatible_score is None:
            compatible_score = DEFAULT_SETTINGS.comparators.category_compatible_score
        if not math.isfinite(compatible_score) or not (0.0 <= compatible_score <= 1.0):
            raise ValueError(
                "compatible_score must be a finite value between 0 and 1"
            )
        self._map = compatibility_map
        self._compatible_score = float(compatible_score)

    # -- record-level entry point ------------------------------------------ #
    def compare(self, complaint: Complaint, candidate: Complaint) -> SignalResult:
        """Compare ``complaint.category`` with ``candidate.category``."""
        return self.compare_categories(complaint.category, candidate.category)

    # -- field-level entry point ------------------------------------------- #
    def compare_categories(
        self, category_a: object, category_b: object
    ) -> SignalResult:
        """Compare two raw category values."""
        normalised_a = _normalise_category(category_a)
        normalised_b = _normalise_category(category_b)

        if normalised_a is _INVALID or normalised_b is _INVALID:
            return invalid_signal(
                "CATEGORY_INVALID",
                {
                    "category_a": _display(category_a),
                    "category_b": _display(category_b),
                },
            )

        base_details: dict[str, Any] = {
            "category_a": normalised_a,
            "category_b": normalised_b,
        }

        if normalised_a is None or normalised_b is None:
            return unavailable_signal("CATEGORY_UNAVAILABLE", base_details)

        # Both normalised to non-empty strings from here on.
        assert isinstance(normalised_a, str) and isinstance(normalised_b, str)

        if normalised_a == normalised_b:
            return available_signal(
                1.0,
                "CATEGORY_EXACT_MATCH",
                {**base_details, "relation": "exact"},
            )

        if self._map.are_incompatible(normalised_a, normalised_b):
            return available_signal(
                0.0,
                "CATEGORY_INCOMPATIBLE",
                {
                    **base_details,
                    "relation": "incompatible",
                    "conflict": True,
                    "conflict_code": "CATEGORY_INCOMPATIBLE",
                },
            )

        if self._map.are_compatible(normalised_a, normalised_b):
            return available_signal(
                self._compatible_score,
                "CATEGORY_COMPATIBLE",
                {**base_details, "relation": "compatible"},
            )

        return unavailable_signal(
            "CATEGORY_UNKNOWN",
            {**base_details, "relation": "unknown"},
        )


__all__ = ["CategoryComparator"]
