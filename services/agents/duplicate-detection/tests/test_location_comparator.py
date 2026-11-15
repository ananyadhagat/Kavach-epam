"""Unit tests for :mod:`app.comparators.location_comparator`."""

from __future__ import annotations

import pytest

from app.comparators.location_comparator import LocationComparator, haversine_meters
from app.schemas.complaint import Complaint, Location
from app.schemas.duplicate_response import SignalStatus

# Bangalore-ish base point and a ~100 m northern offset.
_BASE_LAT = 12.9716
_BASE_LON = 77.5946
_NEAR_LAT = _BASE_LAT + 0.0009  # ~100 m


def _location(
    facility_id: str | None = None,
    location_id: str | None = None,
    latitude: float | None = None,
    longitude: float | None = None,
) -> Location:
    return Location(
        facility_id=facility_id,
        location_id=location_id,
        latitude=latitude,
        longitude=longitude,
    )


def _raw_location(**fields: object) -> Location:
    """Bypass validation to build deliberately malformed locations for tests."""
    return Location.model_construct(**fields)


@pytest.fixture()
def comparator() -> LocationComparator:
    # 500 m linear scale (the provisional default).
    return LocationComparator(distance_scale_m=500.0)


# -- coordinates ----------------------------------------------------------- #
def test_identical_coordinates_score_one(comparator: LocationComparator) -> None:
    a = _location(latitude=_BASE_LAT, longitude=_BASE_LON)
    b = _location(latitude=_BASE_LAT, longitude=_BASE_LON)
    result = comparator.compare_locations(a, b)
    assert result.status is SignalStatus.AVAILABLE
    assert result.score == 1.0
    assert result.reason == "LOCATION_PROXIMITY"
    assert result.details["basis"] == "coordinates"
    assert result.details["distance_m"] == pytest.approx(0.0, abs=1e-6)


def test_nearby_coordinates_score_high(comparator: LocationComparator) -> None:
    a = _location(latitude=_BASE_LAT, longitude=_BASE_LON)
    b = _location(latitude=_NEAR_LAT, longitude=_BASE_LON)
    result = comparator.compare_locations(a, b)
    assert result.status is SignalStatus.AVAILABLE
    assert result.score is not None
    assert 0.75 < result.score < 0.85
    assert result.details["distance_m"] == pytest.approx(100.0, abs=5.0)


def test_distant_coordinates_score_zero(comparator: LocationComparator) -> None:
    a = _location(latitude=_BASE_LAT, longitude=_BASE_LON)
    b = _location(latitude=_BASE_LAT + 0.05, longitude=_BASE_LON)  # ~5.5 km
    result = comparator.compare_locations(a, b)
    assert result.status is SignalStatus.AVAILABLE
    assert result.score == 0.0
    assert result.details["distance_m"] > 500.0


@pytest.mark.parametrize(
    "latitude, longitude",
    [(90.0, 180.0), (-90.0, -180.0), (0.0, 0.0), (90.0, -180.0)],
)
def test_valid_boundary_coordinates(
    comparator: LocationComparator, latitude: float, longitude: float
) -> None:
    a = _location(latitude=latitude, longitude=longitude)
    b = _location(latitude=latitude, longitude=longitude)
    result = comparator.compare_locations(a, b)
    assert result.status is SignalStatus.AVAILABLE
    assert result.score == 1.0


def test_distance_decreases_monotonically(comparator: LocationComparator) -> None:
    a = _location(latitude=_BASE_LAT, longitude=_BASE_LON)
    scores = []
    for offset in (0.0, 0.001, 0.002, 0.004, 0.01):
        b = _location(latitude=_BASE_LAT + offset, longitude=_BASE_LON)
        scores.append(comparator.compare_locations(a, b).score)
    for earlier, later in zip(scores, scores[1:]):
        assert earlier >= later


# -- malformed coordinates ------------------------------------------------- #
@pytest.mark.parametrize(
    "fields",
    [
        {"latitude": 120.0, "longitude": 77.0},        # latitude out of range
        {"latitude": 12.0, "longitude": 200.0},        # longitude out of range
        {"latitude": float("nan"), "longitude": 77.0},  # NaN
        {"latitude": float("inf"), "longitude": 77.0},  # infinite
        {"latitude": 12.0, "longitude": float("nan")},
        {"latitude": 12.0},                             # lone coordinate
        {"longitude": 77.0},                            # lone coordinate
    ],
)
def test_malformed_coordinates_are_invalid(
    comparator: LocationComparator, fields: dict[str, object]
) -> None:
    a = _raw_location(**fields)
    b = _location(latitude=_BASE_LAT, longitude=_BASE_LON)
    result = comparator.compare_locations(a, b)
    assert result.status is SignalStatus.INVALID
    assert result.score is None
    assert result.reason == "LOCATION_INVALID"
    assert result.details["coordinates_valid"] is False


# -- missing --------------------------------------------------------------- #
@pytest.mark.parametrize(
    "left, right",
    [
        (None, _location(latitude=_BASE_LAT, longitude=_BASE_LON)),
        (_location(latitude=_BASE_LAT, longitude=_BASE_LON), None),
        (None, None),
    ],
)
def test_missing_location_is_unavailable(
    comparator: LocationComparator, left: object, right: object
) -> None:
    result = comparator.compare_locations(left, right)  # type: ignore[arg-type]
    assert result.status is SignalStatus.UNAVAILABLE
    assert result.score is None
    assert result.reason == "LOCATION_UNAVAILABLE"


def test_empty_location_is_unavailable(comparator: LocationComparator) -> None:
    result = comparator.compare_locations(_location(), _location())
    assert result.status is SignalStatus.UNAVAILABLE
    assert result.score is None


def test_one_side_missing_coordinates_is_unavailable(
    comparator: LocationComparator,
) -> None:
    a = _location(latitude=_BASE_LAT, longitude=_BASE_LON)
    b = _location(facility_id="FAC-A")  # an id but no coordinates
    result = comparator.compare_locations(a, b)
    # Only one side has coordinates and only one side has a facility id, so
    # there is no shared identifier and no comparable coordinate pair.
    assert result.status is SignalStatus.UNAVAILABLE
    assert result.score is None


# -- identifiers ----------------------------------------------------------- #
def test_matching_facility_and_location_ids(comparator: LocationComparator) -> None:
    a = _location(facility_id="FAC-A", location_id="LOC-1")
    b = _location(facility_id="FAC-A", location_id="LOC-1")
    result = comparator.compare_locations(a, b)
    assert result.status is SignalStatus.AVAILABLE
    assert result.score == 1.0
    assert result.reason == "LOCATION_IDENTIFIER_MATCH"
    assert result.details["basis"] == "identifier"


def test_same_location_id_without_facilities_matches(
    comparator: LocationComparator,
) -> None:
    a = _location(location_id="LOC-1")
    b = _location(location_id="LOC-1")
    result = comparator.compare_locations(a, b)
    assert result.status is SignalStatus.AVAILABLE
    assert result.score == 1.0


def test_same_location_id_different_facilities_conflicts(
    comparator: LocationComparator,
) -> None:
    a = _location(facility_id="FAC-A", location_id="LOC-1")
    b = _location(facility_id="FAC-B", location_id="LOC-1")
    result = comparator.compare_locations(a, b)
    assert result.status is SignalStatus.AVAILABLE
    assert result.score == 0.0
    assert result.reason == "LOCATION_FACILITY_CONFLICT"
    assert result.details["conflict"] is True
    assert result.details["conflict_code"] == "LOCATION_FACILITY_CONFLICT"


def test_different_location_id_same_facility_is_partial(
    comparator: LocationComparator,
) -> None:
    a = _location(facility_id="FAC-A", location_id="LOC-1")
    b = _location(facility_id="FAC-A", location_id="LOC-2")
    result = comparator.compare_locations(a, b)
    assert result.status is SignalStatus.AVAILABLE
    assert result.score == pytest.approx(0.60)
    assert result.reason == "LOCATION_FACILITY_MATCH"


def test_different_location_id_no_facility_conflicts(
    comparator: LocationComparator,
) -> None:
    a = _location(location_id="LOC-1")
    b = _location(location_id="LOC-2")
    result = comparator.compare_locations(a, b)
    assert result.status is SignalStatus.AVAILABLE
    assert result.score == 0.0
    assert result.reason == "LOCATION_IDENTIFIER_CONFLICT"
    assert result.details["conflict"] is True


def test_matching_facility_only_is_partial(
    comparator: LocationComparator,
) -> None:
    a = _location(facility_id="FAC-A")
    b = _location(facility_id="FAC-A")
    result = comparator.compare_locations(a, b)
    assert result.status is SignalStatus.AVAILABLE
    assert result.score == pytest.approx(0.60)
    assert result.reason == "LOCATION_FACILITY_MATCH"


def test_conflicting_facilities_conflict(comparator: LocationComparator) -> None:
    a = _location(facility_id="FAC-A")
    b = _location(facility_id="FAC-B")
    result = comparator.compare_locations(a, b)
    assert result.status is SignalStatus.AVAILABLE
    assert result.score == 0.0
    assert result.details["conflict"] is True


def test_conflict_preserved_despite_close_coordinates(
    comparator: LocationComparator,
) -> None:
    # Different facilities and different sub-sites, but only ~100 m apart. The
    # conflict must survive and the distance must still be retained as evidence.
    a = _location(facility_id="FAC-A", location_id="LOC-1",
                  latitude=_BASE_LAT, longitude=_BASE_LON)
    b = _location(facility_id="FAC-B", location_id="LOC-2",
                  latitude=_NEAR_LAT, longitude=_BASE_LON)
    result = comparator.compare_locations(a, b)
    assert result.status is SignalStatus.AVAILABLE
    assert result.score == 0.0
    assert result.details["conflict"] is True
    assert result.details["distance_m"] == pytest.approx(100.0, abs=5.0)


def test_missing_ids_valid_coordinates_uses_coordinates(
    comparator: LocationComparator,
) -> None:
    a = _location(latitude=_BASE_LAT, longitude=_BASE_LON)
    b = _location(latitude=_NEAR_LAT, longitude=_BASE_LON)
    result = comparator.compare_locations(a, b)
    assert result.status is SignalStatus.AVAILABLE
    assert result.details["basis"] == "coordinates"


def test_identifier_match_includes_supporting_distance(
    comparator: LocationComparator,
) -> None:
    a = _location(facility_id="FAC-A", location_id="LOC-1",
                  latitude=_BASE_LAT, longitude=_BASE_LON)
    b = _location(facility_id="FAC-A", location_id="LOC-1",
                  latitude=_NEAR_LAT, longitude=_BASE_LON)
    result = comparator.compare_locations(a, b)
    assert result.score == 1.0
    assert result.details["distance_m"] == pytest.approx(100.0, abs=5.0)


# -- record-level & helpers ------------------------------------------------ #
def test_compare_reads_complaint_location(comparator: LocationComparator) -> None:
    a = Complaint(complaint_id="NEW-1",
                  location=_location(latitude=_BASE_LAT, longitude=_BASE_LON))
    b = Complaint(complaint_id="CMP-1",
                  location=_location(latitude=_BASE_LAT, longitude=_BASE_LON))
    result = comparator.compare(a, b)
    assert result.status is SignalStatus.AVAILABLE
    assert result.score == 1.0


def test_haversine_zero_for_identical_points() -> None:
    assert haversine_meters(12.0, 77.0, 12.0, 77.0) == pytest.approx(0.0)


def test_haversine_is_symmetric() -> None:
    forward = haversine_meters(12.0, 77.0, 12.5, 77.5)
    backward = haversine_meters(12.5, 77.5, 12.0, 77.0)
    assert forward == pytest.approx(backward)


def test_invalid_distance_scale_is_rejected() -> None:
    with pytest.raises(ValueError):
        LocationComparator(distance_scale_m=0)
    with pytest.raises(ValueError):
        LocationComparator(distance_scale_m=float("nan"))
