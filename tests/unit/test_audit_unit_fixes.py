"""Unit-level regression tests for audit fixes in pure functions."""
from io import BytesIO

import pytest
from PIL import Image

from kavach.schemas.incident_intelligence import Severity
from kavach.schemas.location import (
    Coordinates, DeviceLocation, ImageMetadataResult, ImageMetadataStatus, LocationSource, ReasonCode,
)
from kavach.services.incident_intelligence.severity_rules import apply_severity_floor
from kavach.services.location.exif_reader import read_image_metadata
from kavach.services.location.verification import LocationRules, LocationVerificationService
from kavach.services.media.validation import difference_hash, validate_image

TARGET = Coordinates(latitude=23.25, longitude=77.4)
svc = LocationVerificationService(LocationRules(radius_m=100, max_accuracy_m=150, source_conflict_m=250))


def test_poor_accuracy_device_does_not_create_source_conflict():
    dev = DeviceLocation(latitude=23.35, longitude=77.4, accuracy_meters=5000)
    ex = ImageMetadataResult(media_id="img-1", status=ImageMetadataStatus.GPS_FOUND,
                             coordinates=Coordinates(latitude=23.2502, longitude=77.4))
    r = svc.verify(TARGET, LocationSource.USER_SELECTED_PIN, dev, [ex])
    assert ReasonCode.SOURCE_CONFLICT not in r.reason_codes and not r.requires_human_review


def test_zero_zero_exif_gps_is_invalid(make_image):
    r = read_image_metadata(make_image(gps=(0.0, 0.0)), "img-1")
    assert r.status == ImageMetadataStatus.INVALID_GPS and r.coordinates is None


@pytest.mark.parametrize("text,rule", [
    ("बाजार में आग लगी है", "FIRE"),
    ("yahan aag lagi hai", "FIRE"),
    ("खंभे से करंट आ रहा है", "ELECTRICAL_HAZARD"),
    ("ek aadmi ghayal hai", "INJURY"),
    ("मंदिर के पास भगदड़", "CROWD_CRUSH"),
    ("deewar gir gayi", "STRUCTURAL"),
])
def test_hindi_and_hinglish_danger_words_escalate(text, rule):
    d = apply_severity_floor(text, Severity.LOW)
    assert d.severity == Severity.HIGH and rule in d.matched_rules


def test_hindi_word_boundary_avoids_aage_false_positive():
    assert apply_severity_floor("गेट के आगे कूड़ा पड़ा है", Severity.MEDIUM).severity == Severity.MEDIUM


def test_matched_rules_are_not_duplicated():
    d = apply_severity_floor("fire! आग! aag!", Severity.LOW)
    assert d.matched_rules.count("FIRE") == 1


def test_dhash_is_stable_and_similar_for_recompressed_image():
    img = Image.new("RGB", (120, 80))
    for x in range(120):
        for y in range(80):
            img.putpixel((x, y), (x * 2, y * 3, (x + y) % 255))
    a, b = BytesIO(), BytesIO()
    img.save(a, "JPEG", quality=95)
    img.resize((60, 40)).save(b, "JPEG", quality=40)
    ha = validate_image("1", a.getvalue(), 10**7).perceptual_hash
    hb = validate_image("2", b.getvalue(), 10**7).perceptual_hash
    assert len(ha) == 16 and bin(int(ha, 16) ^ int(hb, 16)).count("1") <= 6
    assert difference_hash(img) == difference_hash(img)
