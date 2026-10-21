import pytest

from kavach.schemas.location import (
    Coordinates, DeviceLocation, ImageMetadataResult, ImageMetadataStatus,
    LocationSource, LocationStatus, ReasonCode,
)
from kavach.services.location.verification import LocationRules, LocationVerificationService

TARGET = Coordinates(latitude=23.2500, longitude=77.4000)
PIN = LocationSource.USER_SELECTED_PIN
svc = LocationVerificationService(LocationRules(radius_m=100, max_accuracy_m=150, source_conflict_m=250))


def device(lat, lon=77.4000, acc=15.0):
    return DeviceLocation(latitude=lat, longitude=lon, accuracy_meters=acc)


def exif(lat=None, lon=77.4000, status=None):
    if lat is None:
        return ImageMetadataResult(media_id="img-1", status=status or ImageMetadataStatus.GPS_MISSING,
                                   reason_codes=[ReasonCode.EXIF_GPS_MISSING])
    return ImageMetadataResult(media_id="img-1", status=ImageMetadataStatus.GPS_FOUND,
                               coordinates=Coordinates(latitude=lat, longitude=lon))


def check(dev=None, ex=(), target=TARGET):
    return svc.verify(target, PIN if target else None, dev, list(ex))


def test_no_target_is_not_checked():
    r = check(device(23.2503), target=None)
    assert r.status == LocationStatus.NOT_CHECKED and ReasonCode.NO_TARGET_COORDINATE in r.reason_codes


def test_no_sources_is_inconclusive_not_a_failure():
    r = check()
    assert r.status == LocationStatus.INCONCLUSIVE and ReasonCode.NO_COMPARISON_SOURCE in r.reason_codes
    assert not r.requires_human_review


def test_device_near_target_is_consistent():
    r = check(device(23.2503, 77.4002))
    assert r.status == LocationStatus.CONSISTENT and r.distance_meters < 100
    assert ReasonCode.WITHIN_CONFIGURED_RADIUS in r.reason_codes
    assert "not proof" in r.warning


def test_remote_report_is_mismatch_but_not_review_or_fraud():
    r = check(device(23.3500))  # ~11 km away
    assert r.status == LocationStatus.MISMATCH
    assert ReasonCode.REMOTE_REPORT_POSSIBLE in r.reason_codes and not r.requires_human_review


def test_poor_accuracy_is_inconclusive():
    r = check(device(23.2503, acc=500))
    assert r.status == LocationStatus.INCONCLUSIVE and ReasonCode.POOR_DEVICE_ACCURACY in r.reason_codes


def test_distance_within_accuracy_uncertainty_is_inconclusive():
    r = check(device(23.2516, acc=100))  # ~178 m away, radius+accuracy = 200 m
    assert r.status == LocationStatus.INCONCLUSIVE and ReasonCode.WITHIN_ACCURACY_UNCERTAINTY in r.reason_codes


def test_same_distance_with_good_accuracy_is_mismatch():
    assert check(device(23.2516, acc=20)).status == LocationStatus.MISMATCH


def test_exif_near_is_consistent_and_far_is_mismatch():
    assert check(ex=[exif(23.2502)]).status == LocationStatus.CONSISTENT
    assert check(ex=[exif(23.3500)]).status == LocationStatus.MISMATCH


def test_missing_exif_does_not_downgrade_good_device_evidence():
    r = check(device(23.2503), [exif(None)])
    assert r.status == LocationStatus.CONSISTENT and ReasonCode.EXIF_GPS_MISSING in r.reason_codes


def test_device_and_exif_disagree_preserved_and_flagged_for_review():
    r = check(device(23.2503), [exif(23.3500)])
    assert r.status == LocationStatus.INCONCLUSIVE
    assert ReasonCode.SOURCE_CONFLICT in r.reason_codes and r.requires_human_review
    assert {c.source for c in r.comparisons} == {LocationSource.DEVICE_GEOLOCATION, LocationSource.IMAGE_EXIF}


def test_device_far_exif_near_is_conflict_not_rejection():
    r = check(device(23.3500), [exif(23.2502)])
    assert r.status == LocationStatus.INCONCLUSIVE and r.requires_human_review


def test_both_far_but_agreeing_is_plain_mismatch_without_conflict():
    r = check(device(23.3500), [exif(23.3501)])
    assert r.status == LocationStatus.MISMATCH and ReasonCode.SOURCE_CONFLICT not in r.reason_codes


def test_rule_version_and_sources_are_reported():
    r = check(device(23.2503))
    assert r.rule_version and r.evidence_sources == [LocationSource.DEVICE_GEOLOCATION]
    assert r.target_source == PIN


def test_invalid_coordinates_rejected_by_schema():
    with pytest.raises(ValueError):
        Coordinates(latitude=float("nan"), longitude=0)
    with pytest.raises(ValueError):
        DeviceLocation(latitude=10, longitude=500)
