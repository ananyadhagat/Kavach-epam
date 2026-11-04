"""Internal orchestration service for duplicate detection.

This module is the composition seam between the existing building blocks::

    ComplaintRepository -> comparators -> WeightedScoringEngine
                        -> DecisionPolicy -> DuplicateDetectionResponse

It contains no similarity maths, no scoring formula and no decision rules. Its
only job is to retrieve candidates, run each configured comparator once per
candidate, adapt the resulting signals to the M3 scoring engine, adapt the
engine result to the M4 ``CandidateScore`` contract, and let the decision policy
produce the final response.

Boundaries and failure semantics
--------------------------------
* The service depends on the existing internal
  :class:`~app.schemas.complaint.Complaint` model and returns the existing
  :class:`~app.schemas.duplicate_response.DuplicateDetectionResponse`. It does
  not define or change either contract.
* It is transport-free: no FastAPI, HTTP, database or vector-store code. The
  HTTP edge in :mod:`app.api` calls :meth:`check_detailed` and owns transport
  mapping.
* Candidate retrieval is delegated to
  :class:`~app.repositories.base.ComplaintRepository`. ``check()`` uses
  ``list_candidates()`` and treats a successful call as
  ``RetrievalStatus.COMPLETE``. ``check_detailed()`` uses the
  completeness-aware ``retrieve_candidates()`` and returns a
  :class:`DetectionResult` carrying the retrieval outcome.
* ``check()`` deliberately lets a
  :class:`~app.repositories.base.RepositoryError` propagate to its caller.
  ``check_detailed()`` converts a ``RepositoryError`` into ``FAILED`` retrieval
  with a ``REVIEW_REQUIRED`` result, and lets an unexpected exception such as
  ``TimeoutError`` propagate so the HTTP edge can return 5xx. Retrieval failure
  is never ``NEW`` and never a fabricated match.
* A comparator that raises unexpectedly is isolated as an ``ERROR`` signal with
  reason ``SIGNAL_ERROR_<NAME>``. The signal is excluded from scoring by the
  existing engine; it is never treated as a similarity of zero.
* The service defensively skips the incoming complaint id and duplicate
  candidate ids even though the in-memory repository already excludes and sorts
  records. The first occurrence of a duplicate id wins.

The service is synchronous because the repository contract is synchronous.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from app.comparators.base import Comparator, error_signal
from app.comparators.factory import build_core_comparators
from app.config.settings import DEFAULT_SETTINGS, Settings
from app.repositories.base import (
    INVALID_RETRIEVAL_RESULT,
    CandidateRetrieval,
    ComplaintRepository,
    RepositoryError,
    RetrievalFailure,
    RetrievalOutcome,
)
from app.schemas.complaint import Complaint
from app.schemas.duplicate_response import DuplicateDetectionResponse, SignalResult
from app.scoring.decision_policy import (
    CandidateScore,
    DecisionOutcome,
    DecisionPolicy,
    RetrievalStatus,
)
from app.scoring.engine import WeightedScoringEngine

#: Canonical core signal names. The factory produces exactly these keys.
CORE_SIGNAL_NAMES: tuple[str, ...] = ("text", "location", "category", "time")

#: Prefix used when a comparator raises unexpectedly.
SIGNAL_ERROR_PREFIX = "SIGNAL_ERROR_"

#: Maximum number of characters of an exception message kept in signal details.
_MAX_ERROR_DETAIL_CHARS = 300

#: Repository completeness -> decision-policy retrieval status.
_RETRIEVAL_STATUS_BY_OUTCOME: Mapping[RetrievalOutcome, RetrievalStatus] = {
    RetrievalOutcome.COMPLETE: RetrievalStatus.COMPLETE,
    RetrievalOutcome.PARTIAL: RetrievalStatus.INCOMPLETE,
    RetrievalOutcome.FAILED: RetrievalStatus.FAILED,
}


def _short_error(exc: BaseException) -> str:
    """Return a single-line, bounded description of ``exc``."""
    message = " ".join(str(exc).split())
    if not message:
        return exc.__class__.__name__
    if len(message) > _MAX_ERROR_DETAIL_CHARS:
        return message[: _MAX_ERROR_DETAIL_CHARS - 3] + "..."
    return message


@dataclass(frozen=True, slots=True)
class DetectionResult:
    """A decision plus the retrieval completeness that produced it.

    :meth:`DuplicateDetectionService.check_detailed` returns this richer result
    so the HTTP layer can distinguish a completed check from a partial or failed
    one without reinterpreting the decision policy.
    """

    incident_id: str
    outcome: DecisionOutcome
    retrieval_status: RetrievalStatus
    retrieval_failure: RetrievalFailure | None = None

    def to_response(self) -> DuplicateDetectionResponse:
        """Adapt the underlying policy outcome to the internal V1 response."""
        return self.outcome.to_response(self.incident_id)


class DuplicateDetectionService:
    """Compose retrieval, comparison, scoring and decision for one complaint.

    Parameters
    ----------
    repository:
        Candidate source. Only ``list_candidates(exclude_complaint_id=...)`` is
        used by this service.
    comparators:
        Mapping of signal name to comparator. Defaults to the four core
        comparators built by :func:`app.comparators.factory
        .build_core_comparators`. Every core signal name must be present and
        the mapping key must match ``comparator.name``.
    scoring_engine:
        Weighted scorer. Defaults to a new
        :class:`~app.scoring.engine.WeightedScoringEngine` using the resolved
        settings' weights.
    decision_policy:
        Decision policy. Defaults to a new
        :class:`~app.scoring.decision_policy.DecisionPolicy` using the resolved
        settings.
    settings:
        Configuration used for defaults. Defaults to
        :data:`app.config.settings.DEFAULT_SETTINGS`.
    """

    def __init__(
        self,
        repository: ComplaintRepository,
        *,
        comparators: Mapping[str, Comparator] | None = None,
        scoring_engine: WeightedScoringEngine | None = None,
        decision_policy: DecisionPolicy | None = None,
        settings: Settings | None = None,
    ) -> None:
        resolved_settings = DEFAULT_SETTINGS if settings is None else settings
        if not isinstance(resolved_settings, Settings):
            raise TypeError("settings must be a Settings instance or None")
        if not isinstance(repository, ComplaintRepository):
            raise TypeError(
                "repository must be a ComplaintRepository instance"
            )

        self._settings = resolved_settings
        self._repository = repository
        self._comparators = self._resolve_comparators(
            comparators, resolved_settings
        )
        self._scoring_engine = self._resolve_scoring_engine(
            scoring_engine, resolved_settings
        )
        self._decision_policy = self._resolve_decision_policy(
            decision_policy, resolved_settings
        )

    @property
    def settings(self) -> Settings:
        """The resolved configuration used to build defaults."""
        return self._settings

    def check(self, complaint: Complaint) -> DuplicateDetectionResponse:
        """Run the full duplicate-detection pipeline for ``complaint``.

        Raises
        ------
        TypeError:
            If ``complaint`` is not a :class:`Complaint`.
        RepositoryError:
            If candidate retrieval fails. This is intentionally propagated: a
            failed retrieval is not evidence that the complaint is ``NEW``.
        ScoringError:
            If the scoring engine rejects malformed evidence or configuration.
            This is a programming/configuration error, not a business outcome.
        """

        if not isinstance(complaint, Complaint):
            raise TypeError("complaint must be a Complaint instance")

        candidates = self._repository.list_candidates(
            exclude_complaint_id=complaint.complaint_id
        )
        eligible = self._eligible_candidates(complaint, candidates)
        candidate_scores = [
            self._score_candidate(complaint, candidate)
            for candidate in eligible
        ]

        # Successful retrieval (including an empty list) is complete. A
        # RepositoryError above propagates instead of reaching this point.
        outcome = self._decision_policy.decide(
            candidate_scores,
            retrieval_status=RetrievalStatus.COMPLETE,
        )
        return outcome.to_response(complaint.complaint_id)

    def check_detailed(self, complaint: Complaint) -> DetectionResult:
        """Run detection while preserving retrieval completeness information.

        This is the integration edge for the Agent 3 HTTP contract. Unlike
        :meth:`check`, it does not assume a successful listing was exhaustive:
        it asks the repository for an explicit :class:`CandidateRetrieval`.

        A :class:`RepositoryError` becomes a ``FAILED`` retrieval result and is
        handed to the unchanged decision policy, which returns
        ``REVIEW_REQUIRED`` rather than ``NEW``. Unexpected exceptions (including
        timeouts) propagate so the HTTP layer can return a 5xx/timeout instead of
        fabricating a duplicate-check result.

        Raises
        ------
        TypeError:
            If ``complaint`` is not a :class:`Complaint`.
        Exception:
            Any unexpected infrastructure failure other than
            :class:`RepositoryError` is deliberately propagated.
        """

        if not isinstance(complaint, Complaint):
            raise TypeError("complaint must be a Complaint instance")

        try:
            retrieval = self._repository.retrieve_candidates(
                exclude_complaint_id=complaint.complaint_id
            )
            if not isinstance(retrieval, CandidateRetrieval):
                raise RepositoryError(
                    "repository.retrieve_candidates() must return a "
                    "CandidateRetrieval; got "
                    f"{type(retrieval).__name__}",
                    code=INVALID_RETRIEVAL_RESULT,
                )
            eligible = self._eligible_candidates(complaint, retrieval.candidates)
        except RepositoryError as exc:
            failure = RetrievalFailure(exc.code, _short_error(exc))
            outcome = self._decision_policy.decide(
                (),
                retrieval_status=RetrievalStatus.FAILED,
            )
            return DetectionResult(
                incident_id=complaint.complaint_id,
                outcome=outcome,
                retrieval_status=RetrievalStatus.FAILED,
                retrieval_failure=failure,
            )

        candidate_scores = [
            self._score_candidate(complaint, candidate)
            for candidate in eligible
        ]
        retrieval_status = _RETRIEVAL_STATUS_BY_OUTCOME[retrieval.outcome]
        outcome = self._decision_policy.decide(
            candidate_scores,
            retrieval_status=retrieval_status,
        )
        return DetectionResult(
            incident_id=complaint.complaint_id,
            outcome=outcome,
            retrieval_status=retrieval_status,
            retrieval_failure=(
                retrieval.failures[0]
                if retrieval.outcome is not RetrievalOutcome.COMPLETE
                else None
            ),
        )

    # ------------------------------------------------------------------ #
    # Candidate selection
    # ------------------------------------------------------------------ #
    @staticmethod
    def _eligible_candidates(
        complaint: Complaint,
        candidates: Iterable[Complaint],
    ) -> list[Complaint]:
        """Return unique candidates, excluding the incoming complaint.

        The in-memory repository already excludes the incoming id and sorts
        records. This guard is defensive: alternate repositories (or test
        doubles) may not honour that contract, and self-comparison must never
        produce a duplicate decision. The first occurrence of a duplicate id is
        retained so the result is deterministic.
        """

        if not isinstance(candidates, Iterable):
            raise RepositoryError(
                "repository.list_candidates() must return an iterable of "
                "Complaint records"
            )

        eligible: list[Complaint] = []
        seen_ids: set[str] = set()
        for candidate in candidates:
            if not isinstance(candidate, Complaint):
                raise RepositoryError(
                    "repository.list_candidates() must return Complaint "
                    f"records; got {type(candidate).__name__}"
                )
            candidate_id = candidate.complaint_id
            if candidate_id == complaint.complaint_id:
                continue
            if candidate_id in seen_ids:
                continue
            seen_ids.add(candidate_id)
            eligible.append(candidate)
        return eligible

    # ------------------------------------------------------------------ #
    # Comparison and scoring
    # ------------------------------------------------------------------ #
    def _score_candidate(
        self,
        complaint: Complaint,
        candidate: Complaint,
    ) -> CandidateScore:
        """Compare one candidate, score it and adapt to the M3 -> M4 boundary."""

        signals = self._compare(complaint, candidate)
        result = self._scoring_engine.score(signals)
        return result.to_candidate_score(candidate.complaint_id)

    def _compare(
        self,
        complaint: Complaint,
        candidate: Complaint,
    ) -> dict[str, SignalResult]:
        """Run every configured comparator, isolating unexpected failures."""

        return {
            name: self._run_comparator(name, comparator, complaint, candidate)
            for name, comparator in self._comparators.items()
        }

    @staticmethod
    def _run_comparator(
        name: str,
        comparator: Comparator,
        complaint: Complaint,
        candidate: Complaint,
    ) -> SignalResult:
        """Return a comparator result or an ``ERROR`` signal.

        Only unexpected exceptions and invalid return types are converted. A
        comparator's own ``UNAVAILABLE`` / ``INVALID`` / ``ERROR`` results are
        preserved exactly as emitted.
        """

        try:
            result = comparator.compare(complaint, candidate)
        except Exception as exc:  # noqa: BLE001 - isolated as an ERROR signal
            return error_signal(
                f"{SIGNAL_ERROR_PREFIX}{name.upper()}",
                {
                    "signal": name,
                    "error_type": type(exc).__name__,
                    "error": _short_error(exc),
                },
            )

        if not isinstance(result, SignalResult):
            return error_signal(
                f"{SIGNAL_ERROR_PREFIX}{name.upper()}",
                {
                    "signal": name,
                    "error_type": "InvalidComparatorResult",
                    "error": (
                        "comparator returned "
                        f"{type(result).__name__}; expected SignalResult"
                    ),
                },
            )
        return result

    # ------------------------------------------------------------------ #
    # Collaborator construction and validation
    # ------------------------------------------------------------------ #
    @staticmethod
    def _resolve_comparators(
        comparators: Mapping[str, Comparator] | None,
        settings: Settings,
    ) -> dict[str, Comparator]:
        if comparators is None:
            return build_core_comparators(settings)

        if not isinstance(comparators, Mapping):
            raise TypeError(
                "comparators must be a mapping of signal name to Comparator"
            )

        resolved = dict(comparators)
        missing = [name for name in CORE_SIGNAL_NAMES if name not in resolved]
        if missing:
            raise ValueError(
                "missing core comparator(s): " + ", ".join(missing)
            )

        for name, comparator in resolved.items():
            if not isinstance(name, str) or not name.strip():
                raise ValueError("comparator keys must be non-empty strings")
            if not isinstance(comparator, Comparator):
                raise TypeError(
                    f"comparator for {name!r} must be a Comparator instance"
                )
            if comparator.name != name:
                raise ValueError(
                    f"comparator key {name!r} does not match "
                    f"comparator.name {comparator.name!r}"
                )
        return resolved

    @staticmethod
    def _resolve_scoring_engine(
        scoring_engine: WeightedScoringEngine | None,
        settings: Settings,
    ) -> WeightedScoringEngine:
        if scoring_engine is None:
            return WeightedScoringEngine(settings.weights)
        if not isinstance(scoring_engine, WeightedScoringEngine):
            raise TypeError(
                "scoring_engine must be a WeightedScoringEngine instance or None"
            )
        return scoring_engine

    @staticmethod
    def _resolve_decision_policy(
        decision_policy: DecisionPolicy | None,
        settings: Settings,
    ) -> DecisionPolicy:
        if decision_policy is None:
            return DecisionPolicy(settings)
        if not isinstance(decision_policy, DecisionPolicy):
            raise TypeError(
                "decision_policy must be a DecisionPolicy instance or None"
            )
        return decision_policy


__all__ = [
    "CORE_SIGNAL_NAMES",
    "DetectionResult",
    "DuplicateDetectionService",
    "SIGNAL_ERROR_PREFIX",
]
