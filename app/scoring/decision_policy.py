"""Duplicate-decision policy (Phase 4 / M4).

Scope
-----
This module decides exactly one thing: given **already-computed** per-candidate
evidence, it maps that evidence to ``DUPLICATE`` / ``REVIEW_REQUIRED`` / ``NEW``
with explicit, machine-readable reason codes. It deliberately does **not**:

* compute similarities (that is the comparators' job — Phase 3),
* combine signals into a weighted score (that is the M3 scoring engine,
  :class:`~app.scoring.engine.WeightedScoringEngine`),
* retrieve candidates, touch the repository, the database, the network or HTTP,
* merge, delete, mutate or auto-resolve complaints, or train any model.

M3 -> M4 boundary
-----------------
Phase 4 has two milestones: M3 (weighted scoring engine) and M4 (this decision
policy). M3 is implemented in :mod:`app.scoring.engine`. Its
:class:`~app.scoring.engine.ScoringResult` is adapted through
:meth:`~app.scoring.engine.ScoringResult.to_candidate_score` into this module's
*domain input contract*, :class:`CandidateScore`.

The policy consumes that contract and remains independently testable. It does not
import the scoring engine at runtime, and it never recomputes or second-guesses
the supplied score; it only validates and judges it.

Interpretation notes (documented deviations)
--------------------------------------------
The authoritative gate order is ``docs/duplicate_detection/matching_policy.md``
section 6.4. Two details needed a documented reading:

1. The document's §6.1 (evidence requirements) and §6.4 (gate order) interact.
   This implementation checks, in order: minimum evidence, core anchor,
   contradictions, corroboration, ambiguity, then the threshold bands. All
   evidence checks therefore precede the tie and threshold checks, exactly as
   §6.4 requires; contradictions are checked before corroboration so that the
   more specific, more actionable disqualifier is the one reported.
2. Ambiguity (a top-two score gap smaller than the margin) is applied literally
   *before* the threshold bands, so two near-equal low-scoring candidates are
   sent to ``REVIEW_REQUIRED`` rather than ``NEW``. This is the conservative
   reading and is covered by an explicit test.

Consequence: ``NEW`` requires that the best candidate was *evaluable* (met the
evidence gates) and that the top candidates were not tied. A low score attached
to a candidate we could not adequately evaluate is sent to review, not declared
new — a deliberate, conservative choice.

This module reuses the Phase 2 response schema (:class:`~app.schemas
.duplicate_response.DuplicateDetectionResponse`); the dataclasses here are
*inputs* and an internal result, not an HTTP contract.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from enum import Enum

from app.config.settings import (
    DEFAULT_SETTINGS,
    DecisionPolicySettings,
    DecisionThresholds,
    Settings,
)
from app.schemas.duplicate_response import (
    Decision,
    DuplicateDetectionResponse,
    SignalResult,
    SignalStatus,
)

# --------------------------------------------------------------------------- #
# Canonical machine-readable reason codes.
#
# Names follow ``matching_policy.md`` §11. The two ``CONTRADICTION_*`` codes
# stand in for the document's illustrative ``LOCATION_CONFLICT`` /
# ``CATEGORY_CONFLICT``; the underlying comparator-specific conflict code (for
# example ``LOCATION_IDENTIFIER_CONFLICT`` or ``CATEGORY_INCOMPATIBLE``) is kept
# on the per-candidate summary so nothing is lost.
# --------------------------------------------------------------------------- #
REASON_SCORE_ABOVE_HIGH = "SCORE_ABOVE_HIGH_THRESHOLD"
REASON_SCORE_BETWEEN_THRESHOLDS = "SCORE_BETWEEN_THRESHOLDS"
REASON_SCORE_BELOW_LOW = "SCORE_BELOW_LOW_THRESHOLD"
REASON_INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
REASON_MISSING_CORE_ANCHOR = "MISSING_CORE_ANCHOR"
REASON_CONTRADICTION_LOCATION = "CONTRADICTION_LOCATION_MISMATCH"
REASON_CONTRADICTION_CATEGORY = "CONTRADICTION_CATEGORY_INCOMPATIBLE"
REASON_AMBIGUOUS_TIED = "AMBIGUOUS_TIED_CANDIDATES"
REASON_NO_ELIGIBLE_CANDIDATES = "NO_ELIGIBLE_CANDIDATES"
REASON_INVALID_SCORE = "INVALID_SCORE"
REASON_RETRIEVAL_INCOMPLETE = "CANDIDATE_RETRIEVAL_INCOMPLETE"
REASON_RETRIEVAL_FAILED = "CANDIDATE_RETRIEVAL_FAILED"

_CORE_SIGNAL_NAMES: tuple[str, ...] = ("text", "location", "category", "time")

# Comparator-specific conflict codes mapped to the policy's canonical reason
# codes. The mapping is deliberately small and explicit; an unrecognised
# explicit contradiction is still disqualifying and is surfaced verbatim.
_EXPLICIT_CONTRADICTION_REASONS: Mapping[str, str] = {
    "LOCATION_IDENTIFIER_CONFLICT": REASON_CONTRADICTION_LOCATION,
    "LOCATION_FACILITY_CONFLICT": REASON_CONTRADICTION_LOCATION,
    "CATEGORY_INCOMPATIBLE": REASON_CONTRADICTION_CATEGORY,
    REASON_CONTRADICTION_LOCATION: REASON_CONTRADICTION_LOCATION,
    REASON_CONTRADICTION_CATEGORY: REASON_CONTRADICTION_CATEGORY,
}

# Internal classification tags for one candidate's evidence.
_SCORED = "scored"
_UNSCORABLE = "unscorable"
_INVALID = "invalid"


class RetrievalStatus(str, Enum):
    """How complete the candidate retrieval behind a decision was.

    The decision policy performs no retrieval itself; the caller states how
    trustworthy the candidate set is. ``NEW`` is only ever allowed when
    retrieval was ``COMPLETE`` — an empty or thin candidate set from an
    incomplete/failed search is not evidence that no duplicate exists.
    """

    COMPLETE = "COMPLETE"
    INCOMPLETE = "INCOMPLETE"
    FAILED = "FAILED"


@dataclass(frozen=True)
class CandidateScore:
    """One candidate's already-computed evidence (the M3 -> M4 boundary).

    This is a **domain contract**, not an HTTP schema. It is what the scoring
    engine (M3) must hand to the decision policy (M4).

    Parameters
    ----------
    incident_id:
        Identifier of the existing complaint this evidence describes.
    score:
        The scoring engine's combined *ranking* score for this candidate, or
        ``None`` when the engine could rank nothing (no ``AVAILABLE`` signal).
        It is **not** a probability and is **never** recomputed here. Any value
        that is not a finite number in ``[0, 1]`` marks the candidate invalid.
    signals:
        Per-signal results keyed by signal name (``text``, ``location``,
        ``category``, ``time``, optionally ``image``). Treated as read-only.
    contradictions:
        Optional explicit disqualifying codes already known for this candidate.
        The policy additionally derives contradictions from ``signals``. Any
        non-empty code here blocks ``DUPLICATE``; recognised comparator codes
        are normalised to the canonical ``CONTRADICTION_*`` reason codes and
        unrecognised codes are surfaced verbatim.
    reasons:
        Optional reason codes already attached to this candidate.
    """

    incident_id: str
    score: float | None
    signals: Mapping[str, SignalResult] = field(default_factory=dict)
    contradictions: tuple[str, ...] = ()
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class RankedCandidate:
    """A candidate summary returned for transparency / human review."""

    incident_id: str
    rank: int
    score: float | None
    contradictions: tuple[str, ...]
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class DecisionOutcome:
    """The decision policy's result.

    This is a domain object. :meth:`to_response` adapts it to the Phase 2
    :class:`~app.schemas.duplicate_response.DuplicateDetectionResponse`;
    the richer per-candidate data stays here (it maps to the deferred
    ``candidates`` response block from ``api_contract.md``).

    ``score`` is the *ranking* score of the leading candidate (``None`` for
    ``NEW`` and for retrieval-blocked reviews). It is never a probability.
    """

    decision: Decision
    matched_incident_id: str | None
    score: float | None
    reasons: tuple[str, ...]
    signals: Mapping[str, SignalResult]
    candidates: tuple[RankedCandidate, ...]
    policy_version: str

    @property
    def leading_candidate_id(self) -> str | None:
        """Top-ranked candidate, suggested for review (never asserted as a match)."""
        return self.candidates[0].incident_id if self.candidates else None

    def to_response(self, complaint_id: str) -> DuplicateDetectionResponse:
        """Adapt to the V1 response schema (reused from Phase 2)."""
        return DuplicateDetectionResponse(
            complaint_id=complaint_id,
            decision=self.decision,
            matched_incident_id=self.matched_incident_id,
            score=self.score,
            signals=dict(self.signals),
            reasons=list(self.reasons),
        )


@dataclass(frozen=True)
class _Evidence:
    """Derived evidence summary for a single scored candidate."""

    available_count: int
    has_core_anchor: bool
    corroborated: bool
    contradiction_codes: tuple[str, ...]


def _is_unit_score(value: object) -> bool:
    """Return True for a finite real number inside ``[0, 1]`` (never a bool)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    return math.isfinite(value) and 0.0 <= value <= 1.0


def _append_unique(items: list[str], value: str) -> None:
    if value not in items:
        items.append(value)


def _validate_policy_config(
    policy: DecisionPolicySettings,
    thresholds: DecisionThresholds,
    tie_margin: float,
) -> None:
    """Defensively re-validate configuration the policy depends on.

    Pydantic already validates :class:`~app.config.settings.Settings`. This guard
    exists because a caller can build one with ``model_construct`` (bypassing
    validation); invalid policy configuration must fail loudly rather than
    silently produce a wrong decision.
    """
    if isinstance(tie_margin, bool) or not isinstance(tie_margin, (int, float)):
        raise ValueError("ambiguity margin (tie_margin) must be a number")
    if not math.isfinite(tie_margin) or tie_margin < 0.0:
        raise ValueError("ambiguity margin (tie_margin) must be finite and >= 0")

    for name in ("high", "low"):
        value = getattr(thresholds, name)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"{name} threshold must be a number")
        if not math.isfinite(value) or not (0.0 <= value <= 1.0):
            raise ValueError(f"{name} threshold must be finite and within [0, 1]")
    if thresholds.low > thresholds.high:
        raise ValueError("low threshold must not exceed the high threshold")

    minimum = policy.min_available_signals
    if isinstance(minimum, bool) or not isinstance(minimum, int):
        raise ValueError("min_available_signals must be an integer")
    if not (1 <= minimum <= len(_CORE_SIGNAL_NAMES)):
        raise ValueError(
            f"min_available_signals must be between 1 and {len(_CORE_SIGNAL_NAMES)}"
        )

    for name in (
        "core_anchor_floor",
        "supportive_floor",
        "location_conflict_text_floor",
        "location_conflict_location_ceiling",
    ):
        value = getattr(policy, name)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"{name} must be a number")
        if not math.isfinite(value) or not (0.0 <= value <= 1.0):
            raise ValueError(f"{name} must be finite and within [0, 1]")

    if policy.location_conflict_location_ceiling >= policy.location_conflict_text_floor:
        raise ValueError(
            "location_conflict_location_ceiling must be less than "
            "location_conflict_text_floor"
        )


class DecisionPolicy:
    """Deterministic, side-effect-free duplicate-decision policy.

    The policy is *advisory* and *pure*: it never mutates its inputs, never
    retrieves data, never touches storage or the network and never computes
    similarities. Given the same candidates, configuration and retrieval status
    it always returns the same outcome.
    """

    def __init__(self, settings: Settings | None = None) -> None:
        resolved = DEFAULT_SETTINGS if settings is None else settings
        self._settings = resolved
        self._policy: DecisionPolicySettings = resolved.decision
        self._thresholds: DecisionThresholds = resolved.thresholds
        self._tie_margin = float(resolved.tie_margin)
        _validate_policy_config(self._policy, self._thresholds, self._tie_margin)

    @property
    def policy_version(self) -> str:
        """Identifier echoed into outcomes for reproducibility."""
        return self._settings.policy_version

    # ------------------------------------------------------------------ #
    # Public entry point
    # ------------------------------------------------------------------ #
    def decide(
        self,
        candidates: Iterable[CandidateScore],
        *,
        retrieval_status: RetrievalStatus = RetrievalStatus.COMPLETE,
    ) -> DecisionOutcome:
        """Return a :class:`DecisionOutcome` for one new complaint.

        Parameters
        ----------
        candidates:
            Already-scored candidate evidence (see :class:`CandidateScore`).
            The policy never mutates these objects.
        retrieval_status:
            Completeness of the search that produced ``candidates``. Defaults to
            ``COMPLETE``.
        """
        candidate_list = tuple(candidates)
        try:
            retrieval = RetrievalStatus(retrieval_status)
        except ValueError as exc:
            raise ValueError(f"unknown retrieval_status: {retrieval_status!r}") from exc

        scored: list[CandidateScore] = []
        unscorable: list[CandidateScore] = []
        saw_invalid = False
        for candidate in candidate_list:
            tag = self._classify(candidate)
            if tag == _SCORED:
                scored.append(candidate)
            elif tag == _INVALID:
                saw_invalid = True
            else:
                unscorable.append(candidate)

        # An unevaluable candidate means the evidence picture cannot be trusted:
        # never DUPLICATE, and never a confident NEW.
        if saw_invalid:
            return self._outcome(
                Decision.REVIEW_REQUIRED, None, None, [REASON_INVALID_SCORE], ()
            )

        # No candidates at all.
        if not candidate_list:
            if retrieval is RetrievalStatus.COMPLETE:
                return self._outcome(
                    Decision.NEW, None, None, [REASON_NO_ELIGIBLE_CANDIDATES], ()
                )
            return self._review_without_candidate(retrieval)

        # Candidates exist but none can be ranked.
        if not scored:
            summaries = self._null_summaries(unscorable)
            reasons = [REASON_INSUFFICIENT_EVIDENCE]
            if retrieval is not RetrievalStatus.COMPLETE:
                reasons.append(self._retrieval_reason(retrieval))
            signals = unscorable[0].signals if unscorable else {}
            return self._outcome(
                Decision.REVIEW_REQUIRED, None, None, reasons, summaries, signals
            )

        ordered = self._order(scored)
        summaries = self._summaries(ordered)
        best = ordered[0]
        evidence = self._evidence(best)

        # --- gates, in the documented order (matching_policy.md 6.4) --------- #
        # 1. evidence sufficiency
        if evidence.available_count < self._policy.min_available_signals:
            return self._review(best, summaries, [REASON_INSUFFICIENT_EVIDENCE])
        if self._policy.require_core_anchor and not evidence.has_core_anchor:
            return self._review(best, summaries, [REASON_MISSING_CORE_ANCHOR])

        # 2. contradictions (disqualifying, more specific than a low score)
        if evidence.contradiction_codes:
            return self._review(best, summaries, list(evidence.contradiction_codes))

        # 3. corroboration (a second, independent supportive signal)
        if self._policy.require_corroboration and not evidence.corroborated:
            return self._review(best, summaries, [REASON_INSUFFICIENT_EVIDENCE])

        # 4. ambiguity at the top
        if self._is_ambiguous(summaries):
            return self._review(best, summaries, [REASON_AMBIGUOUS_TIED])

        # 5. threshold bands
        best_score = float(best.score)  # _SCORED guarantees a numeric score
        if best_score >= self._thresholds.high:
            return self._outcome(
                Decision.DUPLICATE,
                best.incident_id,
                best_score,
                [REASON_SCORE_ABOVE_HIGH],
                summaries,
                best.signals,
            )
        if best_score >= self._thresholds.low:
            return self._review(best, summaries, [REASON_SCORE_BETWEEN_THRESHOLDS])

        # Below the low threshold: NEW, unless retrieval was not complete.
        if retrieval is not RetrievalStatus.COMPLETE:
            return self._review(
                best,
                summaries,
                [REASON_SCORE_BELOW_LOW, self._retrieval_reason(retrieval)],
            )
        return self._outcome(
            Decision.NEW, None, None, [REASON_SCORE_BELOW_LOW], summaries, best.signals
        )

    # ------------------------------------------------------------------ #
    # Candidate classification and ordering
    # ------------------------------------------------------------------ #
    def _classify(self, candidate: object) -> str:
        """Tag a candidate as ``scored``, ``unscorable`` or ``invalid``."""
        incident_id = getattr(candidate, "incident_id", None)
        if not isinstance(incident_id, str) or not incident_id.strip():
            return _INVALID

        signals = getattr(candidate, "signals", None)
        if signals is None or not isinstance(signals, Mapping):
            return _INVALID
        for signal in signals.values():
            if not isinstance(signal, SignalResult):
                return _INVALID
            if signal.status is SignalStatus.AVAILABLE:
                if not _is_unit_score(signal.score):
                    return _INVALID
            elif signal.score is not None:
                # A non-AVAILABLE signal must never carry a numeric score.
                return _INVALID

        score = getattr(candidate, "score", None)
        if score is None:
            if any(
                isinstance(signal, SignalResult)
                and signal.status is SignalStatus.AVAILABLE
                for signal in signals.values()
            ):
                # A scoreable candidate was handed over without a score.
                return _INVALID
            return _UNSCORABLE
        if not _is_unit_score(score):
            return _INVALID
        return _SCORED

    def _order(self, scored: list[CandidateScore]) -> list[CandidateScore]:
        """Total, deterministic ordering; best candidate first.

        The ordering is presentation-only: it never invents a decision. Beyond
        the combined score it uses documented stable tie-breakers (higher
        text/location/time signal, then ascending ``incident_id``) so equal
        scores order reproducibly. ``matching_policy.md`` §9 also mentions the
        raw absolute time gap; here the time *score* is used as its monotonic
        proxy because the score is all the policy receives.
        """
        return sorted(scored, key=self._sort_key)

    def _sort_key(self, candidate: CandidateScore) -> tuple[float, float, float, float, str]:
        return (
            -float(candidate.score if candidate.score is not None else 0.0),
            -self._signal_score(candidate, "location"),
            -self._signal_score(candidate, "text"),
            -self._signal_score(candidate, "time"),
            candidate.incident_id,
        )

    def _summaries(self, ordered: list[CandidateScore]) -> tuple[RankedCandidate, ...]:
        return tuple(
            RankedCandidate(
                incident_id=candidate.incident_id,
                rank=index + 1,
                score=float(candidate.score) if candidate.score is not None else None,
                contradictions=self._candidate_contradictions(candidate),
                reasons=tuple(candidate.reasons),
            )
            for index, candidate in enumerate(ordered)
        )

    def _null_summaries(
        self, candidates: Iterable[CandidateScore]
    ) -> tuple[RankedCandidate, ...]:
        ordered = sorted(candidates, key=lambda candidate: candidate.incident_id)
        return tuple(
            RankedCandidate(
                incident_id=candidate.incident_id,
                rank=index + 1,
                score=None,
                contradictions=self._candidate_contradictions(candidate),
                reasons=tuple(candidate.reasons),
            )
            for index, candidate in enumerate(ordered)
        )

    # ------------------------------------------------------------------ #
    # Evidence derivation
    # ------------------------------------------------------------------ #
    def _evidence(self, candidate: CandidateScore) -> _Evidence:
        available_count = 0
        supportive_count = 0
        for name in _CORE_SIGNAL_NAMES:
            score = self._signal_score_or_none(candidate, name)
            if score is None:
                continue
            available_count += 1
            if score >= self._policy.supportive_floor:
                supportive_count += 1

        has_core_anchor = (
            self._signal_score(candidate, "text") >= self._policy.core_anchor_floor
            or self._signal_score(candidate, "location") >= self._policy.core_anchor_floor
        )

        # Documented corroboration exception: an identifier match plus an exact
        # category match corroborate each other even if neither clears the floor.
        identifier_and_exact = (
            self._signal_reason(candidate, "location") == "LOCATION_IDENTIFIER_MATCH"
            and self._signal_reason(candidate, "category") == "CATEGORY_EXACT_MATCH"
        )
        corroborated = supportive_count >= 2 or identifier_and_exact

        contradictions = self._contradiction_codes(candidate)
        return _Evidence(
            available_count=available_count,
            has_core_anchor=has_core_anchor,
            corroborated=corroborated,
            contradiction_codes=contradictions,
        )

    def _contradiction_codes(self, candidate: CandidateScore) -> tuple[str, ...]:
        codes: list[str] = []

        # Explicit disqualifiers from the upstream contract are honoured even
        # when the corresponding signal details were not forwarded. Unknown
        # codes are kept verbatim: they still block DUPLICATE and preserve the
        # additive reason-code contract.
        for code in candidate.contradictions:
            if not isinstance(code, str):
                continue
            explicit = code.strip()
            if not explicit:
                continue
            _append_unique(
                codes,
                _EXPLICIT_CONTRADICTION_REASONS.get(explicit, explicit),
            )

        for name, signal in candidate.signals.items():
            if not isinstance(signal, SignalResult):
                continue
            details = signal.details
            if not isinstance(details, Mapping) or details.get("conflict") is not True:
                continue
            if name == "category":
                _append_unique(codes, REASON_CONTRADICTION_CATEGORY)
            elif name == "location":
                _append_unique(codes, REASON_CONTRADICTION_LOCATION)

        # C1: text clearly similar AND location clearly different.
        text_score = self._signal_score_or_none(candidate, "text")
        location_score = self._signal_score_or_none(candidate, "location")
        if (
            text_score is not None
            and location_score is not None
            and text_score >= self._policy.location_conflict_text_floor
            and location_score <= self._policy.location_conflict_location_ceiling
        ):
            _append_unique(codes, REASON_CONTRADICTION_LOCATION)

        return tuple(codes)

    @staticmethod
    def _candidate_contradictions(candidate: CandidateScore) -> tuple[str, ...]:
        """Comparator-specific conflict codes, surfaced for human review."""
        codes: list[str] = []
        for code in candidate.contradictions:
            _append_unique(codes, code)
        for signal in candidate.signals.values():
            if not isinstance(signal, SignalResult):
                continue
            details = signal.details
            if not isinstance(details, Mapping):
                continue
            conflict_code = details.get("conflict_code")
            if isinstance(conflict_code, str):
                _append_unique(codes, conflict_code)
        return tuple(codes)

    def _is_ambiguous(self, summaries: tuple[RankedCandidate, ...]) -> bool:
        if len(summaries) < 2:
            return False
        top, second = summaries[0], summaries[1]
        if top.score is None or second.score is None:
            return False
        return (top.score - second.score) < self._tie_margin

    # ------------------------------------------------------------------ #
    # Small helpers
    # ------------------------------------------------------------------ #
    @staticmethod
    def _signal_score(candidate: CandidateScore, name: str) -> float:
        """Available signal score, or ``-1.0`` when absent (sorts last)."""
        score = DecisionPolicy._signal_score_or_none(candidate, name)
        return -1.0 if score is None else score

    @staticmethod
    def _signal_score_or_none(candidate: CandidateScore, name: str) -> float | None:
        signal = candidate.signals.get(name)
        if (
            isinstance(signal, SignalResult)
            and signal.status is SignalStatus.AVAILABLE
            and signal.score is not None
        ):
            return float(signal.score)
        return None

    @staticmethod
    def _signal_reason(candidate: CandidateScore, name: str) -> str | None:
        signal = candidate.signals.get(name)
        if isinstance(signal, SignalResult):
            return signal.reason
        return None

    @staticmethod
    def _retrieval_reason(status: RetrievalStatus) -> str:
        if status is RetrievalStatus.FAILED:
            return REASON_RETRIEVAL_FAILED
        return REASON_RETRIEVAL_INCOMPLETE

    # ------------------------------------------------------------------ #
    # Outcome builders
    # ------------------------------------------------------------------ #
    def _review(
        self,
        best: CandidateScore,
        summaries: tuple[RankedCandidate, ...],
        reasons: list[str],
    ) -> DecisionOutcome:
        return self._outcome(
            Decision.REVIEW_REQUIRED,
            None,
            float(best.score) if best.score is not None else None,
            reasons,
            summaries,
            best.signals,
        )

    def _review_without_candidate(self, retrieval: RetrievalStatus) -> DecisionOutcome:
        return self._outcome(
            Decision.REVIEW_REQUIRED,
            None,
            None,
            [self._retrieval_reason(retrieval)],
            (),
        )

    def _outcome(
        self,
        decision: Decision,
        matched_incident_id: str | None,
        score: float | None,
        reasons: list[str],
        candidates: tuple[RankedCandidate, ...],
        signals: Mapping[str, SignalResult] | None = None,
    ) -> DecisionOutcome:
        unique_reasons: list[str] = []
        for reason in reasons:
            _append_unique(unique_reasons, reason)
        return DecisionOutcome(
            decision=decision,
            matched_incident_id=matched_incident_id,
            score=score,
            reasons=tuple(unique_reasons),
            signals=dict(signals) if signals else {},
            candidates=candidates,
            policy_version=self._settings.policy_version,
        )
