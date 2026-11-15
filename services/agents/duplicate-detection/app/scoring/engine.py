"""Weighted scoring engine (Phase 4 / M3).

Scope
-----
This module performs exactly one job: combine the four core comparator signals
(``text``, ``location``, ``category``, ``time``) into one ranking score in
``[0, 1]`` using the configured :class:`~app.config.settings.MatchingWeights`.
It does not retrieve candidates, compute similarities, decide whether a
candidate is a duplicate, persist anything or touch HTTP.

The formula is the one in ``docs/duplicate_detection/matching_policy.md`` §3::

    score = Σ(w_i × s_i) / Σ(w_i)      for signals with status == AVAILABLE and w_i > 0

Only ``AVAILABLE`` signals contribute. ``UNAVAILABLE``, ``INVALID`` and
``ERROR`` signals are excluded from **both** the numerator and the denominator;
they are never treated as a score of zero. If no usable signal with a positive
weight remains, the combined score is ``None`` (the candidate cannot be ranked).

Terminology note
----------------
``matching_policy.md`` §5 calls this component ``ScoringPolicy`` and names its
exception ``ScoringError``. The requested implementation class is
:class:`WeightedScoringEngine`; it follows the authoritative §3 formula and the
documented exception name. This is an intentional naming reconciliation, not a
second scoring policy.

Result and boundary
-------------------
:class:`ScoringResult` is a domain object, not an HTTP schema. It keeps every
input signal, the score, the weights actually used, the normalisation
denominator and deterministic reason codes. :meth:`ScoringResult
.to_candidate_score` adapts it to
:class:`~app.scoring.decision_policy.CandidateScore`, the documented M3 -> M4
boundary, without making this module depend on the decision policy.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING, Any

from app.config.settings import DEFAULT_SETTINGS, MatchingWeights
from app.schemas.duplicate_response import SignalResult, SignalStatus

if TYPE_CHECKING:  # pragma: no cover - import-time only for type checkers
    from app.scoring.decision_policy import CandidateScore

# --------------------------------------------------------------------------- #
# Canonical machine-readable reason codes (open, additive set).
# --------------------------------------------------------------------------- #
REASON_SCORE_COMPUTED = "WEIGHTED_SCORE_COMPUTED"
REASON_SCORE_UNAVAILABLE = "WEIGHTED_SCORE_UNAVAILABLE"
REASON_NO_AVAILABLE_SIGNAL = "NO_AVAILABLE_SIGNAL"
REASON_NO_POSITIVE_WEIGHT_SIGNAL = "NO_POSITIVE_WEIGHT_SIGNAL"
REASON_SCORE_RENORMALISED = "SCORE_RENORMALISED_FOR_AVAILABLE_WEIGHTS"
REASON_ZERO_WEIGHT_SIGNAL_IGNORED = "ZERO_WEIGHT_SIGNAL_IGNORED"
REASON_UNWEIGHTED_SIGNAL_PRESENT = "UNWEIGHTED_SIGNAL_PRESENT"
REASON_CONFLICT_PRESENT = "CONFLICT_METADATA_PRESENT"

_CORE_SIGNAL_NAMES: tuple[str, ...] = ("text", "location", "category", "time")


class ScoringError(ValueError):
    """Raised when scoring input or configuration is invalid.

    This is deliberately a ``ValueError`` so callers can treat malformed
    configuration and malformed/out-of-range signal evidence uniformly. The
    name follows ``matching_policy.md`` §5/§8.
    """


def _as_mapping(value: object, field_name: str) -> Mapping[str, SignalResult]:
    """Return ``value`` as a mapping, or raise a clear error."""
    if not isinstance(value, Mapping):
        raise TypeError(f"{field_name} must be a mapping of signal name to SignalResult")
    return value


@dataclass(frozen=True)
class ScoringResult:
    """The weighted-scoring engine's domain result.

    Parameters
    ----------
    score:
        Combined ranking score in ``[0, 1]``, or ``None`` when no ``AVAILABLE``
        signal with a positive configured weight contributed.
    signals:
        Every input signal, keyed by name and in a deterministic order (the
        four core names first, then additional signal names sorted). Unweighted
        signals (for example a future ``image``) remain here for downstream
        evidence even though they never affect ``score``.
    available_scores:
        Scores of **all** ``AVAILABLE`` signals, including unweighted extras.
    configured_weights:
        The configured weights for the four core signals (which may include
        zeros). Extras are intentionally absent because they have no weight.
    weights_used:
        Effective, normalised weights for the signals that contributed to
        ``score`` (``configured weight / weight_total``). Empty when no score
        can be produced. Values sum to ``1.0`` (within floating-point error).
    contributions:
        Each contributing signal's share of ``score``
        (``weights_used[name] * available_scores[name]``); these sum to
        ``score`` (within floating-point error).
    weighted_sum:
        The numerator ``Σ(w_i × s_i)`` before normalisation.
    weight_total:
        The denominator ``Σ(w_i)`` over contributing signals. ``0.0`` when no
        score can be produced.
    configured_weight_total:
        Sum of all four configured core weights (including zero weights).
    normalised:
        ``True`` when at least one configured-weight core signal did not
        contribute (it was unavailable, invalid, errored or zero-weight), so the
        denominator is smaller than ``configured_weight_total``. Always
        ``False`` when ``score is None``.
    contradictions:
        Comparator-specific conflict codes (``details["conflict_code"]``) in
        deterministic signal order. The full conflict metadata, including
        ``details["conflict"]``, remains untouched on :attr:`signals`.
    reasons:
        Deterministic engine reason codes; see the ``REASON_*`` constants.
    """

    score: float | None
    signals: Mapping[str, SignalResult]
    available_scores: Mapping[str, float]
    configured_weights: Mapping[str, float]
    weights_used: Mapping[str, float]
    contributions: Mapping[str, float]
    weighted_sum: float
    weight_total: float
    configured_weight_total: float
    normalised: bool
    contradictions: tuple[str, ...]
    reasons: tuple[str, ...]

    def to_candidate_score(self, incident_id: str) -> "CandidateScore":
        """Adapt this result to the M3 -> M4 :class:`CandidateScore` contract.

        The adapter is intentionally thin: it maps the combined score, every
        signal, the conflict codes and the engine reason codes. The decision
        policy remains unchanged and chooses the final outcome.
        """
        # Local import keeps this module focused on scoring at import time and
        # avoids a hard M3 -> M4 module cycle if policy layering changes later.
        from app.scoring.decision_policy import CandidateScore

        return CandidateScore(
            incident_id=incident_id,
            score=self.score,
            signals=dict(self.signals),
            contradictions=self.contradictions,
            reasons=self.reasons,
        )


class WeightedScoringEngine:
    """Deterministic weighted scorer for one candidate's core signals.

    Parameters
    ----------
    weights:
        The existing :class:`~app.config.settings.MatchingWeights`. Defaults to
        ``DEFAULT_SETTINGS.weights``. Weights are defensively re-validated so
        objects built with ``model_construct`` cannot bypass validation.

    The engine is pure and side-effect free: it never mutates signals, weights
    or configuration and always returns the same result for the same inputs.
    """

    def __init__(self, weights: MatchingWeights | None = None) -> None:
        resolved = DEFAULT_SETTINGS.weights if weights is None else weights
        if not isinstance(resolved, MatchingWeights):
            raise TypeError("weights must be a MatchingWeights instance or None")
        values = _validate_weights(resolved)
        self._weights: Mapping[str, float] = MappingProxyType(values)
        self._configured_weight_total = math.fsum(values.values())

    @property
    def weights(self) -> Mapping[str, float]:
        """Read-only view of the validated configured core weights."""
        return self._weights

    # ------------------------------------------------------------------ #
    # Public entry point
    # ------------------------------------------------------------------ #
    def score(
        self,
        signals: Mapping[str, SignalResult] | None = None,
        *,
        text: SignalResult | None = None,
        location: SignalResult | None = None,
        category: SignalResult | None = None,
        time: SignalResult | None = None,
        extra_signals: Mapping[str, SignalResult] | None = None,
    ) -> ScoringResult:
        """Score one candidate.

        The four core signals may be supplied either as a mapping::

            engine.score({"text": ..., "location": ..., "category": ..., "time": ...})

        or as keyword arguments::

            engine.score(text=..., location=..., category=..., time=...)

        All four core signals are required. Future/unweighted signals can be
        supplied as extra mapping entries or via ``extra_signals``; they are
        retained on the result but never affect the combined score.

        Raises
        ------
        TypeError
            If both calling styles are mixed or a mapping is not supplied.
        ValueError
            If a core signal is missing, an extra signal name collides with a
            core name, or :class:`ScoringError` for invalid evidence/weights.
        """
        provided = self._collect_signals(
            signals,
            text=text,
            location=location,
            category=category,
            time=time,
            extra_signals=extra_signals,
        )

        ordered: list[tuple[str, SignalResult]] = [
            (name, provided[name]) for name in _CORE_SIGNAL_NAMES
        ]
        ordered.extend(
            (name, provided[name])
            for name in sorted(name for name in provided if name not in _CORE_SIGNAL_NAMES)
        )

        available_scores: dict[str, float] = {}
        contributing: dict[str, tuple[float, float]] = {}
        zero_weight_available: list[str] = []

        for name, signal in ordered:
            status, signal_score = _validate_signal(name, signal)
            if status is not SignalStatus.AVAILABLE:
                continue
            assert signal_score is not None  # narrowed by _validate_signal
            available_scores[name] = signal_score

            weight = self._weights.get(name)
            if weight is None:
                # Unweighted future signals remain evidence but cannot enter
                # the weighted average.
                continue
            if weight > 0.0:
                contributing[name] = (weight, signal_score)
            else:
                zero_weight_available.append(name)

        weight_total = math.fsum(weight for weight, _ in contributing.values())
        if not contributing or weight_total <= 0.0:
            return self._unscorable_result(
                ordered,
                available_scores,
                zero_weight_available=zero_weight_available,
            )

        weighted_sum = math.fsum(
            weight * signal_score for weight, signal_score in contributing.values()
        )
        combined = weighted_sum / weight_total
        if not math.isfinite(combined):
            raise ScoringError("combined score must be finite")
        # Mathematically the weighted average is already in [0, 1]; clamp only
        # to absorb floating-point overshoot at the boundaries.
        combined = min(1.0, max(0.0, combined))

        weights_used = {
            name: weight / weight_total
            for name, (weight, _) in contributing.items()
        }
        contributions = {
            name: weights_used[name] * signal_score
            for name, (_, signal_score) in contributing.items()
        }

        normalised = weight_total < self._configured_weight_total
        reasons: list[str] = [REASON_SCORE_COMPUTED]
        if normalised:
            reasons.append(REASON_SCORE_RENORMALISED)
        if zero_weight_available:
            reasons.append(REASON_ZERO_WEIGHT_SIGNAL_IGNORED)
        if any(name not in _CORE_SIGNAL_NAMES for name, _ in ordered):
            reasons.append(REASON_UNWEIGHTED_SIGNAL_PRESENT)

        contradictions = _conflict_codes(ordered)
        if contradictions:
            reasons.append(REASON_CONFLICT_PRESENT)

        return ScoringResult(
            score=combined,
            signals=_signal_view(ordered),
            available_scores=MappingProxyType(dict(available_scores)),
            configured_weights=self._weights,
            weights_used=MappingProxyType(dict(weights_used)),
            contributions=MappingProxyType(dict(contributions)),
            weighted_sum=weighted_sum,
            weight_total=weight_total,
            configured_weight_total=self._configured_weight_total,
            normalised=normalised,
            contradictions=contradictions,
            reasons=tuple(reasons),
        )

    # ------------------------------------------------------------------ #
    # Input handling
    # ------------------------------------------------------------------ #
    @staticmethod
    def _collect_signals(
        signals: Mapping[str, SignalResult] | None,
        *,
        text: SignalResult | None,
        location: SignalResult | None,
        category: SignalResult | None,
        time: SignalResult | None,
        extra_signals: Mapping[str, SignalResult] | None,
    ) -> dict[str, SignalResult]:
        kwargs = {
            "text": text,
            "location": location,
            "category": category,
            "time": time,
        }

        if signals is not None:
            if any(value is not None for value in kwargs.values()):
                raise TypeError(
                    "pass either a signals mapping or the four keyword signals, "
                    "not both"
                )
            provided = dict(_as_mapping(signals, "signals"))
            missing = [name for name in _CORE_SIGNAL_NAMES if name not in provided]
            if missing:
                raise ValueError(f"missing core signal(s): {', '.join(missing)}")
        else:
            missing = [name for name, value in kwargs.items() if value is None]
            if missing:
                raise ValueError(f"missing core signal(s): {', '.join(missing)}")
            provided = {name: value for name, value in kwargs.items() if value is not None}

        if extra_signals is not None:
            extras = _as_mapping(extra_signals, "extra_signals")
            duplicate = [name for name in extras if name in provided]
            if duplicate:
                raise ValueError(
                    "extra_signals must not redefine signal(s): "
                    + ", ".join(sorted(duplicate))
                )
            provided.update(extras)

        for name in provided:
            if not isinstance(name, str) or not name:
                raise ScoringError("signal names must be non-empty strings")
        return provided

    def _unscorable_result(
        self,
        ordered: list[tuple[str, SignalResult]],
        available_scores: Mapping[str, float],
        *,
        zero_weight_available: list[str],
    ) -> ScoringResult:
        reasons: list[str] = [REASON_SCORE_UNAVAILABLE]
        if available_scores:
            reasons.append(REASON_NO_POSITIVE_WEIGHT_SIGNAL)
        else:
            reasons.append(REASON_NO_AVAILABLE_SIGNAL)
        if zero_weight_available:
            reasons.append(REASON_ZERO_WEIGHT_SIGNAL_IGNORED)
        if any(name not in _CORE_SIGNAL_NAMES for name, _ in ordered):
            reasons.append(REASON_UNWEIGHTED_SIGNAL_PRESENT)

        contradictions = _conflict_codes(ordered)
        if contradictions:
            reasons.append(REASON_CONFLICT_PRESENT)

        return ScoringResult(
            score=None,
            signals=_signal_view(ordered),
            available_scores=MappingProxyType(dict(available_scores)),
            configured_weights=self._weights,
            weights_used=MappingProxyType({}),
            contributions=MappingProxyType({}),
            weighted_sum=0.0,
            weight_total=0.0,
            configured_weight_total=self._configured_weight_total,
            normalised=False,
            contradictions=contradictions,
            reasons=tuple(reasons),
        )


# --------------------------------------------------------------------------- #
# Validation helpers (defensive: model_construct must not bypass invariants)
# --------------------------------------------------------------------------- #
def _validate_weights(weights: MatchingWeights) -> dict[str, float]:
    values: dict[str, float] = {}
    for name in _CORE_SIGNAL_NAMES:
        try:
            value = getattr(weights, name)
        except AttributeError as exc:  # model_construct with missing fields
            raise ScoringError(f"missing {name} weight") from exc
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ScoringError(f"{name} weight must be a number")
        numeric = float(value)
        if not math.isfinite(numeric):
            raise ScoringError(f"{name} weight must be finite")
        if numeric < 0.0:
            raise ScoringError(f"{name} weight must be non-negative")
        values[name] = numeric

    if math.fsum(values.values()) <= 0.0:
        raise ScoringError(
            "the sum of the weights must be positive; at least one weight "
            "must be greater than zero"
        )
    return values


def _validate_signal(name: str, signal: SignalResult) -> tuple[SignalStatus, float | None]:
    """Validate one signal defensively and return its status and score."""
    if not isinstance(signal, SignalResult):
        raise ScoringError(f"{name} signal must be a SignalResult")
    try:
        status = SignalStatus(signal.status)
    except (TypeError, ValueError) as exc:
        raise ScoringError(f"{name} signal has an unknown status: {signal.status!r}") from exc

    raw_score = signal.score
    if status is SignalStatus.AVAILABLE:
        if isinstance(raw_score, bool) or not isinstance(raw_score, (int, float)):
            raise ScoringError(f"{name} signal score must be a number when AVAILABLE")
        score = float(raw_score)
        if not math.isfinite(score):
            raise ScoringError(f"{name} signal score must be finite")
        if not (0.0 <= score <= 1.0):
            raise ScoringError(f"{name} signal score must be within [0, 1]")
        return status, score

    if raw_score is not None:
        raise ScoringError(
            f"{name} signal must have a null score when status is {status.value}"
        )
    return status, None


def _signal_view(
    ordered: list[tuple[str, SignalResult]],
) -> Mapping[str, SignalResult]:
    return MappingProxyType(dict(ordered))


def _conflict_codes(ordered: list[tuple[str, SignalResult]]) -> tuple[str, ...]:
    """Collect comparator conflict codes deterministically, preserving metadata."""
    codes: list[str] = []
    for _name, signal in ordered:
        details: Any = signal.details
        if not isinstance(details, Mapping) or details.get("conflict") is not True:
            continue
        code = details.get("conflict_code")
        if isinstance(code, str) and code and code not in codes:
            codes.append(code)
    return tuple(codes)


__all__ = [
    "REASON_CONFLICT_PRESENT",
    "REASON_NO_AVAILABLE_SIGNAL",
    "REASON_NO_POSITIVE_WEIGHT_SIGNAL",
    "REASON_SCORE_COMPUTED",
    "REASON_SCORE_RENORMALISED",
    "REASON_SCORE_UNAVAILABLE",
    "REASON_UNWEIGHTED_SIGNAL_PRESENT",
    "REASON_ZERO_WEIGHT_SIGNAL_IGNORED",
    "ScoringError",
    "ScoringResult",
    "WeightedScoringEngine",
]
