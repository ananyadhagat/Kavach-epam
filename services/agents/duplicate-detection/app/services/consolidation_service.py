"""Consolidation service: persist complaints and group M3-confirmed duplicates.

Responsibilities
----------------
1. Store every accepted complaint individually.
2. Run the **unchanged** M3 duplicate-detection service against previously
   consolidated complaints.
3. Apply the M3 decision:
   * ``NEW`` -> create a group and a ``PRIMARY`` link;
   * ``DUPLICATE`` -> resolve the matched incident to its group's canonical
     primary and create a ``DUPLICATE`` link with atomic count updates;
   * ``REVIEW_REQUIRED`` -> create a pending review, with no link and no count
     changes.
4. Record an idempotent response snapshot and expose read models for
   Supervisor/Dispatch.

The module contains no similarity maths, scoring, thresholds or decision
policy. It delegates all of that to :class:`DuplicateDetectionService` and only
persists the outcome.
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Callable, Mapping
from typing import Protocol
from uuid import uuid4

from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from app.comparators.base import Comparator
from app.comparators.factory import build_core_comparators
from app.db.models import (
    ConsolidationGroup,
    ConsolidationLink,
    ConsolidationRequest,
    ConsolidationReview,
    ensure_aware,
    utc_now,
)
from app.repositories.base import ComplaintRepository
from app.repositories.consolidation import (
    get_complaint,
    get_group,
    get_link,
    get_request,
    get_review,
    increment_duplicate_counts,
    list_duplicates,
    list_groups,
    list_reviews,
    review_summary,
)
from app.repositories.sql_complaint import (
    DatabaseComplaintRepository,
    SessionComplaintRepository,
    complaint_to_record,
    record_to_complaint,
)
from app.schemas.complaint import Complaint
from app.schemas.consolidation import (
    ComplaintDetailResponse,
    ConsolidationResult,
    ConsolidationStatus,
    DuplicateMember,
    GroupDetailResponse,
    GroupSummaryResponse,
    PaginatedGroups,
    PaginatedReviews,
    ReviewQueueItem,
    ReviewResponse,
)
from app.schemas.duplicate_response import Decision
from app.services.consolidation_errors import (
    ConsolidationError,
    complaint_already_exists,
    complaint_not_consolidated,
    complaint_not_found,
    database_unavailable,
    group_closed,
    group_not_found,
    idempotency_key_reused,
    internal_error,
    matched_primary_not_consolidated,
    matched_primary_not_found,
)
from app.services.detection_service import DetectionResult, DuplicateDetectionService

logger = logging.getLogger(__name__)

#: HTTP status used for a successful ingestion and for idempotent replays.
INGEST_RESPONSE_STATUS = 201

#: Maximum number of insertion attempts when a concurrent writer wins a race.
_MAX_INGEST_ATTEMPTS = 2


class DetailedDetectionService(Protocol):
    """Narrow view of the unchanged M3 service used by consolidation."""

    def check_detailed(self, complaint: Complaint) -> DetectionResult: ...


DetectionServiceFactory = Callable[
    [ComplaintRepository], DetailedDetectionService
]


def fingerprint_complaint(complaint: Complaint) -> str:
    """Return a stable SHA-256 fingerprint of the canonical complaint payload."""

    canonical = json.dumps(
        complaint.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class ConsolidationService:
    """Persist complaints and consolidate M3-confirmed duplicates.

    Parameters
    ----------
    session_factory:
        SQLAlchemy session factory. Each call opens its own session and
        transaction.
    comparators:
        Optional pre-built M3 comparator mapping. When omitted, the standard
        core comparators are built lazily and reused across requests.
    detection_service_factory:
        Optional test seam. It receives the transaction-scoped repository and
        returns an object with ``check_detailed``. Production uses the real
        :class:`DuplicateDetectionService`.
    """

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        *,
        comparators: Mapping[str, Comparator] | None = None,
        detection_service_factory: DetectionServiceFactory | None = None,
    ) -> None:
        if not callable(session_factory):
            raise TypeError("session_factory must be callable")
        if comparators is not None and detection_service_factory is not None:
            raise ValueError(
                "pass comparators or detection_service_factory, not both"
            )
        self._session_factory = session_factory
        self._comparators = comparators
        self._detection_service_factory = detection_service_factory

    # ------------------------------------------------------------------
    # M3 wiring
    # ------------------------------------------------------------------
    def _get_comparators(self) -> Mapping[str, Comparator]:
        if self._comparators is None:
            self._comparators = build_core_comparators()
        return self._comparators

    def _build_detection_service(
        self, repository: ComplaintRepository
    ) -> DetailedDetectionService:
        if self._detection_service_factory is not None:
            return self._detection_service_factory(repository)
        return DuplicateDetectionService(
            repository=repository,
            comparators=self._get_comparators(),
        )

    def build_detection_service(self) -> DetailedDetectionService:
        """Build the database-backed service used by the read-only check route.

        The returned service opens a short session for each candidate
        retrieval. It does not write complaints or consolidation rows.
        """

        return self._build_detection_service(
            DatabaseComplaintRepository(self._session_factory)
        )

    # ------------------------------------------------------------------
    # Ingestion
    # ------------------------------------------------------------------
    def ingest(
        self,
        complaint: Complaint,
        idempotency_key: str,
    ) -> ConsolidationResult:
        """Store one complaint and apply the M3 decision atomically.

        Raises:
            ConsolidationError: for idempotency conflicts, unknown matches,
                closed groups, or database failures.
        """

        fingerprint = fingerprint_complaint(complaint)
        attempt = 0
        while True:
            attempt += 1
            try:
                with self._session_factory() as session:
                    with session.begin():
                        return self._ingest_once(
                            session,
                            complaint,
                            idempotency_key,
                            fingerprint,
                        )
            except IntegrityError:
                recovered = self._recover_conflict(
                    complaint, idempotency_key, fingerprint
                )
                if recovered is not None:
                    return recovered
                if attempt >= _MAX_INGEST_ATTEMPTS:
                    logger.exception(
                        "consolidation hit an unrecoverable integrity conflict"
                    )
                    raise internal_error()
            except ConsolidationError:
                raise
            except SQLAlchemyError:
                logger.exception("consolidation database operation failed")
                raise database_unavailable()

    def _ingest_once(
        self,
        session: Session,
        complaint: Complaint,
        idempotency_key: str,
        fingerprint: str,
    ) -> ConsolidationResult:
        existing_request = get_request(session, idempotency_key)
        if existing_request is not None:
            if existing_request.fingerprint != fingerprint:
                raise idempotency_key_reused()
            stored = ConsolidationResult.model_validate(
                existing_request.response_body
            )
            return stored.model_copy(update={"idempotent_replay": True})

        if get_complaint(session, complaint.complaint_id) is not None:
            raise complaint_already_exists(complaint.complaint_id)

        session.add(complaint_to_record(complaint))
        session.flush()

        detection = self._build_detection_service(
            SessionComplaintRepository(session)
        )
        detection_result = detection.check_detailed(complaint)
        outcome = detection_result.outcome

        reasons = list(outcome.reasons)
        status: ConsolidationStatus
        group_id: str | None = None
        primary_complaint_id: str | None = None
        matched_incident_id: str | None = None
        leading_candidate_id: str | None = None
        review_id: str | None = None
        active_count = 0
        historical_count = 0

        if outcome.decision is Decision.NEW:
            group = ConsolidationGroup(
                group_id=str(uuid4()),
                primary_complaint_id=complaint.complaint_id,
                status="OPEN",
                active_duplicate_count=0,
                historical_duplicate_count=0,
                creation_reason="M3_NEW",
                created_at=utc_now(),
            )
            session.add(group)
            session.flush()

            session.add(
                ConsolidationLink(
                    link_id=str(uuid4()),
                    group_id=group.group_id,
                    complaint_id=complaint.complaint_id,
                    role="PRIMARY",
                    matched_incident_id=None,
                    match_score=None,
                    reasons=reasons,
                    linked_at=utc_now(),
                )
            )
            session.flush()

            status = ConsolidationStatus.PRIMARY
            group_id = group.group_id
            primary_complaint_id = complaint.complaint_id
            active_count = 0
            historical_count = 0

        elif outcome.decision is Decision.DUPLICATE:
            matched_incident_id = outcome.matched_incident_id
            if not matched_incident_id:
                raise matched_primary_not_found("<missing>")

            matched_link = get_link(session, matched_incident_id)
            if matched_link is None:
                if get_complaint(session, matched_incident_id) is None:
                    raise matched_primary_not_found(matched_incident_id)
                raise matched_primary_not_consolidated(matched_incident_id)

            group = get_group(session, matched_link.group_id)
            if group is None:
                raise matched_primary_not_found(matched_incident_id)
            if group.status != "OPEN":
                raise group_closed(group.group_id)

            session.add(
                ConsolidationLink(
                    link_id=str(uuid4()),
                    group_id=group.group_id,
                    complaint_id=complaint.complaint_id,
                    role="DUPLICATE",
                    matched_incident_id=matched_incident_id,
                    match_score=outcome.score,
                    reasons=reasons,
                    linked_at=utc_now(),
                )
            )
            session.flush()

            updated = increment_duplicate_counts(session, group.group_id)
            if updated == 0:
                raise group_closed(group.group_id)
            session.refresh(group)

            status = ConsolidationStatus.DUPLICATE
            group_id = group.group_id
            primary_complaint_id = group.primary_complaint_id
            active_count = group.active_duplicate_count
            historical_count = group.historical_duplicate_count

        elif outcome.decision is Decision.REVIEW_REQUIRED:
            # A review never asserts a match. The policy reports the top-ranked
            # candidate separately from ``matched_incident_id`` (which is None
            # for reviews); the fallback keeps a leading candidate if a custom
            # policy ever supplies one via the matched field.
            leading_candidate_id = (
                outcome.matched_incident_id or outcome.leading_candidate_id
            )
            review = ConsolidationReview(
                review_id=str(uuid4()),
                complaint_id=complaint.complaint_id,
                status="OPEN",
                decision=outcome.decision.value,
                leading_candidate_id=leading_candidate_id,
                score=outcome.score,
                reasons=reasons,
                created_at=utc_now(),
            )
            session.add(review)
            session.flush()

            status = ConsolidationStatus.PENDING_REVIEW
            review_id = review.review_id

        else:  # pragma: no cover - the Decision enum is closed
            raise internal_error()

        result = ConsolidationResult(
            complaint_id=complaint.complaint_id,
            consolidation_status=status,
            decision=outcome.decision,
            group_id=group_id,
            primary_complaint_id=primary_complaint_id,
            matched_incident_id=matched_incident_id,
            leading_candidate_id=leading_candidate_id,
            score=outcome.score,
            reasons=reasons,
            active_duplicate_count=active_count,
            historical_duplicate_count=historical_count,
            review_id=review_id,
            idempotent_replay=False,
        )

        session.add(
            ConsolidationRequest(
                idempotency_key=idempotency_key,
                complaint_id=complaint.complaint_id,
                fingerprint=fingerprint,
                response_status=INGEST_RESPONSE_STATUS,
                response_body=result.model_dump(mode="json"),
                created_at=utc_now(),
            )
        )
        session.flush()
        return result

    def _recover_conflict(
        self,
        complaint: Complaint,
        idempotency_key: str,
        fingerprint: str,
    ) -> ConsolidationResult | None:
        """Re-read after a unique-constraint race and replay when possible."""

        try:
            with self._session_factory() as session:
                with session.begin():
                    existing = get_request(session, idempotency_key)
                    if existing is not None:
                        if existing.fingerprint != fingerprint:
                            raise idempotency_key_reused()
                        stored = ConsolidationResult.model_validate(
                            existing.response_body
                        )
                        return stored.model_copy(
                            update={"idempotent_replay": True}
                        )
                    if get_complaint(session, complaint.complaint_id) is not None:
                        raise complaint_already_exists(complaint.complaint_id)
                    return None
        except ConsolidationError:
            raise
        except SQLAlchemyError:
            logger.exception("consolidation conflict recovery failed")
            raise database_unavailable()

    # ------------------------------------------------------------------
    # Retrieval
    # ------------------------------------------------------------------
    def get_complaint_detail(self, complaint_id: str) -> ComplaintDetailResponse:
        try:
            with self._session_factory() as session:
                record = get_complaint(session, complaint_id)
                if record is None:
                    raise complaint_not_found(complaint_id)

                link = get_link(session, complaint_id)
                review = None
                group_response = None
                if link is not None:
                    group = get_group(session, link.group_id)
                    if group is None:
                        raise group_not_found(link.group_id)
                    group_response = self._group_summary_response(group)
                    if link.role == "PRIMARY":
                        status = ConsolidationStatus.PRIMARY
                    else:
                        status = ConsolidationStatus.DUPLICATE
                else:
                    review = get_review(session, complaint_id)
                    if review is None:
                        raise complaint_not_consolidated(complaint_id)
                    status = ConsolidationStatus.PENDING_REVIEW

                complaint = record_to_complaint(record)
                return ComplaintDetailResponse(
                    complaint=complaint,
                    consolidation_status=status,
                    group=group_response,
                    review=(
                        self._review_response(review)
                        if review is not None
                        else None
                    ),
                    received_at=ensure_aware(record.received_at),
                )
        except ConsolidationError:
            raise
        except SQLAlchemyError:
            logger.exception("complaint retrieval failed")
            raise database_unavailable()

    def get_group_detail(self, group_id: str) -> GroupDetailResponse:
        try:
            with self._session_factory() as session:
                group = get_group(session, group_id)
                if group is None:
                    raise group_not_found(group_id)

                primary_record = get_complaint(
                    session, group.primary_complaint_id
                )
                if primary_record is None:  # pragma: no cover - FK protects this
                    raise internal_error()

                duplicates: list[DuplicateMember] = []
                for record, link in list_duplicates(session, group_id):
                    duplicates.append(
                        DuplicateMember(
                            complaint=record_to_complaint(record),
                            link_id=link.link_id,
                            matched_incident_id=link.matched_incident_id,
                            match_score=link.match_score,
                            reasons=list(link.reasons or ()),
                            linked_at=ensure_aware(link.linked_at),
                        )
                    )

                summary = self._group_summary_response(group)
                return GroupDetailResponse(
                    **summary.model_dump(),
                    primary=record_to_complaint(primary_record),
                    duplicates=duplicates,
                )
        except ConsolidationError:
            raise
        except SQLAlchemyError:
            logger.exception("group retrieval failed")
            raise database_unavailable()

    def list_groups(
        self,
        *,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> PaginatedGroups:
        try:
            with self._session_factory() as session:
                groups, total = list_groups(
                    session, status=status, limit=limit, offset=offset
                )
                return PaginatedGroups(
                    items=[
                        self._group_summary_response(group)
                        for group in groups
                    ],
                    total=total,
                    limit=limit,
                    offset=offset,
                )
        except SQLAlchemyError:
            logger.exception("group listing failed")
            raise database_unavailable()

    def list_review_queue(
        self,
        *,
        status: str | None = "OPEN",
        limit: int = 50,
        offset: int = 0,
    ) -> PaginatedReviews:
        try:
            with self._session_factory() as session:
                reviews, total = list_reviews(
                    session, status=status, limit=limit, offset=offset
                )
                items: list[ReviewQueueItem] = []
                for review in reviews:
                    record = get_complaint(session, review.complaint_id)
                    if record is None:  # pragma: no cover - FK protects this
                        raise internal_error()
                    base = self._review_response(review)
                    items.append(
                        ReviewQueueItem(
                            **base.model_dump(),
                            complaint=record_to_complaint(record),
                        )
                    )
                return PaginatedReviews(
                    items=items,
                    total=total,
                    limit=limit,
                    offset=offset,
                )
        except ConsolidationError:
            raise
        except SQLAlchemyError:
            logger.exception("review queue retrieval failed")
            raise database_unavailable()

    # ------------------------------------------------------------------
    # Mapping helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _group_summary_response(
        group: ConsolidationGroup,
    ) -> GroupSummaryResponse:
        return GroupSummaryResponse(
            group_id=group.group_id,
            primary_complaint_id=group.primary_complaint_id,
            status=group.status,
            active_duplicate_count=group.active_duplicate_count,
            historical_duplicate_count=group.historical_duplicate_count,
            member_count=group.active_duplicate_count + 1,
            created_at=ensure_aware(group.created_at),
            closed_at=ensure_aware(group.closed_at),
        )

    @staticmethod
    def _review_response(review: ConsolidationReview) -> ReviewResponse:
        summary = review_summary(review)
        return ReviewResponse(
            review_id=summary.review_id,
            complaint_id=summary.complaint_id,
            status=summary.status,
            decision=summary.decision,
            leading_candidate_id=summary.leading_candidate_id,
            score=summary.score,
            reasons=list(summary.reasons),
            created_at=ensure_aware(summary.created_at),
            resolved_at=ensure_aware(summary.resolved_at),
        )


__all__ = [
    "ConsolidationService",
    "DetailedDetectionService",
    "DetectionServiceFactory",
    "fingerprint_complaint",
]
