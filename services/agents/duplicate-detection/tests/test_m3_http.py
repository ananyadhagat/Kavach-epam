"""HTTP contract tests for ``POST /internal/v1/duplicate-detection/check``.

These tests exercise the transport edge only. They inject a deterministic
service double so the exact Agent 3 wire contract can be asserted without
loading an embedding model or depending on comparator thresholds.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from app.api.app import create_app
from app.repositories.base import RetrievalFailure
from app.schemas.complaint import Complaint
from app.schemas.duplicate_response import Decision
from app.scoring import DecisionOutcome, RankedCandidate, RetrievalStatus
from app.services.detection_service import DetectionResult

ENDPOINT = "/internal/v1/duplicate-detection/check"
INCIDENT_ID = "INC-2026-001"
POLICY_VERSION = "v1-draft"

#: Exactly the eleven top-level fields required by the Agent 3 contract.
CONTRACT_FIELDS = {
    "check_id",
    "incident_id",
    "decision",
    "processing_status",
    "policy_version",
    "checked_at",
    "matched_incident_id",
    "score",
    "reason_codes",
    "candidates",
    "error",
}


# --------------------------------------------------------------------------- #
# Deterministic doubles
# --------------------------------------------------------------------------- #
class StubService:
    """Service double returning a prepared result or raising a prepared error."""

    def __init__(
        self,
        result: DetectionResult | None = None,
        *,
        error: BaseException | None = None,
    ) -> None:
        self.result = result
        self.error = error
        self.received: list[Complaint] = []

    def check_detailed(self, complaint: Complaint) -> DetectionResult:
        self.received.append(complaint)
        if self.error is not None:
            raise self.error
        assert self.result is not None
        return self.result


def _candidate(
    incident_id: str,
    score: float | None,
    *,
    rank: int = 1,
    reasons: tuple[str, ...] = (),
    contradictions: tuple[str, ...] = (),
) -> RankedCandidate:
    return RankedCandidate(
        incident_id=incident_id,
        rank=rank,
        score=score,
        contradictions=contradictions,
        reasons=reasons,
    )


def _result(
    decision: Decision,
    *,
    status: RetrievalStatus = RetrievalStatus.COMPLETE,
    candidates: tuple[RankedCandidate, ...] = (),
    reasons: tuple[str, ...] = (),
    matched_incident_id: str | None = None,
    score: float | None = None,
    failure: RetrievalFailure | None = None,
    incident_id: str = INCIDENT_ID,
) -> DetectionResult:
    return DetectionResult(
        incident_id=incident_id,
        outcome=DecisionOutcome(
            decision=decision,
            matched_incident_id=matched_incident_id,
            score=score,
            reasons=reasons,
            signals={},
            candidates=candidates,
            policy_version=POLICY_VERSION,
        ),
        retrieval_status=status,
        retrieval_failure=failure,
    )


@pytest.fixture()
def payload(complete_contract_payload: dict[str, Any]) -> dict[str, Any]:
    return complete_contract_payload


def _client(service: StubService) -> TestClient:
    return TestClient(create_app(service=service))


# --------------------------------------------------------------------------- #
# Happy path and exact envelope
# --------------------------------------------------------------------------- #
def test_response_has_exactly_the_eleven_contract_fields(payload):
    service = StubService(
        _result(
            Decision.DUPLICATE,
            candidates=(_candidate("CMP-2026-0101", 0.91),),
            reasons=("SCORE_ABOVE_HIGH_THRESHOLD",),
            matched_incident_id="CMP-2026-0101",
            score=0.91,
        )
    )

    response = _client(service).post(ENDPOINT, json=payload)

    assert response.status_code == 200
    body = response.json()
    assert set(body) == CONTRACT_FIELDS
    assert body["incident_id"] == INCIDENT_ID
    assert body["decision"] == "DUPLICATE"
    assert body["processing_status"] == "COMPLETED"
    assert body["policy_version"] == POLICY_VERSION
    assert body["matched_incident_id"] == "CMP-2026-0101"
    assert body["score"] == 0.91
    assert body["reason_codes"] == ["SCORE_ABOVE_HIGH_THRESHOLD"]
    assert body["candidates"] == [
        {
            "matched_incident_id": "CMP-2026-0101",
            "similarity_score": 0.91,
            "reason_codes": [],
        }
    ]
    assert body["error"] is None


def test_check_id_is_a_uuid_and_checked_at_is_utc(payload):
    service = StubService(
        _result(
            Decision.DUPLICATE,
            candidates=(_candidate("CMP-2026-0101", 0.90),),
            matched_incident_id="CMP-2026-0101",
            score=0.90,
        )
    )

    body = _client(service).post(ENDPOINT, json=payload).json()

    assert str(UUID(body["check_id"])) == body["check_id"]
    assert body["checked_at"].endswith("Z")
    parsed = datetime.fromisoformat(body["checked_at"].replace("Z", "+00:00"))
    assert parsed.tzinfo is not None
    assert parsed.utcoffset() == timezone.utc.utcoffset(None)


def test_route_passes_the_adapted_complaint_to_the_service(payload):
    service = StubService(
        _result(
            Decision.NEW,
            reasons=("NO_ELIGIBLE_CANDIDATES",),
        )
    )

    _client(service).post(ENDPOINT, json=payload)

    assert len(service.received) == 1
    complaint = service.received[0]
    assert complaint.complaint_id == INCIDENT_ID
    assert complaint.description == payload["description"]
    assert complaint.image_hash == payload["image_hash"]


def test_default_app_is_wired_with_an_empty_repository(payload):
    # End-to-end with the real service and the default empty in-memory store.
    body = TestClient(create_app()).post(ENDPOINT, json=payload).json()

    assert body["decision"] == "NEW"
    assert body["processing_status"] == "COMPLETED"
    assert body["matched_incident_id"] is None
    assert body["score"] is None
    assert body["candidates"] == []
    assert body["error"] is None


# --------------------------------------------------------------------------- #
# Decision-specific mapping
# --------------------------------------------------------------------------- #
def test_duplicate_repeats_the_leading_candidate(payload):
    service = StubService(
        _result(
            Decision.DUPLICATE,
            candidates=(
                _candidate("CMP-2026-0101", 0.91),
                _candidate("CMP-2026-0102", 0.88),
            ),
            reasons=("SCORE_ABOVE_HIGH_THRESHOLD",),
            matched_incident_id="CMP-2026-0101",
            score=0.91,
        )
    )

    body = _client(service).post(ENDPOINT, json=payload).json()

    assert body["decision"] == "DUPLICATE"
    assert body["matched_incident_id"] == "CMP-2026-0101"
    assert body["score"] == 0.91
    assert [c["matched_incident_id"] for c in body["candidates"]] == [
        "CMP-2026-0101",
        "CMP-2026-0102",
    ]


def test_review_required_returns_the_highest_scoring_candidate(payload):
    service = StubService(
        _result(
            Decision.REVIEW_REQUIRED,
            candidates=(_candidate("CMP-2026-0101", 0.72),),
            reasons=("SCORE_BETWEEN_THRESHOLDS",),
        )
    )

    body = _client(service).post(ENDPOINT, json=payload).json()

    assert body["decision"] == "REVIEW_REQUIRED"
    assert body["processing_status"] == "COMPLETED"
    assert body["matched_incident_id"] == "CMP-2026-0101"
    assert body["score"] == 0.72
    assert body["error"] is None


def test_new_nulls_match_and_score_but_keeps_below_threshold_candidates(payload):
    service = StubService(
        _result(
            Decision.NEW,
            candidates=(_candidate("CMP-2026-0101", 0.41),),
            reasons=("SCORE_BELOW_LOW_THRESHOLD",),
        )
    )

    body = _client(service).post(ENDPOINT, json=payload).json()

    assert body["decision"] == "NEW"
    assert body["matched_incident_id"] is None
    assert body["score"] is None
    assert body["candidates"] == [
        {
            "matched_incident_id": "CMP-2026-0101",
            "similarity_score": 0.41,
            "reason_codes": [],
        }
    ]


def test_candidates_are_sorted_by_descending_similarity_score(payload):
    # The policy is expected to order candidates; the mapper must still emit a
    # contract-valid order even if a future caller hands them over unsorted.
    service = StubService(
        _result(
            Decision.REVIEW_REQUIRED,
            candidates=(
                _candidate("CMP-LOW", 0.70),
                _candidate("CMP-HIGH", 0.95),
            ),
            reasons=("INSUFFICIENT_EVIDENCE",),
        )
    )

    body = _client(service).post(ENDPOINT, json=payload).json()

    assert [c["matched_incident_id"] for c in body["candidates"]] == [
        "CMP-HIGH",
        "CMP-LOW",
    ]
    assert body["matched_incident_id"] == "CMP-HIGH"
    assert body["score"] == 0.95


def test_candidates_without_a_score_are_omitted(payload):
    service = StubService(
        _result(
            Decision.REVIEW_REQUIRED,
            candidates=(
                _candidate("CMP-UNSCORABLE", None),
                _candidate("CMP-SCORED", 0.66),
            ),
            reasons=("INSUFFICIENT_EVIDENCE",),
        )
    )

    body = _client(service).post(ENDPOINT, json=payload).json()

    assert [c["matched_incident_id"] for c in body["candidates"]] == [
        "CMP-SCORED"
    ]
    assert body["matched_incident_id"] == "CMP-SCORED"
    assert body["score"] == 0.66


def test_candidate_reason_codes_preserve_policy_codes_and_contradictions(payload):
    service = StubService(
        _result(
            Decision.REVIEW_REQUIRED,
            candidates=(
                _candidate(
                    "CMP-2026-0101",
                    0.75,
                    reasons=("SCORE_BETWEEN_THRESHOLDS",),
                    contradictions=("CONTRADICTION_LOCATION_MISMATCH",),
                ),
            ),
            reasons=("SCORE_BETWEEN_THRESHOLDS",),
        )
    )

    body = _client(service).post(ENDPOINT, json=payload).json()

    assert body["candidates"][0]["reason_codes"] == [
        "SCORE_BETWEEN_THRESHOLDS",
        "CONTRADICTION_LOCATION_MISMATCH",
    ]


# --------------------------------------------------------------------------- #
# Partial and failed retrieval are HTTP 200 business outcomes
# --------------------------------------------------------------------------- #
def test_partial_retrieval_is_200_review_required_and_never_duplicate(payload):
    service = StubService(
        _result(
            # The policy can still say DUPLICATE from the candidates it saw.
            Decision.DUPLICATE,
            status=RetrievalStatus.INCOMPLETE,
            candidates=(_candidate("CMP-2026-0101", 0.93),),
            reasons=("SCORE_ABOVE_HIGH_THRESHOLD",),
            matched_incident_id="CMP-2026-0101",
            score=0.93,
            failure=RetrievalFailure(
                "RETRIEVAL_COMPLETENESS_UNKNOWN",
                "The index may not have returned every candidate.",
            ),
        )
    )

    response = _client(service).post(ENDPOINT, json=payload)

    assert response.status_code == 200
    body = response.json()
    assert body["decision"] == "REVIEW_REQUIRED"
    assert body["processing_status"] == "PARTIAL"
    assert body["error"] == {
        "code": "RETRIEVAL_COMPLETENESS_UNKNOWN",
        "message": "The index may not have returned every candidate.",
    }
    assert "CANDIDATE_RETRIEVAL_INCOMPLETE" in body["reason_codes"]
    # Valid candidates discovered before the completeness gap are preserved.
    assert body["matched_incident_id"] == "CMP-2026-0101"
    assert body["score"] == 0.93
    assert len(body["candidates"]) == 1


def test_partial_retrieval_without_candidates_is_review_not_new(payload):
    service = StubService(
        _result(
            Decision.REVIEW_REQUIRED,
            status=RetrievalStatus.INCOMPLETE,
            reasons=("CANDIDATE_RETRIEVAL_INCOMPLETE",),
            failure=RetrievalFailure(
                "RETRIEVAL_COMPLETENESS_UNKNOWN",
                "Candidate retrieval may be incomplete.",
            ),
        )
    )

    body = _client(service).post(ENDPOINT, json=payload).json()

    assert body["decision"] == "REVIEW_REQUIRED"
    assert body["processing_status"] == "PARTIAL"
    assert body["matched_incident_id"] is None
    assert body["score"] is None
    assert body["candidates"] == []
    assert body["error"]["code"] == "RETRIEVAL_COMPLETENESS_UNKNOWN"


def test_failed_retrieval_is_200_review_required_with_error(payload):
    service = StubService(
        _result(
            Decision.REVIEW_REQUIRED,
            status=RetrievalStatus.FAILED,
            reasons=("CANDIDATE_RETRIEVAL_FAILED",),
            failure=RetrievalFailure(
                "RETRIEVAL_TIMEOUT",
                "The vector store timed out.",
            ),
        )
    )

    response = _client(service).post(ENDPOINT, json=payload)

    assert response.status_code == 200
    body = response.json()
    assert body["decision"] == "REVIEW_REQUIRED"
    assert body["processing_status"] == "FAILED"
    assert body["error"] == {
        "code": "RETRIEVAL_TIMEOUT",
        "message": "The vector store timed out.",
    }
    assert "CANDIDATE_RETRIEVAL_FAILED" in body["reason_codes"]
    assert body["matched_incident_id"] is None
    assert body["score"] is None


# --------------------------------------------------------------------------- #
# Request validation
# --------------------------------------------------------------------------- #
def test_missing_required_field_returns_422_and_no_contract_body(payload):
    del payload["complaint_id"]

    response = _client(StubService()).post(ENDPOINT, json=payload)

    assert response.status_code == 422
    body = response.json()
    assert body["detail"]["code"] == "INVALID_INCIDENT_PAYLOAD"
    assert set(body) == {"detail"}
    assert "check_id" not in body


def test_unsupported_field_returns_422(payload):
    payload["unexpected"] = "value"

    response = _client(StubService()).post(ENDPOINT, json=payload)

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "INVALID_INCIDENT_PAYLOAD"


def test_non_mapping_json_returns_422(payload):
    response = _client(StubService()).post(ENDPOINT, json=["not", "a", "mapping"])

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "INVALID_INCIDENT_PAYLOAD"


def test_malformed_json_returns_422():
    response = _client(StubService()).post(
        ENDPOINT,
        content=b"{not valid json",
        headers={"content-type": "application/json"},
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "INVALID_INCIDENT_PAYLOAD"


def test_missing_body_returns_422():
    response = _client(StubService()).post(ENDPOINT)

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "INVALID_INCIDENT_PAYLOAD"


# --------------------------------------------------------------------------- #
# Infrastructure failures never fabricate a duplicate-check result
# --------------------------------------------------------------------------- #
def test_timeout_returns_504_and_no_contract_body(payload):
    service = StubService(error=TimeoutError("upstream timed out"))

    response = _client(service).post(ENDPOINT, json=payload)

    assert response.status_code == 504
    body = response.json()
    assert body["detail"]["code"] == "DUPLICATE_CHECK_TIMEOUT"
    assert "check_id" not in body


def test_unexpected_failure_returns_500_and_no_contract_body(payload):
    service = StubService(error=RuntimeError("programming bug"))

    response = _client(service).post(ENDPOINT, json=payload)

    assert response.status_code == 500
    body = response.json()
    assert body["detail"]["code"] == "INTERNAL_ERROR"
    assert "check_id" not in body


def test_422_does_not_call_the_service(payload):
    payload["reported_at"] = "not-a-timestamp"
    service = StubService(_result(Decision.NEW))

    response = _client(service).post(ENDPOINT, json=payload)

    assert response.status_code == 422
    assert service.received == []
