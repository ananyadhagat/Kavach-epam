"""Shared pytest fixtures for the duplicate-detection test suite.

The two payloads below are copied verbatim from Agent 1's published draft
handoff contract (``a1-to-a2-draft-1``, sections 4 and 5) so the adapter and
service tests exercise the exact examples the contract shows. The contract
states that every value is an illustrative placeholder, not a captured API
response.

They are exposed as function-scoped fixtures returning deep copies, because the
adapter tests deliberately mutate payloads to prove rejection and non-mutation
behaviour.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

import pytest

#: Section 4 — complete illustrative payload from the Agent 1 contract.
COMPLETE_CONTRACT_PAYLOAD: dict[str, Any] = {
    "complaint_id": "INC-2026-001",
    "description": "Garbage is overflowing near the public park entrance.",
    "category": "WASTE_OVERFLOW",
    "location": {
        "facility_id": None,
        "location_id": None,
        "latitude": 23.2599,
        "longitude": 77.4126,
    },
    "reported_at": "2026-10-31T18:30:00+05:30",
    "image_hash": "a1b2c3d4e5f6",
    "kavach_agent1": {
        "contract_version": "a1-to-a2-draft-1",
        "request_id": "REQ-001",
        "category": "SANITATION",
        "incident_type": "WASTE_OVERFLOW",
        "incident_summary": "Garbage overflowing near the park.",
        "severity_recommendation": "MEDIUM",
        "location_source": "USER_SELECTED_PIN",
        "location_check_status": "PASSED",
        "image_sha256": ["example_sha256_hash"],
        "image_perceptual_hashes": ["a1b2c3d4e5f6"],
        "needs_clarification": False,
    },
}

#: Section 5 — proposed minimal payload. The contract notes this is a proposal
#: for the receiver, not a shape Agent 1 currently omits fields from.
MINIMAL_CONTRACT_PAYLOAD: dict[str, Any] = {
    "complaint_id": "INC-2026-002",
    "description": "Streetlight is not working.",
    "category": "BROKEN_STREETLIGHT",
    "location": {
        "facility_id": None,
        "location_id": None,
        "latitude": None,
        "longitude": None,
    },
    "reported_at": "2026-10-31T19:00:00+05:30",
    "image_hash": None,
    "kavach_agent1": {
        "contract_version": "a1-to-a2-draft-1",
    },
}


@pytest.fixture
def complete_contract_payload() -> dict[str, Any]:
    """A fresh copy of the contract's complete illustrative payload."""
    return deepcopy(COMPLETE_CONTRACT_PAYLOAD)


@pytest.fixture
def minimal_contract_payload() -> dict[str, Any]:
    """A fresh copy of the contract's proposed minimal payload."""
    return deepcopy(MINIMAL_CONTRACT_PAYLOAD)
