"""Map an internal detection result to the Agent 3 M3 HTTP contract.

This module is a thin adapter. It does not score candidates, re-rank them by a
new formula, or make a second duplicate decision. It applies only the contract
rules that sit *outside* the internal decision policy:

* repository completeness becomes ``processing_status``;
* incomplete or failed retrieval is always surfaced as ``REVIEW_REQUIRED``;
* top-level ``matched_incident_id``/``score`` repeat the first candidate for
  non-``NEW`` decisions;
* the contract's error object is populated for incomplete/failed searches.

The policy's decision, reason codes and candidate order are preserved otherwise.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from app.repositories.base import RetrievalFailure
from app.schemas.duplicate_response import Decision
from app.schemas.m3_response import (
    M3Candidate,
    M3DuplicateCheckResponse,
    M3Error,
    ProcessingStatus,
)
from app.scoring.decision_policy import (
    REASON_RETRIEVAL_FAILED,
    REASON_RETRIEVAL_INCOMPLETE,
    RankedCandidate,
    RetrievalStatus,
)
from app.services.detection_service import DetectionResult

_PROCESSING_STATUS_BY_RETRIEVAL = {
    RetrievalStatus.COMPLETE: ProcessingStatus.COMPLETED,
    RetrievalStatus.INCOMPLETE: ProcessingStatus.PARTIAL,
    RetrievalStatus.FAILED: ProcessingStatus.FAILED,
}


def _processing_status(result: DetectionResult) -> ProcessingStatus:
    return _PROCESSING_STATUS_BY_RETRIEVAL[result.retrieval_status]


def _fallback_failure(status: ProcessingStatus) -> RetrievalFailure:
    if status is ProcessingStatus.PARTIAL:
        return RetrievalFailure(
            "RETRIEVAL_INCOMPLETE",
            "Candidate retrieval was incomplete.",
        )
    return RetrievalFailure(
        "RETRIEVAL_FAILED",
        "Candidate retrieval failed.",
    )


def _retrieval_reason(status: ProcessingStatus) -> str:
    if status is ProcessingStatus.FAILED:
        return REASON_RETRIEVAL_FAILED
    return REASON_RETRIEVAL_INCOMPLETE


def _unique_codes(codes: list[str]) -> list[str]:
    unique: list[str] = []
    for code in codes:
        if code not in unique:
            unique.append(code)
    return unique


def _candidate_reason_codes(candidate: RankedCandidate) -> list[str]:
    """Keep every code the policy already attached to a candidate."""
    return _unique_codes(
        [*candidate.reasons, *candidate.contradictions]
    )


def to_m3_response(
    result: DetectionResult,
    *,
    check_id: str | None = None,
    checked_at: datetime | None = None,
) -> M3DuplicateCheckResponse:
    """Adapt ``result`` to the exact Agent 3 response shape.

    ``check_id`` and ``checked_at`` are injectable for deterministic tests; in
    production they are generated per request.
    """

    if not isinstance(result, DetectionResult):
        raise TypeError("result must be a DetectionResult")

    status = _processing_status(result)
    decision = result.outcome.decision
    if status is not ProcessingStatus.COMPLETED:
        # Contract rule: partial/failed search is never NEW and never asserted
        # as a confirmed duplicate. The policy's candidate evidence is retained.
        decision = Decision.REVIEW_REQUIRED

    candidates = [
        M3Candidate(
            matched_incident_id=candidate.incident_id,
            similarity_score=float(candidate.score),
            reason_codes=_candidate_reason_codes(candidate),
        )
        for candidate in result.outcome.candidates
        if candidate.score is not None
    ]
    # Stable sort: the policy already orders by score; repeating it here makes
    # the wire invariant explicit without changing ties or introducing a second
    # ranking formula.
    candidates.sort(key=lambda candidate: -candidate.similarity_score)

    if decision is Decision.NEW:
        matched_incident_id = None
        score = None
    elif candidates:
        matched_incident_id = candidates[0].matched_incident_id
        score = candidates[0].similarity_score
    else:
        matched_incident_id = None
        score = None

    reasons = list(result.outcome.reasons)
    error: M3Error | None = None
    if status is not ProcessingStatus.COMPLETED:
        reasons = _unique_codes([*reasons, _retrieval_reason(status)])
        failure = result.retrieval_failure or _fallback_failure(status)
        error = M3Error(code=failure.code, message=failure.message)

    generated_check_id = str(uuid4()) if check_id is None else check_id
    generated_checked_at = (
        datetime.now(timezone.utc) if checked_at is None else checked_at
    )

    return M3DuplicateCheckResponse(
        check_id=generated_check_id,
        incident_id=result.incident_id,
        decision=decision,
        processing_status=status,
        policy_version=result.outcome.policy_version,
        checked_at=generated_checked_at,
        matched_incident_id=matched_incident_id,
        score=score,
        reason_codes=reasons,
        candidates=candidates,
        error=error,
    )


__all__ = ["to_m3_response"]
