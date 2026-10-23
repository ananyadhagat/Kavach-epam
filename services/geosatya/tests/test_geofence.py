"""The pure geofence rule: no HTTP, no database."""

import math

import pytest

from geosatya.location.coordinates import CoordinateError, haversine_m, validate_accuracy, validate_coordinates
from geosatya.location.geofence import Fix, Policy, check_worker_location
from tests.conftest import SPOT, offset

POLICY = Policy(radius_m=15, max_accuracy_m=25)


def check(point, accuracy=8.0, policy=POLICY, simulated=False, **kw):
    fix = None if point is None else Fix(point[0], point[1], accuracy, simulated)
    return check_worker_location(target=SPOT, fix=fix, policy=policy, **kw)


# ----------------------------------------------------------- coordinates
@pytest.mark.parametrize("lat,lon", [(23.25, 77.38), (-33.86, -151.2), (90, 180), (-90, -180), (0, 10)])
def test_valid_coordinates(lat, lon):
    assert validate_coordinates(lat, lon) == (float(lat), float(lon))


@pytest.mark.parametrize("lat,lon,code", [
    (91, 77, "LATITUDE_OUT_OF_RANGE"), (-90.1, 77, "LATITUDE_OUT_OF_RANGE"), (23, 180.5, "LONGITUDE_OUT_OF_RANGE"),
    (0, 0, "NULL_ISLAND"), (math.nan, 77, "COORDINATES_NOT_FINITE"), (23, math.inf, "COORDINATES_NOT_FINITE"),
    (-math.inf, 77, "COORDINATES_NOT_FINITE"), (True, 77, "COORDINATES_NOT_FINITE"), ("23", "77", "COORDINATES_NOT_FINITE"),
])
def test_invalid_coordinates(lat, lon, code):
    with pytest.raises(CoordinateError) as exc:
        validate_coordinates(lat, lon)
    assert exc.value.code == code


@pytest.mark.parametrize("bad", [0, -5, math.nan, math.inf, 200_000, "10"])
def test_invalid_accuracy(bad):
    with pytest.raises(CoordinateError):
        validate_accuracy(bad)


def test_haversine():
    assert haversine_m(0, 0, 1, 0) == pytest.approx(111_195, rel=1e-3)
    assert haversine_m(*SPOT, *offset(SPOT, north_m=12)) == pytest.approx(12, abs=0.05)
    assert haversine_m(*SPOT, *SPOT) == 0


# ------------------------------------------------------------ the rule
def test_inside_radius_passes():
    r = check(offset(SPOT, east_m=8))
    assert r["outcome"] == "PASS" and r["distance_m"] == pytest.approx(8, abs=0.2)
    assert "within the permitted radius" in r["message"] and r["needs_review"] is False


def test_outside_radius_fails_with_clear_message():
    r = check(offset(SPOT, east_m=60))
    assert r["outcome"] == "FAIL" and "OUTSIDE_RADIUS" in r["reason_codes"]
    assert "Move closer" in r["message"]


def test_poor_accuracy_inside_radius_is_not_a_pass():
    # reports 80 m accuracy while only 10 m away: position can't be established
    r = check(offset(SPOT, north_m=10), accuracy=80)
    assert r["outcome"] == "REVIEW_REQUIRED" and "POOR_GPS_ACCURACY" in r["reason_codes"]
    assert "too weak" in r["message"]


def test_poor_accuracy_cannot_rescue_a_far_point():
    assert check(offset(SPOT, north_m=500), accuracy=60)["outcome"] == "FAIL"


def test_boundary_within_accuracy_is_review():
    r = check(offset(SPOT, north_m=22), accuracy=10)
    assert r["outcome"] == "REVIEW_REQUIRED" and "BOUNDARY_UNCERTAIN" in r["reason_codes"]


def test_missing_or_denied_location_is_not_checked():
    r = check(None, unavailable_reason="PERMISSION_DENIED")
    assert r["outcome"] == "NOT_CHECKED" and "PERMISSION_DENIED" in r["reason_codes"]
    assert "permission was denied" in r["message"]
    assert check(None)["outcome"] == "NOT_CHECKED"


def test_no_target_is_not_checked():
    assert check_worker_location(target=None, fix=Fix(*SPOT, 5), policy=POLICY)["outcome"] == "NOT_CHECKED"


def test_missing_accuracy_is_review_not_pass():
    assert check(offset(SPOT, east_m=3), accuracy=None)["outcome"] == "REVIEW_REQUIRED"


def test_exif_far_from_incident_is_a_conflict():
    r = check(offset(SPOT, east_m=3), exif=offset(SPOT, north_m=900))
    assert r["outcome"] == "REVIEW_REQUIRED" and "SOURCE_CONFLICT" in r["reason_codes"]


def test_exif_that_disagrees_with_device():
    # near the target but 120 m from the device: still a conflict
    r = check(offset(SPOT, east_m=3, north_m=0), exif=offset(SPOT, north_m=-130))
    assert "SOURCE_CONFLICT" in r["reason_codes"]


def test_exif_agreeing_is_fine():
    assert check(offset(SPOT, east_m=3), exif=offset(SPOT, east_m=5))["outcome"] == "PASS"


def test_gallery_photo_location_is_unverified_without_exif():
    r = check(offset(SPOT, east_m=3), photo_source="GALLERY")
    assert r["outcome"] == "REVIEW_REQUIRED" and "PHOTO_LOCATION_UNVERIFIED" in r["reason_codes"]
    assert "could not be confidently associated" in r["message"]
    ok = check(offset(SPOT, east_m=3), photo_source="GALLERY", exif=offset(SPOT, east_m=4))
    assert ok["outcome"] == "PASS"


def test_duplicate_photo_needs_review():
    assert "DUPLICATE_PHOTO" in check(offset(SPOT, east_m=3), duplicate=True)["reason_codes"]


def test_simulated_location_is_labelled_and_gated():
    near = offset(SPOT, east_m=3)
    strict = check(near, simulated=True)
    assert strict["outcome"] == "REVIEW_REQUIRED" and strict["simulated"] is True
    demo = check(near, simulated=True, policy=Policy(15, 25, simulated_can_pass=True))
    assert demo["outcome"] == "PASS" and "SIMULATED" in demo["message"] and "SIMULATED_LOCATION" in demo["reason_codes"]
    far = check(offset(SPOT, east_m=80), simulated=True, policy=Policy(15, 25, simulated_can_pass=True))
    assert far["outcome"] == "FAIL"


def test_radius_is_configurable():
    point = offset(SPOT, east_m=18)
    assert check(point, accuracy=3)["outcome"] != "PASS"
    assert check(point, accuracy=3, policy=Policy(20, 25))["outcome"] == "PASS"


@pytest.mark.parametrize("bad", [0, -1, math.nan])
def test_policy_rejects_bad_values(bad):
    with pytest.raises(ValueError):
        Policy(radius_m=bad, max_accuracy_m=25)
