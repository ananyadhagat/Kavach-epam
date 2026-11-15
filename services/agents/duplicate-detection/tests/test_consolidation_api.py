"""HTTP contract tests for the consolidation routes.

The tests drive the real FastAPI application with a SQLite-backed consolidation
service and a deterministic detection double. The M3 check route is untouched;
these tests only cover the additive ``/internal/v1/consolidation`` surface.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Mapping

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.api.app import create_app
from app.db.base import Base
from app.db.session import build_session_factory
from app.schemas.complaint import Complaint
from app.schemas.duplicate_response import Decision
from app.scoring import DecisionOutcome, RetrievalStatus
from app.scoring.decision_policy import RankedCandidate
from app.services.consolidation_service import ConsolidationService
from app.services.detection_service import DetectionResult
from tests.conftest import COMPLETE_CONTRACT_PAYLOAD

BASE = "/internal/v1/consolidation"
REPORTED_AT = datetime(2026, 10, 31, 13, 0, tzinfo=timezone.utc)


def detection(
    complaint_id: str,
    decision: Decision,
    *,
    matched_incident_id: str | None = None,
    leading_candidate_id: str | None = None,
    score: float | None = None,
) -> DetectionResult:
    candidates = (
        (
            RankedCandidate(
                incident_id=leading_candidate_id,
                rank=1,
                score=score,
                contradictions=(),
                reasons=(),
            ),
        )
        if leading_candidate_id is not None
        else ()
    )
    outcome = DecisionOutcome(
        decision=decision,
        matched_incident_id=matched_incident_id,
        score=score,
        reasons=("TEST_REASON",),
        signals={},
        candidates=candidates,
        policy_version="test-policy",
    )
    return DetectionResult(
        incident_id=complaint_id,
        outcome=outcome,
        retrieval_status=RetrievalStatus.COMPLETE,
    )


class StubDetectionService:
    def __init__(
        self,
        results: Mapping[str, DetectionResult],
    ) -> None:
        self._results = results

    def check_detailed(self, complaint: Complaint) -> DetectionResult:
        return self._results[complaint.complaint_id]


@pytest.fixture
def session_factory() -> sessionmaker[Session]:
    engine, factory = build_session_factory("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    try:
        yield factory
    finally:
        engine.dispose()


def build_client(
    session_factory: sessionmaker[Session],
    results: Mapping[str, DetectionResult],
) -> TestClient:
    service = ConsolidationService(
        session_factory,
        detection_service_factory=lambda repository: StubDetectionService(results),
    )
    app = create_app(consolidation_service=service)
    return TestClient(app)


def payload(complaint_id: str, description: str | None = None) -> dict[str, Any]:
    body = deepcopy(COMPLETE_CONTRACT_PAYLOAD)
    body["complaint_id"] = complaint_id
    if description is not None:
        body["description"] = description
    return body


# --------------------------------------------------------------------------- #
# Happy path
# --------------------------------------------------------------------------- #
def test_ingest_and_read_endpoints(session_factory) -> None:
    client = build_client(
        session_factory,
        {
            "INC-2026-001": detection("INC-2026-001", Decision.NEW),
            "INC-2026-002": detection(
                "INC-2026-002",
                Decision.DUPLICATE,
                matched_incident_id="INC-2026-001",
                score=0.94,
            ),
            "INC-2026-003": detection(
                "INC-2026-003",
                Decision.REVIEW_REQUIRED,
                leading_candidate_id="INC-2026-001",
                score=0.61,
            ),
        },
    )

    primary_response = client.post(
        f"{BASE}/complaints",
        json=payload("INC-2026-001"),
        headers={"Idempotency-Key": "key-primary"},
    )
    assert primary_response.status_code == 201
    primary = primary_response.json()
    assert primary["consolidation_status"] == "PRIMARY"
    assert primary["primary_complaint_id"] == "INC-2026-001"
    assert primary["review_id"] is None
    assert "Idempotent-Replay" not in primary_response.headers

    duplicate_response = client.post(
        f"{BASE}/complaints",
        json=payload("INC-2026-002", "Garbage is still overflowing."),
        headers={"Idempotency-Key": "key-duplicate"},
    )
    assert duplicate_response.status_code == 201
    duplicate = duplicate_response.json()
    assert duplicate["consolidation_status"] == "DUPLICATE"
    assert duplicate["group_id"] == primary["group_id"]
    assert duplicate["primary_complaint_id"] == "INC-2026-001"
    assert duplicate["active_duplicate_count"] == 1

    review_response = client.post(
        f"{BASE}/complaints",
        json=payload("INC-2026-003", "Possible overflow near the park."),
        headers={"Idempotency-Key": "key-review"},
    )
    assert review_response.status_code == 201
    review = review_response.json()
    assert review["consolidation_status"] == "PENDING_REVIEW"
    assert review["group_id"] is None
    assert review["review_id"] is not None
    assert review["matched_incident_id"] is None
    assert review["leading_candidate_id"] == "INC-2026-001"

    complaint_response = client.get(f"{BASE}/complaints/INC-2026-002")
    assert complaint_response.status_code == 200
    detail = complaint_response.json()
    assert detail["complaint"]["complaint_id"] == "INC-2026-002"
    assert detail["consolidation_status"] == "DUPLICATE"
    assert detail["group"]["group_id"] == primary["group_id"]
    assert datetime.fromisoformat(detail["received_at"]).tzinfo is not None

    group_response = client.get(f"{BASE}/groups/{primary['group_id']}")
    assert group_response.status_code == 200
    group = group_response.json()
    assert group["primary"]["complaint_id"] == "INC-2026-001"
    assert group["member_count"] == 2
    assert [item["complaint"]["complaint_id"] for item in group["duplicates"]] == [
        "INC-2026-002"
    ]
    assert datetime.fromisoformat(group["created_at"]).tzinfo is not None

    groups_response = client.get(f"{BASE}/groups")
    assert groups_response.status_code == 200
    groups = groups_response.json()
    assert groups["total"] == 1
    assert groups["limit"] == 50
    assert groups["offset"] == 0
    assert groups["items"][0]["group_id"] == primary["group_id"]

    queue_response = client.get(f"{BASE}/review-queue")
    assert queue_response.status_code == 200
    queue = queue_response.json()
    assert queue["total"] == 1
    assert queue["items"][0]["complaint"]["complaint_id"] == "INC-2026-003"
    assert queue["items"][0]["review_id"] == review["review_id"]
    assert queue["items"][0]["leading_candidate_id"] == "INC-2026-001"
    assert "matched_incident_id" not in queue["items"][0]


def test_pending_review_detail_has_no_group(session_factory) -> None:
    client = build_client(
        session_factory,
        {
            "INC-2026-001": detection(
                "INC-2026-001",
                Decision.REVIEW_REQUIRED,
                matched_incident_id=None,
                score=0.5,
            )
        },
    )
    created = client.post(
        f"{BASE}/complaints",
        json=payload("INC-2026-001"),
        headers={"Idempotency-Key": "key-review"},
    ).json()

    detail = client.get(f"{BASE}/complaints/INC-2026-001").json()

    assert detail["consolidation_status"] == "PENDING_REVIEW"
    assert detail["group"] is None
    assert detail["review"]["review_id"] == created["review_id"]


# --------------------------------------------------------------------------- #
# Idempotency
# --------------------------------------------------------------------------- #
def test_replay_returns_201_with_replay_header(session_factory) -> None:
    client = build_client(
        session_factory,
        {"INC-2026-001": detection("INC-2026-001", Decision.NEW)},
    )

    first = client.post(
        f"{BASE}/complaints",
        json=payload("INC-2026-001"),
        headers={"Idempotency-Key": "key-one"},
    )
    replay = client.post(
        f"{BASE}/complaints",
        json=payload("INC-2026-001"),
        headers={"Idempotency-Key": "key-one"},
    )

    assert first.status_code == 201
    assert replay.status_code == 201
    assert replay.headers["Idempotent-Replay"] == "true"
    assert replay.json()["idempotent_replay"] is True
    assert replay.json()["group_id"] == first.json()["group_id"]


def test_missing_idempotency_key_is_rejected(session_factory) -> None:
    client = build_client(session_factory, {})

    response = client.post(f"{BASE}/complaints", json=payload("INC-2026-001"))

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "INVALID_IDEMPOTENCY_KEY"


def test_invalid_idempotency_key_is_rejected(session_factory) -> None:
    client = build_client(session_factory, {})

    for key in ("   ", "has space", "x" * 129):
        response = client.post(
            f"{BASE}/complaints",
            json=payload("INC-2026-001"),
            headers={"Idempotency-Key": key},
        )
        assert response.status_code == 422
        assert response.json()["detail"]["code"] == "INVALID_IDEMPOTENCY_KEY"


def test_idempotency_key_reuse_conflict(session_factory) -> None:
    client = build_client(
        session_factory,
        {"INC-2026-001": detection("INC-2026-001", Decision.NEW)},
    )
    client.post(
        f"{BASE}/complaints",
        json=payload("INC-2026-001"),
        headers={"Idempotency-Key": "key-one"},
    )

    response = client.post(
        f"{BASE}/complaints",
        json=payload("INC-2026-001", "A different description."),
        headers={"Idempotency-Key": "key-one"},
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "IDEMPOTENCY_KEY_REUSED"


def test_duplicate_complaint_with_new_key_conflicts(session_factory) -> None:
    client = build_client(
        session_factory,
        {"INC-2026-001": detection("INC-2026-001", Decision.NEW)},
    )
    client.post(
        f"{BASE}/complaints",
        json=payload("INC-2026-001"),
        headers={"Idempotency-Key": "key-one"},
    )

    response = client.post(
        f"{BASE}/complaints",
        json=payload("INC-2026-001"),
        headers={"Idempotency-Key": "key-two"},
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "COMPLAINT_ALREADY_EXISTS"


# --------------------------------------------------------------------------- #
# Validation and not-found errors
# --------------------------------------------------------------------------- #
def test_invalid_payload_is_rejected(session_factory) -> None:
    client = build_client(session_factory, {})
    body = payload("INC-2026-001")
    body["reported_at"] = "not-a-timestamp"

    response = client.post(
        f"{BASE}/complaints",
        json=body,
        headers={"Idempotency-Key": "key-one"},
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "INVALID_COMPLAINT_PAYLOAD"


def test_malformed_json_is_rejected(session_factory) -> None:
    client = build_client(session_factory, {})

    response = client.post(
        f"{BASE}/complaints",
        content="{not valid json",
        headers={
            "Content-Type": "application/json",
            "Idempotency-Key": "key-one",
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "INVALID_COMPLAINT_PAYLOAD"


def test_unknown_complaint_and_group_return_404(session_factory) -> None:
    client = build_client(session_factory, {})

    complaint_response = client.get(f"{BASE}/complaints/UNKNOWN")
    assert complaint_response.status_code == 404
    assert complaint_response.json()["detail"]["code"] == "COMPLAINT_NOT_FOUND"

    group_response = client.get(
        f"{BASE}/groups/00000000-0000-0000-0000-000000000000"
    )
    assert group_response.status_code == 404
    assert group_response.json()["detail"]["code"] == "GROUP_NOT_FOUND"


def test_pagination_query_is_validated(session_factory) -> None:
    client = build_client(session_factory, {})

    response = client.get(f"{BASE}/groups", params={"limit": 0})

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "INVALID_COMPLAINT_PAYLOAD"


# --------------------------------------------------------------------------- #
# Default application compatibility
# --------------------------------------------------------------------------- #
def test_default_app_does_not_mount_consolidation_routes() -> None:
    client = TestClient(create_app())

    response = client.get(f"{BASE}/groups")

    assert response.status_code == 404
