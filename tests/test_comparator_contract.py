"""Cross-comparator contract tests for Phase 3.

These verify the *shared* guarantees that every comparator must uphold, rather
than any single comparator's behaviour.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

import pytest

from app.comparators import (
    CategoryComparator,
    Comparator,
    LocationComparator,
    TextComparator,
    TimeComparator,
)
from app.schemas.complaint import Complaint, Location
from app.schemas.duplicate_response import SignalResult, SignalStatus

UTC = timezone.utc
_MOMENT = datetime(2026, 10, 14, 9, 15, tzinfo=UTC)


def _rich_complaint(complaint_id: str, marker: str) -> Complaint:
    return Complaint(
        complaint_id=complaint_id,
        description=f"broken streetlight near {marker} gate",
        category="STREETLIGHT",
        location=Location(
            facility_id="FAC-A",
            location_id="LOC-1",
            latitude=12.9716,
            longitude=77.5946,
        ),
        reported_at=_MOMENT,
        image_hash="phash:deadbeef",
    )


def _sparse_complaint(complaint_id: str) -> Complaint:
    """Every optional field absent."""
    return Complaint(complaint_id=complaint_id)


def _all_comparators() -> list[Comparator]:
    return [
        CategoryComparator(),
        TimeComparator(),
        LocationComparator(),
        TextComparator(),
    ]


# -- common interface ------------------------------------------------------ #
def test_all_comparators_expose_common_interface() -> None:
    names = set()
    for comparator in _all_comparators():
        assert isinstance(comparator, Comparator)
        assert isinstance(comparator.name, str) and comparator.name
        assert callable(comparator.compare)
        names.add(comparator.name)
    assert names == {"category", "time", "location", "text"}


def test_compare_returns_signal_result() -> None:
    a = _rich_complaint("NEW-1", "north")
    b = _rich_complaint("CMP-1", "north")
    for comparator in _all_comparators():
        result = comparator.compare(a, b)
        assert isinstance(result, SignalResult)


# -- available scores: finite and bounded ---------------------------------- #
def test_available_scores_are_finite_and_bounded() -> None:
    a = _rich_complaint("NEW-1", "north")
    b = _rich_complaint("CMP-1", "north")
    for comparator in _all_comparators():
        result = comparator.compare(a, b)
        assert result.status is SignalStatus.AVAILABLE
        assert result.score is not None
        assert math.isfinite(result.score)
        assert 0.0 <= result.score <= 1.0


# -- unavailable scores: null ---------------------------------------------- #
def test_unavailable_scores_are_null() -> None:
    a = _sparse_complaint("NEW-1")
    b = _sparse_complaint("CMP-1")
    for comparator in _all_comparators():
        result = comparator.compare(a, b)
        assert result.status is SignalStatus.UNAVAILABLE
        assert result.score is None
        assert result.reason is not None


# -- invalid vs ordinary low similarity ------------------------------------ #
def _available_low_results() -> list[SignalResult]:
    return [
        CategoryComparator().compare_categories("WASTE_MANAGEMENT", "STREETLIGHT"),
        TimeComparator().compare_timestamps(_MOMENT, _MOMENT + timedelta(days=90)),
        LocationComparator().compare_locations(
            Location(latitude=0.0, longitude=0.0),
            Location(latitude=45.0, longitude=45.0),
        ),
        TextComparator().compare_texts("garbage overflow", "pothole highway"),
    ]


def _invalid_results() -> list[SignalResult]:
    return [
        CategoryComparator().compare_categories(123, "STREETLIGHT"),
        TimeComparator().compare_timestamps(
            datetime(2026, 10, 14, 9, 15), _MOMENT  # naive
        ),
        LocationComparator().compare_locations(
            Location.model_construct(latitude=999.0, longitude=0.0),
            Location(latitude=0.0, longitude=0.0),
        ),
        TextComparator().compare_texts(123, "a real description"),
    ]


def test_invalid_is_distinct_from_low_similarity() -> None:
    for result in _available_low_results():
        assert result.status is SignalStatus.AVAILABLE
        assert result.score is not None and result.score <= 0.01
    for result in _invalid_results():
        assert result.status is SignalStatus.INVALID
        assert result.score is None


# -- purity: no mutation --------------------------------------------------- #
def test_comparators_do_not_mutate_complaints() -> None:
    a = _rich_complaint("NEW-1", "north")
    b = _rich_complaint("CMP-1", "south")
    before_a = a.model_dump()
    before_b = b.model_dump()
    for comparator in _all_comparators():
        comparator.compare(a, b)
    assert a.model_dump() == before_a
    assert b.model_dump() == before_b


# -- determinism ----------------------------------------------------------- #
def test_comparators_are_deterministic() -> None:
    a = _rich_complaint("NEW-1", "north")
    b = _rich_complaint("CMP-1", "north")
    for comparator in _all_comparators():
        first = comparator.compare(a, b)
        second = comparator.compare(a, b)
        assert first.model_dump() == second.model_dump()


# -- conflicts remain visible --------------------------------------------- #
def test_location_conflict_is_preserved_for_phase4() -> None:
    a = Complaint(
        complaint_id="NEW-1",
        location=Location(
            facility_id="FAC-A", location_id="LOC-1",
            latitude=12.9716, longitude=77.5946,
        ),
    )
    b = Complaint(
        complaint_id="CMP-1",
        location=Location(
            facility_id="FAC-B", location_id="LOC-1",
            latitude=12.9716, longitude=77.5946,  # same coords
        ),
    )
    result = LocationComparator().compare(a, b)
    assert result.status is SignalStatus.AVAILABLE
    assert result.score == 0.0
    assert result.details is not None
    assert result.details.get("conflict") is True
    assert result.details.get("conflict_code")


# -- comparators never decide the outcome ---------------------------------- #
def test_comparators_do_not_return_final_decisions() -> None:
    a = _rich_complaint("NEW-1", "north")
    b = _rich_complaint("CMP-1", "north")
    forbidden = {"decision", "matched_incident_id", "DUPLICATE", "NEW"}
    for comparator in _all_comparators():
        result = comparator.compare(a, b)
        assert not (set(result.model_dump().keys()) & forbidden)
        assert not hasattr(result, "decision")
        # A signal's reason is an evidence label, never a final decision code.
        if result.reason is not None:
            assert result.reason not in {"DUPLICATE", "NEW", "REVIEW_REQUIRED"}
