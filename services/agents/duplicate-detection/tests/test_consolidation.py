"""Service-level tests for complaint consolidation.

These tests exercise persistence and the M3 decision mapping without loading
the embedding model. A deterministic detection double returns one pre-programmed
:class:`DetectionResult` per complaint id, so the assertions focus on
consolidation semantics rather than similarity thresholds.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Mapping

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.comparators.factory import build_core_comparators
from app.config.settings import ComparatorSettings, Settings
from app.db.base import Base
from app.db.models import (
    ComplaintRecord,
    ConsolidationGroup,
    ConsolidationLink,
    ConsolidationRequest,
    ConsolidationReview,
)
from app.db.session import build_session_factory
from app.repositories.sql_complaint import SessionComplaintRepository
from app.schemas.complaint import Complaint, Location
from app.schemas.duplicate_response import Decision
from app.scoring import DecisionOutcome, RetrievalStatus
from app.services.consolidation_errors import (
    COMPLAINT_ALREADY_EXISTS,
    COMPLAINT_NOT_CONSOLIDATED,
    COMPLAINT_NOT_FOUND,
    GROUP_CLOSED,
    GROUP_NOT_FOUND,
    IDEMPOTENCY_KEY_REUSED,
    MATCHED_PRIMARY_NOT_CONSOLIDATED,
    MATCHED_PRIMARY_NOT_FOUND,
    ConsolidationError,
)
from app.services.consolidation_service import (
    ConsolidationService,
    fingerprint_complaint,
)
from app.services.detection_service import DetectionResult

REPORTED_AT = datetime(2026, 10, 31, 13, 0, tzinfo=timezone.utc)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def complaint(complaint_id: str, description: str = "Garbage overflow") -> Complaint:
    """Build a valid canonical complaint for tests."""

    return Complaint(
        complaint_id=complaint_id,
        description=description,
        category="WASTE_OVERFLOW",
        location=Location(latitude=23.2599, longitude=77.4126),
        reported_at=REPORTED_AT,
        image_hash=None,
    )


def detection(
    complaint_id: str,
    decision: Decision,
    *,
    matched_incident_id: str | None = None,
    score: float | None = None,
    reasons: tuple[str, ...] = ("TEST_REASON",),
) -> DetectionResult:
    """Build a deterministic detection result."""

    outcome = DecisionOutcome(
        decision=decision,
        matched_incident_id=matched_incident_id,
        score=score,
        reasons=reasons,
        signals={},
        candidates=(),
        policy_version="test-policy",
    )
    return DetectionResult(
        incident_id=complaint_id,
        outcome=outcome,
        retrieval_status=RetrievalStatus.COMPLETE,
    )


class StubDetectionService:
    """Detection double that also records the candidates M3 would have seen."""

    def __init__(
        self,
        repository: SessionComplaintRepository,
        results: Mapping[str, DetectionResult],
    ) -> None:
        self._repository = repository
        self._results = results
        self.calls: list[str] = []
        self.seen_candidates: dict[str, list[str]] = {}

    def check_detailed(self, complaint: Complaint) -> DetectionResult:
        self.calls.append(complaint.complaint_id)
        self.seen_candidates[complaint.complaint_id] = [
            candidate.complaint_id
            for candidate in self._repository.list_candidates(
                exclude_complaint_id=complaint.complaint_id
            )
        ]
        return self._results[complaint.complaint_id]


def build_service(
    session_factory: sessionmaker[Session],
    results: Mapping[str, DetectionResult],
) -> tuple[ConsolidationService, list[StubDetectionService]]:
    """Build a service whose M3 calls are served by the stub."""

    stubs: list[StubDetectionService] = []

    def factory(repository: SessionComplaintRepository) -> StubDetectionService:
        stub = StubDetectionService(repository, results)
        stubs.append(stub)
        return stub

    service = ConsolidationService(
        session_factory,
        detection_service_factory=factory,
    )
    return service, stubs


@pytest.fixture
def session_factory() -> sessionmaker[Session]:
    engine, factory = build_session_factory("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    try:
        yield factory
    finally:
        engine.dispose()


def _count(session_factory: sessionmaker[Session], model) -> int:
    with session_factory() as session:
        return int(
            session.execute(select(func.count()).select_from(model)).scalar_one()
        )


def _group_state(
    session_factory: sessionmaker[Session], group_id: str
) -> tuple[ConsolidationGroup, list[ConsolidationLink]]:
    with session_factory() as session:
        group = session.get(ConsolidationGroup, group_id)
        assert group is not None
        links = list(
            session.execute(
                select(ConsolidationLink).order_by(
                    ConsolidationLink.linked_at,
                    ConsolidationLink.complaint_id,
                )
            ).scalars()
        )
        return group, links


# --------------------------------------------------------------------------- #
# NEW: primary and group creation
# --------------------------------------------------------------------------- #
def test_new_creates_primary_link_and_group(session_factory) -> None:
    service, stubs = build_service(
        session_factory, {"CMP-A": detection("CMP-A", Decision.NEW)}
    )

    result = service.ingest(complaint("CMP-A"), "key-a")

    assert result.consolidation_status.value == "PRIMARY"
    assert result.decision is Decision.NEW
    assert result.primary_complaint_id == "CMP-A"
    assert result.group_id is not None
    assert result.review_id is None
    assert result.active_duplicate_count == 0
    assert result.historical_duplicate_count == 0
    assert result.idempotent_replay is False

    group, links = _group_state(session_factory, result.group_id)
    assert group.primary_complaint_id == "CMP-A"
    assert group.status == "OPEN"
    assert group.active_duplicate_count == 0
    assert group.historical_duplicate_count == 0
    assert [link.role for link in links] == ["PRIMARY"]
    assert links[0].complaint_id == "CMP-A"
    assert links[0].matched_incident_id is None

    assert _count(session_factory, ComplaintRecord) == 1
    assert _count(session_factory, ConsolidationGroup) == 1
    assert _count(session_factory, ConsolidationLink) == 1
    assert _count(session_factory, ConsolidationRequest) == 1
    assert len(stubs) == 1
    assert stubs[0].calls == ["CMP-A"]
    assert stubs[0].seen_candidates["CMP-A"] == []


def test_new_mapping_returns_timezone_aware_timestamps(session_factory) -> None:
    service, _ = build_service(
        session_factory, {"CMP-A": detection("CMP-A", Decision.NEW)}
    )
    result = service.ingest(complaint("CMP-A"), "key-a")

    detail = service.get_complaint_detail("CMP-A")
    group = service.get_group_detail(result.group_id)

    assert detail.received_at.tzinfo is not None
    assert detail.received_at.utcoffset() is not None
    assert group.created_at.tzinfo is not None
    assert group.created_at.utcoffset() is not None


# --------------------------------------------------------------------------- #
# DUPLICATE: direct and transitive canonical resolution
# --------------------------------------------------------------------------- #
def test_duplicate_links_to_group_primary(session_factory) -> None:
    service, _ = build_service(
        session_factory,
        {
            "CMP-A": detection("CMP-A", Decision.NEW),
            "CMP-B": detection(
                "CMP-B",
                Decision.DUPLICATE,
                matched_incident_id="CMP-A",
                score=0.93,
            ),
        },
    )
    primary = service.ingest(complaint("CMP-A"), "key-a")
    duplicate = service.ingest(complaint("CMP-B"), "key-b")

    assert duplicate.consolidation_status.value == "DUPLICATE"
    assert duplicate.group_id == primary.group_id
    assert duplicate.primary_complaint_id == "CMP-A"
    assert duplicate.matched_incident_id == "CMP-A"
    assert duplicate.active_duplicate_count == 1
    assert duplicate.historical_duplicate_count == 1

    group = service.get_group_detail(primary.group_id)
    assert group.primary.complaint_id == "CMP-A"
    assert group.member_count == 2
    assert [member.complaint.complaint_id for member in group.duplicates] == [
        "CMP-B"
    ]
    assert group.duplicates[0].match_score == 0.93
    assert group.duplicates[0].linked_at.tzinfo is not None


def test_duplicate_matching_a_duplicate_resolves_to_canonical_primary(
    session_factory,
) -> None:
    service, _ = build_service(
        session_factory,
        {
            "CMP-A": detection("CMP-A", Decision.NEW),
            "CMP-B": detection(
                "CMP-B",
                Decision.DUPLICATE,
                matched_incident_id="CMP-A",
                score=0.91,
            ),
            "CMP-C": detection(
                "CMP-C",
                Decision.DUPLICATE,
                matched_incident_id="CMP-B",
                score=0.88,
            ),
        },
    )
    primary = service.ingest(complaint("CMP-A"), "key-a")
    service.ingest(complaint("CMP-B"), "key-b")
    transitive = service.ingest(complaint("CMP-C"), "key-c")

    assert transitive.group_id == primary.group_id
    assert transitive.primary_complaint_id == "CMP-A"
    assert transitive.matched_incident_id == "CMP-B"
    assert transitive.active_duplicate_count == 2
    assert transitive.historical_duplicate_count == 2

    group = service.get_group_detail(primary.group_id)
    by_id = {
        member.complaint.complaint_id: member for member in group.duplicates
    }
    assert set(by_id) == {"CMP-B", "CMP-C"}
    assert by_id["CMP-C"].matched_incident_id == "CMP-B"
    assert group.active_duplicate_count == 2
    assert group.historical_duplicate_count == 2


# --------------------------------------------------------------------------- #
# REVIEW_REQUIRED: pending review, no link, no count change
# --------------------------------------------------------------------------- #
def test_review_required_creates_review_without_link_or_count(
    session_factory,
) -> None:
    service, _ = build_service(
        session_factory,
        {
            "CMP-A": detection("CMP-A", Decision.NEW),
            "CMP-B": detection(
                "CMP-B",
                Decision.REVIEW_REQUIRED,
                score=0.66,
            ),
        },
    )
    primary = service.ingest(complaint("CMP-A"), "key-a")
    review = service.ingest(complaint("CMP-B"), "key-b")

    assert review.consolidation_status.value == "PENDING_REVIEW"
    assert review.group_id is None
    assert review.primary_complaint_id is None
    assert review.review_id is not None
    assert review.matched_incident_id is None
    assert review.leading_candidate_id is None

    group, links = _group_state(session_factory, primary.group_id)
    assert group.active_duplicate_count == 0
    assert group.historical_duplicate_count == 0
    assert [link.complaint_id for link in links] == ["CMP-A"]

    with session_factory() as session:
        stored = session.get(ConsolidationReview, review.review_id)
        assert stored is not None
        assert stored.complaint_id == "CMP-B"
        assert stored.status == "OPEN"
        assert stored.decision == "REVIEW_REQUIRED"
        assert stored.leading_candidate_id is None
        assert stored.resolved_at is None
        assert session.execute(
            select(ConsolidationLink).where(
                ConsolidationLink.complaint_id == "CMP-B"
            )
        ).scalar_one_or_none() is None

    detail = service.get_complaint_detail("CMP-B")
    assert detail.consolidation_status.value == "PENDING_REVIEW"
    assert detail.group is None
    assert detail.review is not None
    assert detail.review.review_id == review.review_id
    assert detail.review.created_at.tzinfo is not None

    queue = service.list_review_queue()
    assert queue.total == 1
    assert queue.items[0].complaint.complaint_id == "CMP-B"
    assert queue.items[0].reasons == ["TEST_REASON"]


def test_review_complaint_is_excluded_from_m3_candidate_pool(
    session_factory,
) -> None:
    service, _ = build_service(
        session_factory,
        {
            "CMP-A": detection("CMP-A", Decision.NEW),
            "CMP-B": detection(
                "CMP-B",
                Decision.REVIEW_REQUIRED,
                score=0.62,
            ),
        },
    )
    service.ingest(complaint("CMP-A"), "key-a")
    service.ingest(complaint("CMP-B"), "key-b")

    with session_factory() as session:
        candidates = SessionComplaintRepository(session).list_candidates()

    assert [candidate.complaint_id for candidate in candidates] == ["CMP-A"]


def test_review_required_preserves_real_policy_leading_candidate(
    session_factory,
) -> None:
    """The real policy names a leading candidate; review persistence must keep it."""

    settings = Settings(comparators=ComparatorSettings(text_backend="tfidf"))
    service = ConsolidationService(
        session_factory,
        comparators=build_core_comparators(settings),
    )

    primary = service.ingest(complaint("CMP-A"), "key-a")
    duplicate = service.ingest(complaint("CMP-B"), "key-b")
    review = service.ingest(complaint("CMP-C"), "key-c")

    assert duplicate.consolidation_status.value == "DUPLICATE"
    assert review.consolidation_status.value == "PENDING_REVIEW"
    assert review.decision is Decision.REVIEW_REQUIRED
    assert review.matched_incident_id is None
    assert review.leading_candidate_id == "CMP-A"

    group, links = _group_state(session_factory, primary.group_id)
    assert group.active_duplicate_count == 1
    assert group.historical_duplicate_count == 1
    assert [link.complaint_id for link in links] == ["CMP-A", "CMP-B"]
    assert all(link.complaint_id != "CMP-C" for link in links)

    with session_factory() as session:
        stored = session.get(ConsolidationReview, review.review_id)
        assert stored is not None
        assert stored.complaint_id == "CMP-C"
        assert stored.leading_candidate_id == review.leading_candidate_id
        assert stored.score == review.score

    detail = service.get_complaint_detail("CMP-C")
    assert detail.consolidation_status.value == "PENDING_REVIEW"
    assert detail.group is None
    assert detail.review is not None
    assert detail.review.leading_candidate_id == review.leading_candidate_id
    assert "matched_incident_id" not in detail.review.model_dump()

    queue = service.list_review_queue()
    assert queue.total == 1
    assert queue.items[0].complaint.complaint_id == "CMP-C"
    assert queue.items[0].leading_candidate_id == review.leading_candidate_id
    assert "matched_incident_id" not in queue.items[0].model_dump()


# --------------------------------------------------------------------------- #
# Idempotency
# --------------------------------------------------------------------------- #
def test_same_key_and_payload_replays_stored_response(session_factory) -> None:
    service, stubs = build_service(
        session_factory, {"CMP-A": detection("CMP-A", Decision.NEW)}
    )
    first = service.ingest(complaint("CMP-A"), "key-a")
    replay = service.ingest(complaint("CMP-A"), "key-a")

    assert replay.idempotent_replay is True
    assert replay.model_dump(exclude={"idempotent_replay"}) == first.model_dump(
        exclude={"idempotent_replay"}
    )
    assert replay.group_id == first.group_id

    assert _count(session_factory, ComplaintRecord) == 1
    assert _count(session_factory, ConsolidationRequest) == 1
    assert _count(session_factory, ConsolidationGroup) == 1
    assert _count(session_factory, ConsolidationLink) == 1
    assert len(stubs) == 1
    assert stubs[0].calls == ["CMP-A"]


def test_same_key_with_different_payload_is_rejected(session_factory) -> None:
    service, _ = build_service(
        session_factory, {"CMP-A": detection("CMP-A", Decision.NEW)}
    )
    service.ingest(complaint("CMP-A"), "key-a")

    with pytest.raises(ConsolidationError) as raised:
        service.ingest(complaint("CMP-A", description="Different text"), "key-a")

    assert raised.value.code == IDEMPOTENCY_KEY_REUSED
    assert raised.value.http_status == 409
    assert _count(session_factory, ConsolidationRequest) == 1


def test_same_complaint_with_new_key_is_rejected(session_factory) -> None:
    service, _ = build_service(
        session_factory, {"CMP-A": detection("CMP-A", Decision.NEW)}
    )
    service.ingest(complaint("CMP-A"), "key-a")

    with pytest.raises(ConsolidationError) as raised:
        service.ingest(complaint("CMP-A"), "key-b")

    assert raised.value.code == COMPLAINT_ALREADY_EXISTS
    assert raised.value.http_status == 409
    assert _count(session_factory, ConsolidationRequest) == 1


def test_fingerprint_is_stable_and_payload_sensitive() -> None:
    first = complaint("CMP-A")
    same = complaint("CMP-A")
    different = complaint("CMP-A", description="A different description")

    assert fingerprint_complaint(first) == fingerprint_complaint(same)
    assert fingerprint_complaint(first) != fingerprint_complaint(different)


# --------------------------------------------------------------------------- #
# Domain failures and transaction safety
# --------------------------------------------------------------------------- #
def test_unknown_matched_incident_rolls_back_the_new_complaint(
    session_factory,
) -> None:
    service, _ = build_service(
        session_factory,
        {
            "CMP-A": detection("CMP-A", Decision.NEW),
            "CMP-B": detection(
                "CMP-B",
                Decision.DUPLICATE,
                matched_incident_id="MISSING",
                score=0.9,
            ),
        },
    )
    service.ingest(complaint("CMP-A"), "key-a")

    with pytest.raises(ConsolidationError) as raised:
        service.ingest(complaint("CMP-B"), "key-b")

    assert raised.value.code == MATCHED_PRIMARY_NOT_FOUND
    assert raised.value.http_status == 409
    with session_factory() as session:
        assert session.get(ComplaintRecord, "CMP-B") is None
        assert session.get(ConsolidationRequest, "key-b") is None
    assert _count(session_factory, ConsolidationGroup) == 1
    assert _count(session_factory, ConsolidationLink) == 1


def test_matched_incident_without_group_is_rejected(session_factory) -> None:
    with session_factory() as session:
        with session.begin():
            session.add(
                ComplaintRecord(
                    complaint_id="ORPHAN",
                    description="Stored but never consolidated",
                    payload=None,
                    received_at=datetime.now(timezone.utc),
                )
            )

    service, _ = build_service(
        session_factory,
        {
            "CMP-B": detection(
                "CMP-B",
                Decision.DUPLICATE,
                matched_incident_id="ORPHAN",
                score=0.9,
            )
        },
    )

    with pytest.raises(ConsolidationError) as raised:
        service.ingest(complaint("CMP-B"), "key-b")

    assert raised.value.code == MATCHED_PRIMARY_NOT_CONSOLIDATED
    with session_factory() as session:
        assert session.get(ComplaintRecord, "CMP-B") is None
    assert _count(session_factory, ConsolidationLink) == 0


def test_closed_group_rejects_new_duplicates(session_factory) -> None:
    service, _ = build_service(
        session_factory,
        {
            "CMP-A": detection("CMP-A", Decision.NEW),
            "CMP-B": detection(
                "CMP-B",
                Decision.DUPLICATE,
                matched_incident_id="CMP-A",
                score=0.9,
            ),
        },
    )
    primary = service.ingest(complaint("CMP-A"), "key-a")

    with session_factory() as session:
        with session.begin():
            group = session.get(ConsolidationGroup, primary.group_id)
            assert group is not None
            group.status = "CLOSED"
            group.closed_at = datetime.now(timezone.utc)

    with pytest.raises(ConsolidationError) as raised:
        service.ingest(complaint("CMP-B"), "key-b")

    assert raised.value.code == GROUP_CLOSED
    assert raised.value.http_status == 409
    with session_factory() as session:
        assert session.get(ComplaintRecord, "CMP-B") is None
        group = session.get(ConsolidationGroup, primary.group_id)
        assert group is not None
        assert group.active_duplicate_count == 0
        assert group.historical_duplicate_count == 0


def test_get_missing_records_raises_domain_errors(session_factory) -> None:
    service, _ = build_service(session_factory, {})

    with pytest.raises(ConsolidationError) as missing_complaint:
        service.get_complaint_detail("UNKNOWN")
    assert missing_complaint.value.code == COMPLAINT_NOT_FOUND
    assert missing_complaint.value.http_status == 404

    with pytest.raises(ConsolidationError) as missing_group:
        service.get_group_detail("00000000-0000-0000-0000-000000000000")
    assert missing_group.value.code == GROUP_NOT_FOUND
    assert missing_group.value.http_status == 404


def test_stored_complaint_without_state_reports_not_consolidated(
    session_factory,
) -> None:
    with session_factory() as session:
        with session.begin():
            session.add(
                ComplaintRecord(
                    complaint_id="ORPHAN",
                    description="No link and no review",
                    payload=None,
                    received_at=datetime.now(timezone.utc),
                )
            )

    service, _ = build_service(session_factory, {})

    with pytest.raises(ConsolidationError) as raised:
        service.get_complaint_detail("ORPHAN")

    assert raised.value.code == COMPLAINT_NOT_CONSOLIDATED
    assert raised.value.http_status == 409


# --------------------------------------------------------------------------- #
# Pagination and filters
# --------------------------------------------------------------------------- #
def test_group_listing_and_status_filter(session_factory) -> None:
    service, _ = build_service(
        session_factory,
        {
            "CMP-A": detection("CMP-A", Decision.NEW),
            "CMP-B": detection("CMP-B", Decision.NEW),
        },
    )
    first = service.ingest(complaint("CMP-A"), "key-a")
    service.ingest(complaint("CMP-B"), "key-b")

    with session_factory() as session:
        with session.begin():
            group = session.get(ConsolidationGroup, first.group_id)
            assert group is not None
            group.status = "CLOSED"

    open_groups = service.list_groups(status="OPEN")
    assert open_groups.total == 1
    assert open_groups.items[0].primary_complaint_id == "CMP-B"

    all_groups = service.list_groups(limit=1, offset=1)
    assert all_groups.total == 2
    assert len(all_groups.items) == 1


def test_review_queue_can_include_closed_reviews(session_factory) -> None:
    service, _ = build_service(
        session_factory,
        {
            "CMP-A": detection(
                "CMP-A",
                Decision.REVIEW_REQUIRED,
                matched_incident_id=None,
                score=0.5,
            )
        },
    )
    result = service.ingest(complaint("CMP-A"), "key-a")

    with session_factory() as session:
        with session.begin():
            review = session.get(ConsolidationReview, result.review_id)
            assert review is not None
            review.status = "CLOSED"
            review.resolved_at = datetime.now(timezone.utc)

    assert service.list_review_queue(status="OPEN").total == 0
    assert service.list_review_queue(status="CLOSED").total == 1
    assert service.list_review_queue(status=None).total == 1
