"""Service-level tests for retrieval completeness and ``check_detailed``.

``check_detailed`` is the M3 HTTP edge into the existing orchestration service.
These tests prove that it preserves repository completeness information and
never converts an incomplete or failed search into ``NEW``. They use fake
repositories and comparators, so no embedding model is loaded.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping

import pytest

from app.comparators.base import Comparator, available_signal
from app.repositories.base import (
    INVALID_RETRIEVAL_RESULT,
    RETRIEVAL_COMPLETENESS_UNKNOWN,
    CandidateRetrieval,
    ComplaintRepository,
    RepositoryError,
    RetrievalFailure,
    RetrievalOutcome,
)
from app.schemas.complaint import Complaint
from app.schemas.duplicate_response import Decision, SignalResult
from app.scoring import RetrievalStatus
from app.scoring.decision_policy import (
    REASON_NO_ELIGIBLE_CANDIDATES,
    REASON_RETRIEVAL_FAILED,
    REASON_RETRIEVAL_INCOMPLETE,
    REASON_SCORE_ABOVE_HIGH,
    REASON_SCORE_BELOW_LOW,
)
from app.services import DuplicateDetectionService

SIGNAL_NAMES = ("text", "location", "category", "time")


# --------------------------------------------------------------------------- #
# Test doubles
# --------------------------------------------------------------------------- #
class RetrievalRepository(ComplaintRepository):
    """Repository double with an explicit retrieval outcome or failure."""

    def __init__(
        self,
        retrieval: CandidateRetrieval | None = None,
        *,
        error: Exception | None = None,
        malformed: object | None = None,
    ) -> None:
        self.retrieval = retrieval
        self.error = error
        self.malformed = malformed
        self.retrieve_calls: list[str | None] = []

    def retrieve_candidates(
        self, exclude_complaint_id: str | None = None
    ) -> CandidateRetrieval:
        self.retrieve_calls.append(exclude_complaint_id)
        if self.error is not None:
            raise self.error
        if self.malformed is not None:
            return self.malformed  # type: ignore[return-value]
        assert self.retrieval is not None
        return self.retrieval

    def add(self, complaint: Complaint) -> None:
        raise NotImplementedError

    def add_many(self, complaints: Iterable[Complaint]) -> None:
        raise NotImplementedError

    def get_by_id(self, complaint_id: str) -> Complaint | None:
        raise NotImplementedError

    def list_candidates(
        self, exclude_complaint_id: str | None = None
    ) -> list[Complaint]:
        raise AssertionError("check_detailed must use retrieve_candidates()")

    def count(self) -> int:
        return len(self.retrieval.candidates) if self.retrieval else 0


class ListOnlyRepository(ComplaintRepository):
    """Repository that implements only the original list interface."""

    def __init__(self, candidates: Iterable[Complaint]) -> None:
        self._candidates = tuple(candidates)
        self.list_calls: list[str | None] = []

    def add(self, complaint: Complaint) -> None:
        raise NotImplementedError

    def add_many(self, complaints: Iterable[Complaint]) -> None:
        raise NotImplementedError

    def get_by_id(self, complaint_id: str) -> Complaint | None:
        raise NotImplementedError

    def list_candidates(
        self, exclude_complaint_id: str | None = None
    ) -> list[Complaint]:
        self.list_calls.append(exclude_complaint_id)
        return [
            candidate
            for candidate in self._candidates
            if candidate.complaint_id != exclude_complaint_id
        ]

    def count(self) -> int:
        return len(self._candidates)


class FixedComparator(Comparator):
    """Comparator double returning a configured signal per candidate id."""

    def __init__(
        self,
        name: str,
        resolver: Mapping[str, SignalResult]
        | Callable[[Complaint, Complaint], SignalResult],
    ) -> None:
        self.name = name
        self._resolver = resolver
        self.calls: list[str] = []

    def compare(
        self, complaint: Complaint, candidate: Complaint
    ) -> SignalResult:
        self.calls.append(candidate.complaint_id)
        if callable(self._resolver):
            return self._resolver(complaint, candidate)
        return self._resolver[candidate.complaint_id]


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _complaint(complaint_id: str) -> Complaint:
    return Complaint(
        complaint_id=complaint_id,
        description=f"description for {complaint_id}",
    )


def _strong_signals() -> dict[str, SignalResult]:
    return {
        "text": available_signal(0.95, "TEXT_EMBEDDING_SIMILARITY"),
        "location": available_signal(0.95, "LOCATION_IDENTIFIER_MATCH"),
        "category": available_signal(1.0, "CATEGORY_EXACT_MATCH"),
        "time": available_signal(0.90, "TIME_CLOSE"),
    }


def _weak_signals() -> dict[str, SignalResult]:
    return {
        "text": available_signal(0.51, "TEXT_EMBEDDING_SIMILARITY"),
        "location": available_signal(0.51, "LOCATION_IDENTIFIER_MATCH"),
        "category": available_signal(0.10, "CATEGORY_DIFFERENT"),
        "time": available_signal(0.10, "TIME_FAR"),
    }


def _comparators(
    signals_by_candidate: Mapping[str, Mapping[str, SignalResult]],
) -> dict[str, FixedComparator]:
    return {
        name: FixedComparator(
            name,
            {
                candidate_id: signals[name]
                for candidate_id, signals in signals_by_candidate.items()
            },
        )
        for name in SIGNAL_NAMES
    }


def _service(
    repository: ComplaintRepository,
    signals_by_candidate: Mapping[str, Mapping[str, SignalResult]],
) -> DuplicateDetectionService:
    return DuplicateDetectionService(
        repository,
        comparators=_comparators(signals_by_candidate),
    )


# --------------------------------------------------------------------------- #
# Complete retrieval
# --------------------------------------------------------------------------- #
def test_complete_retrieval_preserves_duplicate_decision() -> None:
    candidate = _complaint("CMP-A")
    repository = RetrievalRepository(
        CandidateRetrieval((candidate,), RetrievalOutcome.COMPLETE)
    )
    service = _service(repository, {"CMP-A": _strong_signals()})

    result = service.check_detailed(_complaint("NEW-1"))

    assert result.incident_id == "NEW-1"
    assert result.outcome.decision is Decision.DUPLICATE
    assert result.outcome.matched_incident_id == "CMP-A"
    assert result.outcome.reasons == (REASON_SCORE_ABOVE_HIGH,)
    assert result.retrieval_status is RetrievalStatus.COMPLETE
    assert result.retrieval_failure is None
    assert repository.retrieve_calls == ["NEW-1"]
    assert result.to_response().complaint_id == "NEW-1"


def test_complete_empty_retrieval_is_new() -> None:
    repository = RetrievalRepository(
        CandidateRetrieval((), RetrievalOutcome.COMPLETE)
    )
    service = _service(repository, {})

    result = service.check_detailed(_complaint("NEW-1"))

    assert result.outcome.decision is Decision.NEW
    assert result.outcome.matched_incident_id is None
    assert result.outcome.score is None
    assert result.outcome.reasons == (REASON_NO_ELIGIBLE_CANDIDATES,)
    assert result.retrieval_status is RetrievalStatus.COMPLETE


# --------------------------------------------------------------------------- #
# Partial retrieval
# --------------------------------------------------------------------------- #
def test_partial_retrieval_with_high_score_is_not_reported_as_complete() -> None:
    candidate = _complaint("CMP-A")
    failure = RetrievalFailure(
        RETRIEVAL_COMPLETENESS_UNKNOWN,
        "The index may not have returned every candidate.",
    )
    repository = RetrievalRepository(
        CandidateRetrieval(
            (candidate,),
            RetrievalOutcome.PARTIAL,
            (failure,),
        )
    )
    service = _service(repository, {"CMP-A": _strong_signals()})

    result = service.check_detailed(_complaint("NEW-1"))

    # The policy is unchanged and still sees a high-scoring candidate. The HTTP
    # mapper is the layer that forces REVIEW_REQUIRED for incomplete retrieval.
    assert result.outcome.decision is Decision.DUPLICATE
    assert result.retrieval_status is RetrievalStatus.INCOMPLETE
    assert result.retrieval_failure == failure


def test_partial_retrieval_with_low_score_is_review_not_new() -> None:
    candidate = _complaint("CMP-WEAK")
    repository = RetrievalRepository(
        CandidateRetrieval((candidate,), RetrievalOutcome.PARTIAL)
    )
    service = _service(repository, {"CMP-WEAK": _weak_signals()})

    result = service.check_detailed(_complaint("NEW-1"))

    assert result.outcome.decision is Decision.REVIEW_REQUIRED
    assert result.outcome.matched_incident_id is None
    assert REASON_SCORE_BELOW_LOW in result.outcome.reasons
    assert REASON_RETRIEVAL_INCOMPLETE in result.outcome.reasons
    assert result.retrieval_status is RetrievalStatus.INCOMPLETE
    assert result.retrieval_failure is not None
    assert result.retrieval_failure.code == RETRIEVAL_COMPLETENESS_UNKNOWN


def test_partial_retrieval_without_candidates_is_review_not_new() -> None:
    repository = RetrievalRepository(
        CandidateRetrieval((), RetrievalOutcome.PARTIAL)
    )
    service = _service(repository, {})

    result = service.check_detailed(_complaint("NEW-1"))

    assert result.outcome.decision is Decision.REVIEW_REQUIRED
    assert result.outcome.matched_incident_id is None
    assert result.outcome.reasons == (REASON_RETRIEVAL_INCOMPLETE,)
    assert result.retrieval_status is RetrievalStatus.INCOMPLETE


def test_list_only_repository_defaults_to_partial_not_complete() -> None:
    candidate = _complaint("CMP-A")
    repository = ListOnlyRepository([candidate])
    service = _service(repository, {"CMP-A": _strong_signals()})

    result = service.check_detailed(_complaint("NEW-1"))

    assert repository.list_calls == ["NEW-1"]
    assert result.retrieval_status is RetrievalStatus.INCOMPLETE
    assert result.retrieval_failure is not None
    assert result.retrieval_failure.code == RETRIEVAL_COMPLETENESS_UNKNOWN


# --------------------------------------------------------------------------- #
# Failed retrieval
# --------------------------------------------------------------------------- #
def test_repository_failure_becomes_failed_review_not_new() -> None:
    repository = RetrievalRepository(
        error=RepositoryError("vector store is down", code="RETRIEVAL_TIMEOUT")
    )
    service = _service(repository, {})

    result = service.check_detailed(_complaint("NEW-1"))

    assert result.outcome.decision is Decision.REVIEW_REQUIRED
    assert result.outcome.matched_incident_id is None
    assert result.outcome.score is None
    assert result.outcome.candidates == ()
    assert result.outcome.reasons == (REASON_RETRIEVAL_FAILED,)
    assert result.retrieval_status is RetrievalStatus.FAILED
    assert result.retrieval_failure is not None
    assert result.retrieval_failure.code == "RETRIEVAL_TIMEOUT"
    assert result.retrieval_failure.message == "vector store is down"


def test_malformed_retrieval_result_becomes_failed() -> None:
    repository = RetrievalRepository(malformed=[_complaint("CMP-A")])
    service = _service(repository, {})

    result = service.check_detailed(_complaint("NEW-1"))

    assert result.outcome.decision is Decision.REVIEW_REQUIRED
    assert result.retrieval_status is RetrievalStatus.FAILED
    assert result.retrieval_failure is not None
    assert result.retrieval_failure.code == INVALID_RETRIEVAL_RESULT


# --------------------------------------------------------------------------- #
# Unexpected infrastructure failures must propagate
# --------------------------------------------------------------------------- #
def test_timeout_propagates_for_http_504() -> None:
    repository = RetrievalRepository(error=TimeoutError("upstream timed out"))
    service = _service(repository, {})

    with pytest.raises(TimeoutError, match="upstream timed out"):
        service.check_detailed(_complaint("NEW-1"))


def test_unexpected_exception_propagates_for_http_500() -> None:
    repository = RetrievalRepository(error=RuntimeError("programming bug"))
    service = _service(repository, {})

    with pytest.raises(RuntimeError, match="programming bug"):
        service.check_detailed(_complaint("NEW-1"))
