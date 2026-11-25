"""Unit tests for :mod:`app.comparators.category_comparator`."""

from __future__ import annotations

import pytest

from app.comparators.category_comparator import CategoryComparator
from app.config.settings import CategoryCompatibilityMap
from app.schemas.complaint import Complaint
from app.schemas.duplicate_response import SignalStatus


def _complaint(complaint_id: str, category: str | None = None) -> Complaint:
    return Complaint(complaint_id=complaint_id, category=category)


@pytest.fixture()
def comparator() -> CategoryComparator:
    return CategoryComparator()


# -- exact matches --------------------------------------------------------- #
def test_exact_match_scores_one(comparator: CategoryComparator) -> None:
    result = comparator.compare_categories("ROAD_DAMAGE", "ROAD_DAMAGE")
    assert result.status is SignalStatus.AVAILABLE
    assert result.score == 1.0
    assert result.reason == "CATEGORY_EXACT_MATCH"
    assert result.details["relation"] == "exact"


# -- normalisation --------------------------------------------------------- #
@pytest.mark.parametrize(
    "left, right",
    [
        ("road_damage", "ROAD_DAMAGE"),
        ("  ROAD_DAMAGE  ", "road_damage"),
        ("Road_Damage", "ROAD_DAMAGE"),
    ],
)
def test_case_and_whitespace_normalisation(
    comparator: CategoryComparator, left: str, right: str
) -> None:
    result = comparator.compare_categories(left, right)
    assert result.status is SignalStatus.AVAILABLE
    assert result.score == 1.0
    assert result.details["category_a"] == "ROAD_DAMAGE"
    assert result.details["category_b"] == "ROAD_DAMAGE"


# -- known compatible ------------------------------------------------------ #
def test_known_compatible_pair(comparator: CategoryComparator) -> None:
    result = comparator.compare_categories("ROAD_DAMAGE", "POTHOLE")
    assert result.status is SignalStatus.AVAILABLE
    assert result.score == pytest.approx(0.60)
    assert result.reason == "CATEGORY_COMPATIBLE"
    assert result.details["relation"] == "compatible"
    assert "conflict" not in (result.details or {})


# -- known incompatible ---------------------------------------------------- #
def test_known_incompatible_pair(comparator: CategoryComparator) -> None:
    result = comparator.compare_categories("WASTE_MANAGEMENT", "STREETLIGHT")
    assert result.status is SignalStatus.AVAILABLE
    assert result.score == 0.0
    assert result.reason == "CATEGORY_INCOMPATIBLE"
    assert result.details["relation"] == "incompatible"
    assert result.details["conflict"] is True
    assert result.details["conflict_code"] == "CATEGORY_INCOMPATIBLE"


def test_incompatible_overrides_compatible_group() -> None:
    # A map that deliberately lists the same pair as both compatible and
    # incompatible must resolve to incompatible (safety precedence).
    compat = CategoryCompatibilityMap(
        compatible_groups=(frozenset({"ALPHA", "BETA"}),),
        incompatible_pairs=(frozenset({"ALPHA", "BETA"}),),
    )
    comparator = CategoryComparator(compatibility_map=compat)
    result = comparator.compare_categories("ALPHA", "BETA")
    assert result.status is SignalStatus.AVAILABLE
    assert result.score == 0.0
    assert result.reason == "CATEGORY_INCOMPATIBLE"


# -- unknown --------------------------------------------------------------- #
def test_unknown_categories_are_unavailable(comparator: CategoryComparator) -> None:
    result = comparator.compare_categories("MYSTERY_A", "MYSTERY_B")
    assert result.status is SignalStatus.UNAVAILABLE
    assert result.score is None
    assert result.reason == "CATEGORY_UNKNOWN"
    assert result.details["relation"] == "unknown"


def test_similar_looking_unknown_categories_are_not_compatible(
    comparator: CategoryComparator,
) -> None:
    # Different codes that merely *look* alike must not be assumed compatible.
    result = comparator.compare_categories("ROAD_DAMAGE_2", "ROAD_DAMAGE")
    assert result.status is SignalStatus.UNAVAILABLE
    assert result.score is None


# -- missing --------------------------------------------------------------- #
@pytest.mark.parametrize(
    "left, right",
    [
        (None, "ROAD_DAMAGE"),
        ("ROAD_DAMAGE", None),
        (None, None),
        ("", "ROAD_DAMAGE"),
        ("ROAD_DAMAGE", "   "),
    ],
)
def test_missing_or_blank_is_unavailable(
    comparator: CategoryComparator, left: object, right: object
) -> None:
    result = comparator.compare_categories(left, right)
    assert result.status is SignalStatus.UNAVAILABLE
    assert result.score is None
    assert result.reason == "CATEGORY_UNAVAILABLE"


# -- malformed ------------------------------------------------------------- #
@pytest.mark.parametrize("bad", [123, 4.5, ["ROAD_DAMAGE"], {"a": 1}])
def test_malformed_category_is_invalid(
    comparator: CategoryComparator, bad: object
) -> None:
    result = comparator.compare_categories(bad, "ROAD_DAMAGE")
    assert result.status is SignalStatus.INVALID
    assert result.score is None
    assert result.reason == "CATEGORY_INVALID"


# -- record-level ---------------------------------------------------------- #
def test_compare_reads_complaint_category(comparator: CategoryComparator) -> None:
    result = comparator.compare(
        _complaint("NEW-1", "streetlight"),
        _complaint("CMP-1", "STREETLIGHT"),
    )
    assert result.status is SignalStatus.AVAILABLE
    assert result.score == 1.0


def test_compare_with_missing_category(comparator: CategoryComparator) -> None:
    result = comparator.compare(_complaint("NEW-1"), _complaint("CMP-1", "STREETLIGHT"))
    assert result.status is SignalStatus.UNAVAILABLE
    assert result.score is None


# -- custom mapping -------------------------------------------------------- #
def test_custom_mapping_overrides_default() -> None:
    compat = CategoryCompatibilityMap(
        compatible_groups=(frozenset({"TREES", "PARKS"}),),
        incompatible_pairs=(),
    )
    comparator = CategoryComparator(compatibility_map=compat)
    assert comparator.compare_categories("TREES", "PARKS").score == pytest.approx(0.60)
    # The default map's compatible pair is now unknown.
    assert (
        comparator.compare_categories("ROAD_DAMAGE", "POTHOLE").status
        is SignalStatus.UNAVAILABLE
    )


def test_custom_compatible_score_is_validated() -> None:
    with pytest.raises(ValueError):
        CategoryComparator(compatible_score=1.5)
    with pytest.raises(ValueError):
        CategoryComparator(compatible_score=float("nan"))
