"""Unit tests for :mod:`app.comparators.time_comparator`."""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

import pytest

from app.comparators.time_comparator import TimeComparator
from app.schemas.complaint import Complaint
from app.schemas.duplicate_response import SignalStatus

IST = timezone(timedelta(hours=5, minutes=30))


def _complaint(complaint_id: str, reported_at: datetime | None = None) -> Complaint:
    return Complaint(complaint_id=complaint_id, reported_at=reported_at)


@pytest.fixture()
def comparator() -> TimeComparator:
    # 48-hour scale (the provisional default).
    return TimeComparator(decay_scale_seconds=172_800.0)


# -- identical ------------------------------------------------------------- #
def test_identical_timestamps_score_one(comparator: TimeComparator) -> None:
    moment = datetime(2026, 10, 14, 9, 15, tzinfo=timezone.utc)
    result = comparator.compare_timestamps(moment, moment)
    assert result.status is SignalStatus.AVAILABLE
    assert result.score == 1.0
    assert result.reason == "TIME_DECAY"
    assert result.details["difference_seconds"] == 0.0


# -- small / large gaps ---------------------------------------------------- #
def test_small_gap_is_high(comparator: TimeComparator) -> None:
    base = datetime(2026, 10, 14, 9, 15, tzinfo=timezone.utc)
    result = comparator.compare_timestamps(base, base + timedelta(minutes=30))
    assert result.status is SignalStatus.AVAILABLE
    assert result.score is not None and result.score > 0.9
    assert result.details["difference_seconds"] == pytest.approx(1800.0)
    assert result.details["difference_hours"] == pytest.approx(0.5)


def test_large_gap_is_low(comparator: TimeComparator) -> None:
    base = datetime(2026, 10, 14, 9, 15, tzinfo=timezone.utc)
    result = comparator.compare_timestamps(base, base + timedelta(days=30))
    assert result.status is SignalStatus.AVAILABLE
    assert result.score is not None and result.score < 0.01


# -- timezone offsets ------------------------------------------------------ #
def test_same_instant_different_offsets_score_one(
    comparator: TimeComparator,
) -> None:
    utc = datetime(2026, 10, 14, 9, 15, tzinfo=timezone.utc)
    ist = datetime(2026, 10, 14, 14, 45, tzinfo=IST)  # same instant
    result = comparator.compare_timestamps(utc, ist)
    assert result.status is SignalStatus.AVAILABLE
    assert result.score == 1.0
    assert result.details["difference_seconds"] == 0.0


def test_different_offsets_measure_true_gap(comparator: TimeComparator) -> None:
    utc = datetime(2026, 10, 14, 9, 15, tzinfo=timezone.utc)
    ist = datetime(2026, 10, 14, 15, 15, tzinfo=IST)  # 30 min after the above
    result = comparator.compare_timestamps(utc, ist)
    assert result.details["difference_seconds"] == pytest.approx(1800.0)


# -- missing --------------------------------------------------------------- #
@pytest.mark.parametrize(
    "left, right",
    [
        (None, datetime(2026, 10, 14, tzinfo=timezone.utc)),
        (datetime(2026, 10, 14, tzinfo=timezone.utc), None),
        (None, None),
    ],
)
def test_missing_timestamp_is_unavailable(
    comparator: TimeComparator, left: object, right: object
) -> None:
    result = comparator.compare_timestamps(left, right)
    assert result.status is SignalStatus.UNAVAILABLE
    assert result.score is None
    assert result.reason == "TIME_UNAVAILABLE"


# -- naive / invalid ------------------------------------------------------- #
def test_naive_timestamp_is_invalid(comparator: TimeComparator) -> None:
    aware = datetime(2026, 10, 14, 9, 15, tzinfo=timezone.utc)
    naive = datetime(2026, 10, 14, 9, 15)
    result = comparator.compare_timestamps(naive, aware)
    assert result.status is SignalStatus.INVALID
    assert result.score is None
    assert result.reason == "TIME_INVALID"


@pytest.mark.parametrize("bad", ["2026-10-14T09:15:00Z", 12345, ["2026"]])
def test_malformed_timestamp_is_invalid(
    comparator: TimeComparator, bad: object
) -> None:
    aware = datetime(2026, 10, 14, 9, 15, tzinfo=timezone.utc)
    result = comparator.compare_timestamps(bad, aware)
    assert result.status is SignalStatus.INVALID
    assert result.score is None


# -- monotonicity ---------------------------------------------------------- #
def test_decay_is_monotonic_non_increasing(comparator: TimeComparator) -> None:
    base = datetime(2026, 10, 14, 9, 15, tzinfo=timezone.utc)
    gaps = [timedelta(0), timedelta(minutes=5), timedelta(hours=1),
            timedelta(hours=12), timedelta(days=2), timedelta(days=10)]
    scores = [
        comparator.compare_timestamps(base, base + gap).score for gap in gaps
    ]
    for earlier, later in zip(scores, scores[1:]):
        assert earlier >= later  # never increases as the gap grows
    assert scores[0] == 1.0


def test_decay_matches_formula(comparator: TimeComparator) -> None:
    base = datetime(2026, 10, 14, 9, 15, tzinfo=timezone.utc)
    gap_seconds = 3600.0
    result = comparator.compare_timestamps(base, base + timedelta(seconds=gap_seconds))
    expected = math.exp(-gap_seconds / 172_800.0)
    assert result.score == pytest.approx(expected)


def test_symmetric(comparator: TimeComparator) -> None:
    a = datetime(2026, 10, 14, 9, 15, tzinfo=timezone.utc)
    b = datetime(2026, 10, 15, 3, 0, tzinfo=timezone.utc)
    assert comparator.compare_timestamps(a, b).score == comparator.compare_timestamps(
        b, a
    ).score


# -- record-level & configuration ------------------------------------------ #
def test_compare_reads_complaint_reported_at(comparator: TimeComparator) -> None:
    moment = datetime(2026, 10, 14, 9, 15, tzinfo=timezone.utc)
    result = comparator.compare(
        _complaint("NEW-1", moment),
        _complaint("CMP-1", moment),
    )
    assert result.status is SignalStatus.AVAILABLE
    assert result.score == 1.0


def test_invalid_decay_scale_is_rejected() -> None:
    with pytest.raises(ValueError):
        TimeComparator(decay_scale_seconds=0)
    with pytest.raises(ValueError):
        TimeComparator(decay_scale_seconds=-1)
    with pytest.raises(ValueError):
        TimeComparator(decay_scale_seconds=float("inf"))
