"""Unit tests for the Phase 4 (M3) weighted scoring engine.

The engine is tested in isolation from retrieval, comparators and HTTP. It
reuses the real ``SignalResult`` and ``MatchingWeights`` contracts, and the
M3 -> M4 compatibility tests use the real ``CandidateScore`` / ``DecisionPolicy``.
"""

from __future__ import annotations

import math
from dataclasses import FrozenInstanceError
from typing import Any

import pytest

from app.config.settings import MatchingWeights
from app.schemas.duplicate_response import Decision, SignalResult, SignalStatus
from app.scoring import (
    REASON_CONFLICT_PRESENT,
    REASON_NO_AVAILABLE_SIGNAL,
    REASON_NO_POSITIVE_WEIGHT_SIGNAL,
    REASON_SCORE_COMPUTED,
    REASON_SCORE_RENORMALISED,
    REASON_SCORE_UNAVAILABLE,
    REASON_UNWEIGHTED_SIGNAL_PRESENT,
    REASON_ZERO_WEIGHT_SIGNAL_IGNORED,
    CandidateScore,
    DecisionPolicy,
    ScoringError,
    ScoringResult,
    WeightedScoringEngine,
)
from app.scoring.decision_policy import (
    REASON_CONTRADICTION_LOCATION,
    REASON_INSUFFICIENT_EVIDENCE,
    REASON_INVALID_SCORE,
    REASON_SCORE_ABOVE_HIGH,
)

ENGINE = WeightedScoringEngine()


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def available(
    score: float,
    *,
    reason: str | None = None,
    details: dict[str, Any] | None = None,
) -> SignalResult:
    return SignalResult(
        status=SignalStatus.AVAILABLE,
        score=score,
        reason=reason,
        details=details,
    )


def missing(status: SignalStatus = SignalStatus.UNAVAILABLE) -> SignalResult:
    return SignalResult(status=status)


def core_signals(
    *,
    text: SignalResult | None = None,
    location: SignalResult | None = None,
    category: SignalResult | None = None,
    time: SignalResult | None = None,
) -> dict[str, SignalResult]:
    return {
        "text": text if text is not None else missing(),
        "location": location if location is not None else missing(),
        "category": category if category is not None else missing(),
        "time": time if time is not None else missing(),
    }


# --------------------------------------------------------------------------- #
# Formula and normalisation
# --------------------------------------------------------------------------- #
def test_all_available_uses_configured_weights() -> None:
    result = ENGINE.score(
        core_signals(
            text=available(0.5),
            location=available(0.6),
            category=available(0.7),
            time=available(0.8),
        )
    )

    assert result.score == pytest.approx(0.605)
    assert result.weighted_sum == pytest.approx(0.605)
    assert result.weight_total == pytest.approx(1.0)
    assert result.configured_weight_total == pytest.approx(1.0)
    assert result.normalised is False
    assert dict(result.configured_weights) == {
        "text": 0.40,
        "location": 0.30,
        "category": 0.15,
        "time": 0.15,
    }
    assert dict(result.weights_used) == pytest.approx(
        {"text": 0.40, "location": 0.30, "category": 0.15, "time": 0.15}
    )
    assert dict(result.available_scores) == pytest.approx(
        {"text": 0.5, "location": 0.6, "category": 0.7, "time": 0.8}
    )
    assert math.fsum(result.contributions.values()) == pytest.approx(result.score)
    assert result.reasons == (REASON_SCORE_COMPUTED,)


def test_partial_availability_renormalises_by_available_weights() -> None:
    result = ENGINE.score(
        core_signals(
            text=available(0.8),
            location=missing(),
            category=available(1.0),
            time=missing(),
        )
    )

    # (0.40 * 0.8 + 0.15 * 1.0) / (0.40 + 0.15) = 0.47 / 0.55
    assert result.score == pytest.approx(0.47 / 0.55)
    assert result.weighted_sum == pytest.approx(0.47)
    assert result.weight_total == pytest.approx(0.55)
    assert result.normalised is True
    assert dict(result.weights_used) == pytest.approx(
        {"text": 0.40 / 0.55, "category": 0.15 / 0.55}
    )
    assert math.fsum(result.weights_used.values()) == pytest.approx(1.0)
    assert math.fsum(result.contributions.values()) == pytest.approx(result.score)
    assert result.reasons == (
        REASON_SCORE_COMPUTED,
        REASON_SCORE_RENORMALISED,
    )


def test_unavailable_invalid_and_error_are_not_scored_as_zero() -> None:
    text_only = ENGINE.score(
        core_signals(
            text=available(0.8),
            location=missing(SignalStatus.UNAVAILABLE),
            category=missing(SignalStatus.INVALID),
            time=missing(SignalStatus.ERROR),
        )
    )

    # If missing/invalid/error signals were coerced to 0, the denominator would
    # be 1.0 and the score would be 0.32. They must be excluded entirely.
    assert text_only.score == pytest.approx(0.8)
    assert text_only.weight_total == pytest.approx(0.4)
    assert text_only.normalised is True
    assert dict(text_only.available_scores) == pytest.approx({"text": 0.8})


@pytest.mark.parametrize(
    "status",
    [SignalStatus.UNAVAILABLE, SignalStatus.INVALID, SignalStatus.ERROR],
)
def test_all_non_available_returns_none(status: SignalStatus) -> None:
    result = ENGINE.score(
        core_signals(
            text=missing(status),
            location=missing(status),
            category=missing(status),
            time=missing(status),
        )
    )

    assert result.score is None
    assert result.weighted_sum == 0.0
    assert result.weight_total == 0.0
    assert result.normalised is False
    assert dict(result.available_scores) == {}
    assert dict(result.weights_used) == {}
    assert dict(result.contributions) == {}
    assert result.reasons == (
        REASON_SCORE_UNAVAILABLE,
        REASON_NO_AVAILABLE_SIGNAL,
    )


# --------------------------------------------------------------------------- #
# Zero weights / no usable positive weight
# --------------------------------------------------------------------------- #
def test_zero_weight_signals_are_evidence_but_cannot_produce_a_score() -> None:
    engine = WeightedScoringEngine(
        MatchingWeights(text=0.5, location=0.0, category=0.0, time=0.0)
    )
    result = engine.score(
        core_signals(
            text=missing(),
            location=available(0.7),
            category=available(0.8),
            time=available(0.9),
        )
    )

    assert result.score is None
    assert dict(result.available_scores) == pytest.approx(
        {"location": 0.7, "category": 0.8, "time": 0.9}
    )
    assert dict(result.weights_used) == {}
    assert result.weight_total == 0.0
    assert result.reasons == (
        REASON_SCORE_UNAVAILABLE,
        REASON_NO_POSITIVE_WEIGHT_SIGNAL,
        REASON_ZERO_WEIGHT_SIGNAL_IGNORED,
    )


@pytest.mark.parametrize(
    "weights",
    [
        MatchingWeights.model_construct(
            text=0.0, location=0.0, category=0.0, time=0.0
        ),
        MatchingWeights.model_construct(
            text=float("nan"), location=0.3, category=0.15, time=0.15
        ),
        MatchingWeights.model_construct(
            text=float("inf"), location=0.3, category=0.15, time=0.15
        ),
        MatchingWeights.model_construct(
            text=-0.1, location=0.3, category=0.15, time=0.15
        ),
        MatchingWeights.model_construct(
            text=True, location=0.3, category=0.15, time=0.15
        ),
        MatchingWeights.model_construct(
            text="0.4", location=0.3, category=0.15, time=0.15
        ),
    ],
)
def test_invalid_weights_are_rejected_even_after_model_construct(
    weights: MatchingWeights,
) -> None:
    with pytest.raises(ScoringError):
        WeightedScoringEngine(weights)


# --------------------------------------------------------------------------- #
# Defensive signal validation
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "raw_score",
    [
        -0.01,
        1.01,
        float("nan"),
        float("inf"),
        float("-inf"),
        None,
        "0.5",
        True,
    ],
)
def test_invalid_available_scores_are_rejected(raw_score: object) -> None:
    signal = SignalResult.model_construct(
        status=SignalStatus.AVAILABLE,
        score=raw_score,
        reason=None,
        details=None,
    )

    with pytest.raises(ScoringError):
        ENGINE.score(core_signals(text=signal))


@pytest.mark.parametrize(
    "status",
    [SignalStatus.UNAVAILABLE, SignalStatus.INVALID, SignalStatus.ERROR],
)
def test_non_available_signal_must_not_carry_a_score(status: SignalStatus) -> None:
    signal = SignalResult.model_construct(
        status=status,
        score=0.5,
        reason=None,
        details=None,
    )

    with pytest.raises(ScoringError):
        ENGINE.score(core_signals(text=signal))


def test_unknown_signal_status_is_rejected() -> None:
    signal = SignalResult.model_construct(
        status="BOGUS",
        score=None,
        reason=None,
        details=None,
    )

    with pytest.raises(ScoringError):
        ENGINE.score(core_signals(text=signal))


def test_non_signal_result_is_rejected() -> None:
    signals: dict[str, Any] = core_signals()
    signals["text"] = object()

    with pytest.raises(ScoringError):
        ENGINE.score(signals)


# --------------------------------------------------------------------------- #
# Conflict metadata preservation
# --------------------------------------------------------------------------- #
def test_conflict_metadata_is_preserved_and_adapted_to_candidate_score() -> None:
    location_details = {
        "conflict": True,
        "conflict_code": "LOCATION_IDENTIFIER_CONFLICT",
        "distance_m": 1200.0,
    }
    category_details = {
        "conflict": True,
        "conflict_code": "CATEGORY_INCOMPATIBLE",
    }
    location = available(0.0, details=location_details)
    category = available(0.0, details=category_details)

    result = ENGINE.score(
        core_signals(
            text=available(0.9),
            location=location,
            category=category,
            time=missing(),
        )
    )

    assert result.signals["location"] is location
    assert result.signals["category"] is category
    assert result.signals["location"].details == location_details
    assert result.signals["location"].details["conflict"] is True
    assert result.signals["location"].details["conflict_code"] == (
        "LOCATION_IDENTIFIER_CONFLICT"
    )
    assert result.contradictions == (
        "LOCATION_IDENTIFIER_CONFLICT",
        "CATEGORY_INCOMPATIBLE",
    )
    assert REASON_CONFLICT_PRESENT in result.reasons

    candidate = result.to_candidate_score("CMP-CONFLICT")
    assert candidate.contradictions == result.contradictions
    assert candidate.signals["location"].details == location_details

    outcome = DecisionPolicy().decide([candidate])
    assert outcome.decision is Decision.REVIEW_REQUIRED
    assert REASON_CONTRADICTION_LOCATION in outcome.reasons


# --------------------------------------------------------------------------- #
# Determinism, immutability and the unweighted-evidence rule
# --------------------------------------------------------------------------- #
def test_deterministic_output_and_no_input_mutation() -> None:
    signals = core_signals(
        text=available(0.7, details={"tokens": ["streetlight"]}),
        location=available(0.4, details={"distance_m": 310.0}),
        category=available(0.6),
        time=available(0.2),
    )
    before = {name: signal.model_dump() for name, signal in signals.items()}

    first = ENGINE.score(signals)
    second = ENGINE.score(dict(reversed(list(signals.items()))))

    assert first == second
    assert list(first.signals) == ["text", "location", "category", "time"]
    assert {name: signal.model_dump() for name, signal in signals.items()} == before
    assert first.signals["text"] is signals["text"]


def test_scoring_result_is_frozen_and_mappings_are_read_only() -> None:
    result = ENGINE.score(core_signals(text=available(0.8)))

    assert isinstance(result, ScoringResult)
    with pytest.raises(FrozenInstanceError):
        result.score = 0.1  # type: ignore[misc]
    with pytest.raises(TypeError):
        result.signals["text"] = available(0.2)  # type: ignore[index]
    with pytest.raises(TypeError):
        result.weights_used["text"] = 0.5  # type: ignore[index]


def test_unweighted_extra_signal_is_retained_but_does_not_affect_score() -> None:
    image = available(0.1, reason="IMAGE_HASH_NEAR_IDENTICAL")
    result = ENGINE.score(
        core_signals(
            text=available(0.5),
            location=available(0.6),
            category=available(0.7),
            time=available(0.8),
        ),
        extra_signals={"image": image},
    )

    assert result.score == pytest.approx(0.605)
    assert list(result.signals) == ["text", "location", "category", "time", "image"]
    assert result.signals["image"] is image
    assert result.available_scores["image"] == pytest.approx(0.1)
    assert "image" not in result.configured_weights
    assert "image" not in result.weights_used
    assert "image" not in result.contributions
    assert REASON_UNWEIGHTED_SIGNAL_PRESENT in result.reasons

    candidate = result.to_candidate_score("CMP-IMAGE")
    assert candidate.signals["image"] is image


# --------------------------------------------------------------------------- #
# API shape and argument validation
# --------------------------------------------------------------------------- #
def test_mapping_and_keyword_apis_are_equivalent() -> None:
    text = available(0.5)
    location = available(0.6)
    category = available(0.7)
    time = available(0.8)

    from_mapping = ENGINE.score(
        {"text": text, "location": location, "category": category, "time": time}
    )
    from_keywords = ENGINE.score(
        text=text, location=location, category=category, time=time
    )

    assert from_mapping == from_keywords


def test_missing_core_signal_is_rejected() -> None:
    incomplete = core_signals(text=available(0.8))
    del incomplete["time"]

    with pytest.raises(ValueError):
        ENGINE.score(incomplete)
    with pytest.raises(ValueError):
        ENGINE.score(
            text=available(0.8),
            location=missing(),
            category=missing(),
        )


def test_mixing_mapping_and_keyword_forms_is_rejected() -> None:
    with pytest.raises(TypeError):
        ENGINE.score(
            core_signals(text=available(0.8)),
            text=available(0.8),
        )


def test_extra_signal_cannot_redefine_a_core_signal() -> None:
    with pytest.raises(ValueError):
        ENGINE.score(
            core_signals(text=available(0.8)),
            extra_signals={"text": available(0.9)},
        )


# --------------------------------------------------------------------------- #
# M3 -> M4 compatibility
# --------------------------------------------------------------------------- #
def test_candidate_score_and_decision_policy_accept_a_strong_score() -> None:
    result = ENGINE.score(
        core_signals(
            text=available(0.95),
            location=available(0.90),
            category=available(1.0),
            time=available(0.90),
        )
    )

    candidate = result.to_candidate_score("CMP-NEAR")
    assert isinstance(candidate, CandidateScore)
    assert candidate.incident_id == "CMP-NEAR"
    assert candidate.score == pytest.approx(result.score)
    assert dict(candidate.signals) == dict(result.signals)
    assert candidate.reasons == result.reasons

    outcome = DecisionPolicy().decide([candidate])
    assert outcome.decision is Decision.DUPLICATE
    assert outcome.matched_incident_id == "CMP-NEAR"
    assert outcome.score == pytest.approx(result.score)
    assert REASON_SCORE_ABOVE_HIGH in outcome.reasons


def test_unscorable_result_adapts_to_review_not_new() -> None:
    result = ENGINE.score(core_signals())
    assert result.score is None

    candidate = result.to_candidate_score("CMP-NO-EVIDENCE")
    outcome = DecisionPolicy().decide([candidate])

    assert outcome.decision is Decision.REVIEW_REQUIRED
    assert REASON_INSUFFICIENT_EVIDENCE in outcome.reasons
    assert REASON_INVALID_SCORE not in outcome.reasons
    assert outcome.matched_incident_id is None
