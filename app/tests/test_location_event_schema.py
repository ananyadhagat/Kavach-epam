import pytest
from pydantic import ValidationError

from app.schemas.location_event import LocationEventCreate


def test_browser_arrival_payload_matches_location_event_contract():
    payload = LocationEventCreate(
        event_type="ARRIVAL",
        capture_status="CAPTURED",
        latitude=28.6139,
        longitude=77.209,
        accuracy_meters=12.5,
        captured_at_device="2026-10-30T12:00:00.000Z",
    )

    assert payload.latitude == 28.6139
    assert payload.longitude == 77.209
    assert payload.accuracy_meters == 12.5
    assert payload.captured_at_device.isoformat() == "2026-10-30T12:00:00+00:00"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("latitude", 91),
        ("longitude", 181),
        ("accuracy_meters", 0),
        ("accuracy_meters", 100_001),
    ],
)
def test_invalid_browser_location_values_are_rejected(field, value):
    payload = {
        "event_type": "ARRIVAL",
        "capture_status": "CAPTURED",
        "latitude": 28.6139,
        "longitude": 77.209,
        "accuracy_meters": 12.5,
        "captured_at_device": "2026-10-30T12:00:00.000Z",
    }
    payload[field] = value

    with pytest.raises(ValidationError):
        LocationEventCreate(**payload)


def test_captured_location_requires_accuracy():
    with pytest.raises(ValidationError, match="requires GPS accuracy"):
        LocationEventCreate(
            event_type="ARRIVAL",
            capture_status="CAPTURED",
            latitude=28.6139,
            longitude=77.209,
            accuracy_meters=None,
        )
