"""Service-level tests for duplicate-detection orchestration.

These tests use fake repositories and comparators. They exercise the composition
of retrieval, comparison, scoring, decision and response mapping without loading
an embedding model or touching the HTTP layer.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping

import pytest

from app.comparators.base import (
    Comparator,
    available_signal,
    error_signal,
    invalid_signal,
    unavailable_signal,
)
from app.repositories.base import ComplaintRepository, RepositoryError
from app.schemas.complaint import Complaint
from app.schemas.duplicate_response import (
    Decision,
    DuplicateDetectionResponse,
    SignalResult,
    SignalStatus,
)
from app.scoring import (
    CandidateScore,
    DecisionOutcome,
    DecisionPolicy,
    RetrievalStatus,
)
from app.scoring.decision_policy import (
    REASON_CONTRADICTION_LOCATION,
    REASON_MISSING_CORE_ANCHOR,
    REASON_NO_ELIGIBLE_CANDIDATES,
    REASON_SCORE_ABOVE_HIGH,
    REASON_SCORE_BELOW_LOW,
)
from app.services import DuplicateDetectionService

SIGNAL_NAMES = ("text", "location", "category", "time")


# --------------------------------------------------------------------------- #
# Test doubles
# --------------------------------------------------------------------------- #
class FakeRepository(ComplaintRepository):
    """Repository double that can ignore exclusion or raise on demand."""

    def __init__(self, candidates: Iterable[Complaint] = ()) -> None:
        self._candidates = list(candidates)
        self.exclude_calls: list[str | None] = []
        self.failure: Exception | None = None

    def list_candidates(
        self, exclude_complaint_id: str | None = None
    ) -> list[Complaint]:
        self.exclude_calls.append(exclude_complaint_id)
        if self.failure is not None:
            raise self.failure
        return list(self._candidates)

    def add(self, complaint: Complaint) -> None:
        raise NotImplementedError

    def add_many(self, complaints: Iterable[Complaint]) -> None:
        raise NotImplementedError

    def get_by_id(self, complaint_id: str) -> Complaint | None:
        raise NotImplementedError

    def count(self) -> int:
        return len(self._candidates)


class FakeComparator(Comparator):
    """Comparator double resolving a signal by candidate id or callback."""

    def __init__(
        self,
        name: str,
        resolver: Mapping[str, SignalResult]
        | Callable[[Complaint, Complaint], SignalResult],
    ) -> None:
        self.name = name
        self._resolver = resolver
        self.calls: list[tuple[str, str]] = []

    def compare(
        self, complaint: Complaint, candidate: Complaint
    ) -> SignalResult:
        self.calls.append((complaint.complaint_id, candidate.complaint_id))
        if callable(self._resolver):
            return self._resolver(complaint, candidate)
        return self._resolver[candidate.complaint_id]


class RaisingTextComparator(Comparator):
    name = "text"

    def compare(
        self, complaint: Complaint, candidate: Complaint
    ) -> SignalResult:
        raise RuntimeError("inference exploded")


class StubDecisionPolicy(DecisionPolicy):
    """Policy double that records inputs and returns a fixed outcome."""

    def __init__(self, outcome: DecisionOutcome) -> None:
        super().__init__()
        self.outcome = outcome
        self.calls: list[tuple[tuple[CandidateScore, ...], RetrievalStatus]] = []

    def decide(
        self,
        candidates: Iterable[CandidateScore],
        *,
        retrieval_status: RetrievalStatus = RetrievalStatus.COMPLETE,
    ) -> DecisionOutcome:
        self.calls.append((tuple(candidates), retrieval_status))
        return self.outcome


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _complaint(complaint_id: str, description: str | None = None) -> Complaint:
    return Complaint(
        complaint_id=complaint_id,
        description=description or f"description for {complaint_id}",
    )


def _mapping_comparators(
    signals_by_candidate: Mapping[str, Mapping[str, SignalResult]],
) -> dict[str, FakeComparator]:
    return {
        name: FakeComparator(
            name,
            {
                candidate_id: signals[name]
                for candidate_id, signals in signals_by_candidate.items()
            },
        )
        for name in SIGNAL_NAMES
    }


def _callable_comparators(
    resolver: Callable[[Complaint, Complaint, str], SignalResult],
) -> dict[str, FakeComparator]:
    return {
        name: FakeComparator(
            name,
            lambda complaint, candidate, signal_name=name: resolver(
                complaint, candidate, signal_name
            ),
        )
        for name in SIGNAL_NAMES
    }


def _service(
    candidates: Iterable[Complaint],
    comparators: Mapping[str, Comparator],
    *,
    policy: DecisionPolicy | None = None,
) -> tuple[DuplicateDetectionService, FakeRepository]:
    repository = FakeRepository(candidates)
    service = DuplicateDetectionService(
        repository,
        comparators=comparators,
        decision_policy=policy,
    )
    return service, repository


def _strong_signals() -> dict[str, SignalResult]:
    """All four signals available, yielding a clear DUPLICATE score."""

    return {
        "text": available_signal(0.95, "TEXT_EMBEDDING_SIMILARITY"),
        "location": available_signal(0.95, "LOCATION_IDENTIFIER_MATCH"),
        "category": available_signal(1.0, "CATEGORY_EXACT_MATCH"),
        "time": available_signal(0.90, "TIME_CLOSE"),
    }


def _moderate_signals() -> dict[str, SignalResult]:
    """A ranked but weaker candidate than ``_strong_signals``."""

    return {
        "text": available_signal(0.80, "TEXT_EMBEDDING_SIMILARITY"),
        "location": available_signal(0.80, "LOCATION_IDENTIFIER_MATCH"),
        "category": available_signal(0.80, "CATEGORY_COMPATIBLE"),
        "time": available_signal(0.80, "TIME_CLOSE"),
    }


def _weak_signals() -> dict[str, SignalResult]:
    """Available evidence below the low threshold, with a core anchor."""

    return {
        "text": available_signal(0.51, "TEXT_EMBEDDING_SIMILARITY"),
        "location": available_signal(0.51, "LOCATION_IDENTIFIER_MATCH"),
        "category": available_signal(0.10, "CATEGORY_DIFFERENT"),
        "time": available_signal(0.10, "TIME_FAR"),
    }


def _text_error_fallback_signals() -> dict[str, SignalResult]:
    """Strong non-text evidence; the text signal is an ERROR."""

    return {
        "text": error_signal(
            "TEXT_EMBEDDING_INFERENCE_FAILED",
            {"model": "fake", "error_type": "RuntimeError", "error": "boom"},
        ),
        "location": available_signal(0.99, "LOCATION_IDENTIFIER_MATCH"),
        "category": available_signal(1.0, "CATEGORY_EXACT_MATCH"),
        "time": available_signal(0.99, "TIME_CLOSE"),
    }


def _text_error_weak_signals() -> dict[str, SignalResult]:
    """Text failed; non-text evidence clears gates but stays below ``low``."""

    return {
        "text": error_signal(
            "TEXT_EMBEDDING_INFERENCE_FAILED",
            {"model": "fake", "error_type": "RuntimeError", "error": "boom"},
        ),
        "location": available_signal(0.60, "LOCATION_IDENTIFIER_MATCH"),
        "category": available_signal(0.60, "CATEGORY_COMPATIBLE"),
        "time": available_signal(0.10, "TIME_FAR"),
    }


# --------------------------------------------------------------------------- #
# Core outcomes
# --------------------------------------------------------------------------- #
def test_clear_duplicate_returns_duplicate() -> None:
    service, repository = _service(
        [_complaint("CMP-1")],
        _mapping_comparators({"CMP-1": _strong_signals()}),
    )

    response = service.check(_complaint("NEW-1"))

    assert response.complaint_id == "NEW-1"
    assert response.decision is Decision.DUPLICATE
    assert response.matched_incident_id == "CMP-1"
    assert response.score == pytest.approx(0.95)
    assert response.reasons == [REASON_SCORE_ABOVE_HIGH]
    assert set(response.signals) == set(SIGNAL_NAMES)
    assert response.signals["text"].status is SignalStatus.AVAILABLE
    assert repository.exclude_calls == ["NEW-1"]


def test_empty_repository_returns_new() -> None:
    comparators = _mapping_comparators({})
    service, repository = _service([], comparators)

    response = service.check(_complaint("NEW-1"))

    assert response.decision is Decision.NEW
    assert response.matched_incident_id is None
    assert response.score is None
    assert response.signals == {}
    assert response.reasons == [REASON_NO_ELIGIBLE_CANDIDATES]
    assert repository.exclude_calls == ["NEW-1"]
    assert all(comparator.calls == [] for comparator in comparators.values())


def test_low_scoring_candidate_returns_new() -> None:
    service, _ = _service(
        [_complaint("CMP-WEAK")],
        _mapping_comparators({"CMP-WEAK": _weak_signals()}),
    )

    response = service.check(_complaint("NEW-1"))

    assert response.decision is Decision.NEW
    assert response.matched_incident_id is None
    assert response.score is None
    assert response.reasons == [REASON_SCORE_BELOW_LOW]
    assert response.signals["text"].status is SignalStatus.AVAILABLE


def test_multiple_candidates_select_the_highest_score() -> None:
    comparators = _mapping_comparators(
        {
            "CMP-A": _strong_signals(),
            "CMP-B": _moderate_signals(),
        }
    )
    service, _ = _service(
        [_complaint("CMP-A"), _complaint("CMP-B")],
        comparators,
    )

    response = service.check(_complaint("NEW-1"))

    assert response.decision is Decision.DUPLICATE
    assert response.matched_incident_id == "CMP-A"
    assert response.score == pytest.approx(0.95)
    assert all(len(comparator.calls) == 2 for comparator in comparators.values())
    assert {candidate_id for _, candidate_id in comparators["text"].calls} == {
        "CMP-A",
        "CMP-B",
    }


# --------------------------------------------------------------------------- #
# Candidate selection edge cases
# --------------------------------------------------------------------------- #
def test_self_candidate_is_skipped_even_if_repository_returns_it() -> None:
    incoming = _complaint("NEW-1")
    comparators = _mapping_comparators({"NEW-1": _strong_signals()})
    service, repository = _service([incoming], comparators)

    response = service.check(incoming)

    assert response.decision is Decision.NEW
    assert response.reasons == [REASON_NO_ELIGIBLE_CANDIDATES]
    assert repository.exclude_calls == ["NEW-1"]
    assert all(comparator.calls == [] for comparator in comparators.values())


def test_duplicate_candidate_ids_keep_the_first_record_and_compare_once() -> None:
    first = _complaint("CMP-DUP", description="first")
    second = _complaint("CMP-DUP", description="second")

    def resolver(
        complaint: Complaint, candidate: Complaint, signal_name: str
    ) -> SignalResult:
        signals = (
            _strong_signals()
            if candidate.description == "first"
            else _weak_signals()
        )
        return signals[signal_name]

    comparators = _callable_comparators(resolver)
    service, _ = _service([first, second], comparators)

    response = service.check(_complaint("NEW-1"))

    # If the duplicate were scored twice, the stronger "second" record would
    # win. If the last record won, this would be NEW. Both are wrong.
    assert response.decision is Decision.DUPLICATE
    assert response.matched_incident_id == "CMP-DUP"
    assert all(len(comparator.calls) == 1 for comparator in comparators.values())


# --------------------------------------------------------------------------- #
# Signal preservation and scoring semantics
# --------------------------------------------------------------------------- #
def test_missing_and_invalid_signals_are_preserved_and_excluded_from_score() -> None:
    signals = {
        "text": unavailable_signal("TEXT_UNAVAILABLE"),
        "location": invalid_signal("LOCATION_INVALID"),
        "category": available_signal(1.0, "CATEGORY_EXACT_MATCH"),
        "time": available_signal(0.90, "TIME_CLOSE"),
    }
    service, _ = _service(
        [_complaint("CMP-MISSING")],
        _mapping_comparators({"CMP-MISSING": signals}),
    )

    response = service.check(_complaint("NEW-1"))

    assert response.decision is Decision.REVIEW_REQUIRED
    assert response.matched_incident_id is None
    # Only the two available signals contribute: (.15*1 + .15*.9) / .30.
    assert response.score == pytest.approx(0.95)
    assert response.reasons == [REASON_MISSING_CORE_ANCHOR]
    assert response.signals["text"].status is SignalStatus.UNAVAILABLE
    assert response.signals["text"].score is None
    assert response.signals["location"].status is SignalStatus.INVALID
    assert response.signals["location"].score is None
    assert response.signals["category"].status is SignalStatus.AVAILABLE


def test_explicit_contradiction_blocks_duplicate() -> None:
    signals = {
        "text": available_signal(0.95, "TEXT_EMBEDDING_SIMILARITY"),
        "location": available_signal(
            0.30,
            "LOCATION_NEAR",
            {
                "conflict": True,
                "conflict_code": "LOCATION_IDENTIFIER_CONFLICT",
            },
        ),
        "category": available_signal(1.0, "CATEGORY_EXACT_MATCH"),
        "time": available_signal(0.90, "TIME_CLOSE"),
    }
    service, _ = _service(
        [_complaint("CMP-CONFLICT")],
        _mapping_comparators({"CMP-CONFLICT": signals}),
    )

    response = service.check(_complaint("NEW-1"))

    assert response.decision is Decision.REVIEW_REQUIRED
    assert response.matched_incident_id is None
    assert response.score == pytest.approx(0.755)
    assert response.reasons == [REASON_CONTRADICTION_LOCATION]
    assert response.signals["location"].details is not None
    assert response.signals["location"].details["conflict"] is True


def test_embedding_error_is_preserved_and_not_treated_as_zero() -> None:
    service, _ = _service(
        [_complaint("CMP-EMB-ERR")],
        _mapping_comparators(
            {"CMP-EMB-ERR": _text_error_fallback_signals()}
        ),
    )

    response = service.check(_complaint("NEW-1"))

    # With text excluded and the remaining weights renormalised over .60, the
    # score is .9925, which is still DUPLICATE. If ERROR were coerced to an
    # available zero, the score would be .5955 and the decision would be
    # REVIEW_REQUIRED.
    assert response.decision is Decision.DUPLICATE
    assert response.matched_incident_id == "CMP-EMB-ERR"
    assert response.score == pytest.approx(0.5955 / 0.6)
    assert response.reasons == [REASON_SCORE_ABOVE_HIGH]
    assert response.signals["text"].status is SignalStatus.ERROR
    assert response.signals["text"].score is None


def test_embedding_error_can_still_return_new_with_weak_other_evidence() -> None:
    service, _ = _service(
        [_complaint("CMP-EMB-ERR-WEAK")],
        _mapping_comparators(
            {"CMP-EMB-ERR-WEAK": _text_error_weak_signals()}
        ),
    )

    response = service.check(_complaint("NEW-1"))

    # Current policy: the ERROR text signal is excluded and the remaining
    # weights are renormalised. Location + category clear the evidence gates,
    # but the combined score (.475) is below the low threshold (.55), so the
    # outcome is NEW. Whether a failed text backend should instead force review
    # is an open policy question, not decided here.
    assert response.decision is Decision.NEW
    assert response.matched_incident_id is None
    assert response.score is None
    assert response.reasons == [REASON_SCORE_BELOW_LOW]
    assert response.signals["text"].status is SignalStatus.ERROR
    assert response.signals["text"].score is None
    assert response.signals["location"].status is SignalStatus.AVAILABLE


def test_comparator_exception_becomes_error_signal() -> None:
    comparators = _mapping_comparators(
        {"CMP-ERR": _text_error_fallback_signals()}
    )
    comparators["text"] = RaisingTextComparator()
    service, _ = _service([_complaint("CMP-ERR")], comparators)

    response = service.check(_complaint("NEW-1"))

    assert response.decision is Decision.DUPLICATE
    assert response.score == pytest.approx(0.5955 / 0.6)
    assert response.signals["text"].status is SignalStatus.ERROR
    assert response.signals["text"].reason == "SIGNAL_ERROR_TEXT"
    assert response.signals["text"].details is not None
    assert response.signals["text"].details["error_type"] == "RuntimeError"
    assert response.signals["text"].details["error"] == "inference exploded"


# --------------------------------------------------------------------------- #
# Failure propagation and response mapping
# --------------------------------------------------------------------------- #
def test_repository_failure_propagates_and_is_never_new() -> None:
    comparators = _mapping_comparators({"CMP-1": _strong_signals()})
    repository = FakeRepository([_complaint("CMP-1")])
    repository.failure = RepositoryError("candidate store unavailable")
    service = DuplicateDetectionService(
        repository,
        comparators=comparators,
    )

    with pytest.raises(RepositoryError, match="candidate store unavailable"):
        service.check(_complaint("NEW-1"))

    assert all(comparator.calls == [] for comparator in comparators.values())


def test_response_mapping_uses_decision_outcome_and_complete_retrieval() -> None:
    signal = available_signal(0.42, "TEST_SIGNAL")
    outcome = DecisionOutcome(
        decision=Decision.REVIEW_REQUIRED,
        matched_incident_id=None,
        score=0.42,
        reasons=("TEST_REASON",),
        signals={"text": signal},
        candidates=(),
        policy_version="test-policy",
    )
    policy = StubDecisionPolicy(outcome)
    service, _ = _service(
        [_complaint("CMP-1")],
        _mapping_comparators({"CMP-1": _strong_signals()}),
        policy=policy,
    )

    response = service.check(_complaint("NEW-1"))

    assert response == DuplicateDetectionResponse(
        complaint_id="NEW-1",
        decision=Decision.REVIEW_REQUIRED,
        matched_incident_id=None,
        score=0.42,
        signals={"text": signal},
        reasons=["TEST_REASON"],
    )
    assert len(policy.calls) == 1
    candidates, retrieval_status = policy.calls[0]
    assert [candidate.incident_id for candidate in candidates] == ["CMP-1"]
    assert retrieval_status is RetrievalStatus.COMPLETE


def test_default_wiring_returns_new_for_empty_repository() -> None:
    # No candidates means the default embedding comparator is never invoked,
    # so this test does not download or load an embedding model.
    service = DuplicateDetectionService(FakeRepository([]))

    response = service.check(_complaint("NEW-1"))

    assert response.decision is Decision.NEW
    assert response.reasons == [REASON_NO_ELIGIBLE_CANDIDATES]
