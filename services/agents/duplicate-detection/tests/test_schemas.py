"""Unit tests for the complaint, response and configuration schemas."""

from __future__ import annotations

import math
from datetime import timedelta

import pytest
from pydantic import ValidationError

from app.config.settings import (
    DEFAULT_SETTINGS,
    DecisionThresholds,
    MatchingWeights,
    Settings,
)
from app.schemas.complaint import Complaint, Location
from app.schemas.duplicate_response import (
    Decision,
    DuplicateDetectionResponse,
    SignalResult,
    SignalStatus,
)


def valid_payload(**overrides):
    """Build a valid complaint payload, applying ``overrides`` last."""
    payload = {
        "complaint_id": "CMP-2026-0001",
        "description": "Large pothole near the main gate of Central Market",
        "category": "ROAD_DAMAGE",
        "location": {
            "facility_id": "FAC-CENTRAL-MARKET",
            "location_id": "LOC-CM-GATE-NORTH",
            "latitude": 12.971598,
            "longitude": 77.594566,
        },
        "reported_at": "2026-10-14T09:15:00+05:30",
        "image_hash": None,
    }
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------- #
# Complaint and location schemas
# --------------------------------------------------------------------------- #


def test_valid_complaint_parses_all_fields():
    complaint = Complaint(**valid_payload())
    assert complaint.complaint_id == "CMP-2026-0001"
    assert complaint.category == "ROAD_DAMAGE"
    assert complaint.location.facility_id == "FAC-CENTRAL-MARKET"
    assert complaint.location.latitude == pytest.approx(12.971598)
    assert complaint.reported_at.utcoffset() == timedelta(hours=5, minutes=30)


def test_complaint_allows_missing_optional_fields():
    complaint = Complaint(complaint_id="CMP-2026-0002")
    assert complaint.description is None
    assert complaint.category is None
    assert complaint.location is None
    assert complaint.reported_at is None
    assert complaint.image_hash is None


def test_empty_complaint_id_is_rejected():
    with pytest.raises(ValidationError):
        Complaint(**valid_payload(complaint_id=""))


def test_whitespace_only_complaint_id_is_rejected():
    with pytest.raises(ValidationError):
        Complaint(**valid_payload(complaint_id="   "))


def test_missing_complaint_id_is_rejected():
    payload = valid_payload()
    del payload["complaint_id"]
    with pytest.raises(ValidationError):
        Complaint(**payload)


def test_complaint_id_is_trimmed():
    complaint = Complaint(**valid_payload(complaint_id="  CMP-2026-0003  "))
    assert complaint.complaint_id == "CMP-2026-0003"


@pytest.mark.parametrize("latitude", [-90.1, 90.1, 200.0, -180.0])
def test_latitude_outside_valid_range_is_rejected(latitude):
    with pytest.raises(ValidationError):
        Complaint(**valid_payload(location={"latitude": latitude, "longitude": 10.0}))


@pytest.mark.parametrize("longitude", [-180.1, 180.1, 500.0])
def test_longitude_outside_valid_range_is_rejected(longitude):
    with pytest.raises(ValidationError):
        Complaint(**valid_payload(location={"latitude": 10.0, "longitude": longitude}))


@pytest.mark.parametrize(
    "latitude, longitude",
    [(float("nan"), 10.0), (10.0, float("nan")), (float("inf"), 10.0), (10.0, float("-inf"))],
)
def test_non_finite_coordinates_are_rejected(latitude, longitude):
    with pytest.raises(ValidationError):
        Complaint(**valid_payload(location={"latitude": latitude, "longitude": longitude}))


def test_only_latitude_provided_is_rejected():
    with pytest.raises(ValidationError):
        Complaint(**valid_payload(location={"latitude": 12.97}))


def test_only_longitude_provided_is_rejected():
    with pytest.raises(ValidationError):
        Complaint(**valid_payload(location={"longitude": 77.59}))


def test_identifier_only_location_is_valid():
    complaint = Complaint(
        **valid_payload(location={"facility_id": "FAC-X", "location_id": "LOC-Y"})
    )
    assert complaint.location.latitude is None
    assert complaint.location.location_id == "LOC-Y"


def test_timezone_aware_timestamp_is_accepted():
    complaint = Complaint(**valid_payload(reported_at="2026-10-14T09:15:00+05:30"))
    assert complaint.reported_at.utcoffset() is not None


def test_timezone_naive_timestamp_is_rejected():
    with pytest.raises(ValidationError):
        Complaint(**valid_payload(reported_at="2026-10-14T09:15:00"))


def test_utc_zulu_timestamp_is_accepted():
    complaint = Complaint(**valid_payload(reported_at="2026-10-14T03:45:00Z"))
    assert complaint.reported_at.utcoffset().total_seconds() == 0


@pytest.mark.parametrize("blank", ["", "   ", "\t"])
def test_blank_description_normalises_to_none(blank):
    complaint = Complaint(**valid_payload(description=blank))
    assert complaint.description is None


@pytest.mark.parametrize("blank", ["", "   "])
def test_blank_category_normalises_to_none(blank):
    complaint = Complaint(**valid_payload(category=blank))
    assert complaint.category is None


def test_description_and_category_are_trimmed():
    complaint = Complaint(
        **valid_payload(description="  overflow  ", category="  WASTE  ")
    )
    assert complaint.description == "overflow"
    assert complaint.category == "WASTE"


def test_image_hash_is_optional_and_accepted_when_present():
    assert Complaint(**valid_payload(image_hash=None)).image_hash is None
    complaint = Complaint(**valid_payload(image_hash="phash:1a2b3c4d"))
    assert complaint.image_hash == "phash:1a2b3c4d"


def test_unknown_field_is_rejected():
    with pytest.raises(ValidationError):
        Complaint(**valid_payload(unexpected_field="x"))


# --------------------------------------------------------------------------- #
# Response schemas
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("decision", list(Decision))
def test_response_supports_every_decision(decision):
    response = DuplicateDetectionResponse(
        complaint_id="CMP-2026-0001",
        decision=decision,
    )
    assert response.decision is decision


def test_valid_signal_score_is_accepted():
    signal = SignalResult(status=SignalStatus.AVAILABLE, score=0.5, reason="TEXT_HIGH")
    assert signal.score == 0.5
    assert signal.reason == "TEXT_HIGH"


def test_available_signal_without_score_is_rejected():
    with pytest.raises(ValidationError):
        SignalResult(status=SignalStatus.AVAILABLE, score=None)


@pytest.mark.parametrize("score", [-0.01, 1.01, 2.0, -5.0])
def test_signal_score_outside_unit_range_is_rejected(score):
    with pytest.raises(ValidationError):
        SignalResult(status=SignalStatus.AVAILABLE, score=score)


@pytest.mark.parametrize("score", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_signal_score_is_rejected(score):
    with pytest.raises(ValidationError):
        SignalResult(status=SignalStatus.AVAILABLE, score=score)


@pytest.mark.parametrize(
    "status",
    [SignalStatus.UNAVAILABLE, SignalStatus.INVALID, SignalStatus.ERROR],
)
def test_unavailable_signal_with_null_score_is_valid(status):
    signal = SignalResult(status=status, score=None, reason="SIGNAL_UNAVAILABLE")
    assert signal.score is None


@pytest.mark.parametrize(
    "status",
    [SignalStatus.UNAVAILABLE, SignalStatus.INVALID, SignalStatus.ERROR],
)
def test_non_available_signal_with_numeric_score_is_rejected(status):
    with pytest.raises(ValidationError):
        SignalResult(status=status, score=0.0)


def test_response_accepts_signals_and_reasons():
    response = DuplicateDetectionResponse(
        complaint_id="CMP-2026-0001",
        decision=Decision.REVIEW_REQUIRED,
        matched_incident_id=None,
        score=0.62,
        signals={
            "text": SignalResult(status=SignalStatus.AVAILABLE, score=0.8),
            "location": SignalResult(
                status=SignalStatus.UNAVAILABLE,
                score=None,
                reason="SIGNAL_UNAVAILABLE_LOCATION",
            ),
        },
        reasons=["SCORE_BETWEEN_THRESHOLDS"],
    )
    assert response.signals["location"].score is None
    assert response.reasons == ["SCORE_BETWEEN_THRESHOLDS"]


def test_response_allows_null_score_for_new():
    response = DuplicateDetectionResponse(
        complaint_id="CMP-2026-0001",
        decision=Decision.NEW,
        score=None,
    )
    assert response.score is None
    assert response.matched_incident_id is None


@pytest.mark.parametrize("score", [-0.1, 1.5, 3.0])
def test_response_score_outside_unit_range_is_rejected(score):
    with pytest.raises(ValidationError):
        DuplicateDetectionResponse(
            complaint_id="CMP-2026-0001", decision=Decision.NEW, score=score
        )


@pytest.mark.parametrize("score", [float("nan"), float("inf")])
def test_response_non_finite_score_is_rejected(score):
    with pytest.raises(ValidationError):
        DuplicateDetectionResponse(
            complaint_id="CMP-2026-0001", decision=Decision.NEW, score=score
        )


def test_response_rejects_empty_complaint_id():
    with pytest.raises(ValidationError):
        DuplicateDetectionResponse(complaint_id="", decision=Decision.NEW)


# --------------------------------------------------------------------------- #
# Configuration schemas
# --------------------------------------------------------------------------- #


def test_default_weights_are_the_provisional_values():
    weights = MatchingWeights()
    assert weights.text == 0.40
    assert weights.location == 0.30
    assert weights.category == 0.15
    assert weights.time == 0.15
    assert weights.total() == pytest.approx(1.0)


def test_default_thresholds_are_the_provisional_values():
    thresholds = DecisionThresholds()
    assert thresholds.high == 0.85
    assert thresholds.low == 0.55
    assert thresholds.high > thresholds.low


def test_default_settings_are_valid():
    settings = Settings()
    assert settings.weights.total() > 0
    assert settings.thresholds.high > settings.thresholds.low
    assert settings.policy_version == "v1-draft"
    assert DEFAULT_SETTINGS == settings


@pytest.mark.parametrize("field", ["text", "location", "category", "time"])
def test_negative_weight_is_rejected(field):
    with pytest.raises(ValidationError):
        MatchingWeights(**{field: -0.1})


def test_all_zero_weights_are_rejected():
    with pytest.raises(ValidationError):
        MatchingWeights(text=0.0, location=0.0, category=0.0, time=0.0)


def test_non_finite_weight_is_rejected():
    with pytest.raises(ValidationError):
        MatchingWeights(text=float("inf"))


@pytest.mark.parametrize("high", [-0.1, 1.5])
def test_threshold_outside_unit_range_is_rejected(high):
    with pytest.raises(ValidationError):
        DecisionThresholds(high=high, low=0.5)


@pytest.mark.parametrize("low", [-0.1, 1.5])
def test_low_threshold_outside_unit_range_is_rejected(low):
    with pytest.raises(ValidationError):
        DecisionThresholds(high=0.9, low=low)


@pytest.mark.parametrize("high, low", [(0.5, 0.5), (0.4, 0.6)])
def test_high_not_greater_than_low_is_rejected(high, low):
    with pytest.raises(ValidationError):
        DecisionThresholds(high=high, low=low)


def test_non_finite_threshold_is_rejected():
    with pytest.raises(ValidationError):
        DecisionThresholds(high=math.inf, low=0.5)
