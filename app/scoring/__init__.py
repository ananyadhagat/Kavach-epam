"""Scoring and decision layer (Phase 4).

This package implements both Phase 4 milestones:

* **M3 — weighted scoring engine**: :class:`~app.scoring.engine
  .WeightedScoringEngine` combines the four core :class:`~app.schemas
  .duplicate_response.SignalResult` values into one ranking score using
  :class:`~app.config.settings.MatchingWeights`. Its result is
  :class:`~app.scoring.engine.ScoringResult`, which adapts to
  :class:`~app.scoring.decision_policy.CandidateScore`.
* **M4 — decision policy**: :class:`~app.scoring.decision_policy.DecisionPolicy`
  consumes already-computed candidate evidence and maps it to ``DUPLICATE`` /
  ``REVIEW_REQUIRED`` / ``NEW``.

The scoring engine is transport-free and never makes a decision; the decision
policy never computes similarities or combines signals. Their shared boundary is
:class:`~app.scoring.decision_policy.CandidateScore`.
"""

from app.scoring.decision_policy import (
    CandidateScore,
    DecisionOutcome,
    DecisionPolicy,
    RankedCandidate,
    RetrievalStatus,
)
from app.scoring.engine import (
    REASON_CONFLICT_PRESENT,
    REASON_NO_AVAILABLE_SIGNAL,
    REASON_NO_POSITIVE_WEIGHT_SIGNAL,
    REASON_SCORE_COMPUTED,
    REASON_SCORE_RENORMALISED,
    REASON_SCORE_UNAVAILABLE,
    REASON_UNWEIGHTED_SIGNAL_PRESENT,
    REASON_ZERO_WEIGHT_SIGNAL_IGNORED,
    ScoringError,
    ScoringResult,
    WeightedScoringEngine,
)

__all__ = [
    "CandidateScore",
    "DecisionOutcome",
    "DecisionPolicy",
    "REASON_CONFLICT_PRESENT",
    "REASON_NO_AVAILABLE_SIGNAL",
    "REASON_NO_POSITIVE_WEIGHT_SIGNAL",
    "REASON_SCORE_COMPUTED",
    "REASON_SCORE_RENORMALISED",
    "REASON_SCORE_UNAVAILABLE",
    "REASON_UNWEIGHTED_SIGNAL_PRESENT",
    "REASON_ZERO_WEIGHT_SIGNAL_IGNORED",
    "RankedCandidate",
    "RetrievalStatus",
    "ScoringError",
    "ScoringResult",
    "WeightedScoringEngine",
]
