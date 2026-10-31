"""Tests for the Agent 1 -> Agent 2 handoff adapter.

The adapter consumes the draft handoff envelope produced by Agent 1's
``build_duplicate_detection_request()`` and returns the existing ``Complaint``
model. It does not re-implement Agent 1's upstream field mapping.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.adapters.incident_payload import (
    HANDOFF_CONTRACT_VERSION,
    IncidentPayloadError,
    to_complaint,
)
from app.schemas.complaint import Complaint


def handoff_payload(**overrides):
    """Build a representative Agent 1 handoff payload, applying overrides last."""
    payload = {
        "complaint_id": "INC-2026-0001",
        "description": "Dustbin near the main gate is overflowing and blocking the path",
        "category": "WASTE_OVERFLOW",
        "location": {
            "facility_id": None,
            "location_id": None,
            "latitude": 23.25,
            "longitude": 77.4,
        },
        "reported_at": "2026-10-17T09:30:00+00:00",
        "image_hash": "0123456789abcdef",
        "kavach_agent1": {
            "contract_version": HANDOFF_CONTRACT_VERSION,
            "request_id": "REQ-1",
            "category": "SANITATION",
            "incident_type": "WASTE_OVERFLOW",
            "incident_summary": "Overflowing dustbin at the main gate",
            "severity_recommendation": "MEDIUM",
            "location_source": "USER_SELECTED_PIN",
            "location_check_status": "CONSISTENT",
            "image_sha256": ["a" * 64],
            "image_perceptual_hashes": ["0123456789abcdef"],
            "needs_clarification": False,
        },
    }
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------- #
# Valid handoff payloads
# --------------------------------------------------------------------------- #


def test_full_handoff_payload_maps_to_complaint():
    complaint = to_complaint(handoff_payload())

    assert isinstance(complaint, Complaint)
    assert complaint.complaint_id == "INC-2026-0001"
    assert complaint.description == (
        "Dustbin near the main gate is overflowing and blocking the path"
    )
    assert complaint.category == "WASTE_OVERFLOW"
    assert complaint.location is not None
    assert complaint.location.facility_id is None
    assert complaint.location.location_id is None
    assert complaint.location.latitude == 23.25
    assert complaint.location.longitude == 77.4
    assert complaint.reported_at == datetime(
        2026, 10, 17, 9, 30, tzinfo=timezone.utc
    )
    assert complaint.image_hash == "0123456789abcdef"


def test_kavach_agent1_context_is_ignored():
    payload = handoff_payload(kavach_agent1={"anything": "opaque"})
    complaint = to_complaint(payload)

    assert complaint.complaint_id == "INC-2026-0001"
    assert not hasattr(complaint, "kavach_agent1")


def test_kavach_agent1_is_optional():
    payload = handoff_payload()
    del payload["kavach_agent1"]

    assert to_complaint(payload).complaint_id == "INC-2026-0001"


def test_minimal_payload_only_requires_complaint_id():
    complaint = to_complaint({"complaint_id": "INC-MINIMAL"})

    assert complaint.complaint_id == "INC-MINIMAL"
    assert complaint.description is None
    assert complaint.category is None
    assert complaint.location is None
    assert complaint.reported_at is None
    assert complaint.image_hash is None


def test_missing_optional_fields_are_preserved_as_none():
    payload = handoff_payload(
        description=None,
        category=None,
        location=None,
        reported_at=None,
        image_hash=None,
    )
    complaint = to_complaint(payload)

    assert complaint.description is None
    assert complaint.category is None
    assert complaint.location is None
    assert complaint.reported_at is None
    assert complaint.image_hash is None


def test_blank_optional_strings_normalise_to_none():
    complaint = to_complaint(
        handoff_payload(description="   ", category="", image_hash=" ")
    )

    assert complaint.description is None
    assert complaint.category is None
    assert complaint.image_hash is None


def test_identifier_only_location_is_valid():
    complaint = to_complaint(
        handoff_payload(
            location={
                "facility_id": "FAC-CENTRAL-MARKET",
                "location_id": "LOC-CM-GATE-NORTH",
            }
        )
    )

    assert complaint.location is not None
    assert complaint.location.facility_id == "FAC-CENTRAL-MARKET"
    assert complaint.location.location_id == "LOC-CM-GATE-NORTH"
    assert complaint.location.latitude is None
    assert complaint.location.longitude is None


def test_adapter_does_not_mutate_the_input_payload():
    payload = handoff_payload()
    original = deepcopy(payload)

    to_complaint(payload)

    assert payload == original


# --------------------------------------------------------------------------- #
# Invalid field values
# --------------------------------------------------------------------------- #


def test_missing_complaint_id_is_rejected():
    payload = handoff_payload()
    del payload["complaint_id"]

    with pytest.raises(ValidationError):
        to_complaint(payload)


@pytest.mark.parametrize("complaint_id", ["", "   ", "x" * 65])
def test_invalid_complaint_id_is_rejected(complaint_id):
    with pytest.raises(ValidationError):
        to_complaint(handoff_payload(complaint_id=complaint_id))


@pytest.mark.parametrize(
    "reported_at",
    [
        "2026-10-17T09:30:00",  # no UTC offset
        "not-a-timestamp",
    ],
)
def test_invalid_reported_at_is_rejected(reported_at):
    with pytest.raises(ValidationError):
        to_complaint(handoff_payload(reported_at=reported_at))


def test_lone_coordinate_is_rejected():
    with pytest.raises(ValidationError, match="supplied together"):
        to_complaint(
            handoff_payload(
                location={
                    "facility_id": None,
                    "location_id": None,
                    "latitude": 23.25,
                    "longitude": None,
                }
            )
        )


@pytest.mark.parametrize(
    "location",
    [
        {
            "facility_id": None,
            "location_id": None,
            "latitude": 91.0,
            "longitude": 77.4,
        },
        {
            "facility_id": None,
            "location_id": None,
            "latitude": 23.25,
            "longitude": 181.0,
        },
        {
            "facility_id": None,
            "location_id": None,
            "latitude": 23.25,
            "longitude": 77.4,
            "ward": "unexpected",
        },
    ],
)
def test_invalid_location_is_rejected(location):
    with pytest.raises(ValidationError):
        to_complaint(handoff_payload(location=location))


@pytest.mark.parametrize(
    "overrides",
    [
        {"description": "x" * 5001},
        {"category": "x" * 65},
        {"image_hash": "x" * 129},
    ],
)
def test_field_length_limits_are_enforced(overrides):
    with pytest.raises(ValidationError):
        to_complaint(handoff_payload(**overrides))


# --------------------------------------------------------------------------- #
# Ambiguous or unsupported handoff fields
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("incident_id", "INC-2026-0001"),
        ("complaint_text", "raw citizen text"),
        ("incident_summary", "model summary"),
        ("created_at", "2026-10-17T09:30:00+00:00"),
        ("submitted_at", "2026-10-17T09:30:00+00:00"),
        ("incident_type", "WASTE_OVERFLOW"),
        ("request_id", "REQ-1"),
        ("image_ref", "s3://bucket/image.jpg"),
    ],
)
def test_raw_or_ambiguous_upstream_field_is_rejected(field, value):
    payload = handoff_payload()
    payload[field] = value

    with pytest.raises(IncidentPayloadError) as excinfo:
        to_complaint(payload)

    assert field in excinfo.value.unsupported_fields
    assert field in str(excinfo.value)


def test_unknown_top_level_field_is_rejected():
    with pytest.raises(IncidentPayloadError, match="unexpected_field"):
        to_complaint(handoff_payload(unexpected_field="x"))


@pytest.mark.parametrize("field", ["options", "candidates"])
def test_http_only_fields_are_rejected(field):
    with pytest.raises(IncidentPayloadError) as excinfo:
        to_complaint(handoff_payload(**{field: {}}))

    assert field in excinfo.value.unsupported_fields


def test_incident_summary_is_not_silently_used_as_description():
    payload = {
        "complaint_id": "INC-2026-0001",
        "incident_summary": "A model-written summary",
    }

    with pytest.raises(IncidentPayloadError) as excinfo:
        to_complaint(payload)

    assert "incident_summary" in excinfo.value.unsupported_fields


def test_non_mapping_payload_is_rejected():
    with pytest.raises(IncidentPayloadError, match="must be a mapping"):
        to_complaint(["not", "a", "mapping"])  # type: ignore[arg-type]
