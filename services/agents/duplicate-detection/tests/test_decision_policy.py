"""Unit tests for the Phase 4 (M4) duplicate-decision policy.

The policy is tested in isolation. Candidate evidence is constructed directly,
independently of any scoring engine, comparator, repository or HTTP layer.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.config.settings import (
    DEFAULT_SETTINGS,
    DecisionPolicySettings,
    DecisionThresholds,
    Settings,
)
from app.schemas.duplicate_response import Decision, SignalResult, SignalStatus
from app.scoring import CandidateScore, DecisionPolicy, RetrievalStatus
from app.scoring.decision_policy import (
    REASON_AMBIGUOUS_TIED,
    REASON_CONTRADICTION_CATEGORY,
    REASON_CONTRADICTION_LOCATION,
    REASON_INSUFFICIENT_EVIDENCE,
    REASON_INVALID_SCORE,
    REASON_MISSING_CORE_ANCHOR,
    REASON_NO_ELIGIBLE_CANDIDATES,
    REASON_RETRIEVAL_FAILED,
    REASON_RETRIEVAL_INCOMPLETE,
    REASON_SCORE_ABOVE_HIGH,
    REASON_SCORE_BELOW_LOW,
    REASON_SCORE_BETWEEN_THRESHOLDS,
)

POLICY = DecisionPolicy()


# --------------------------------------------------------------------------- #
# Builders
# --------------------------------------------------------------------------- #
def available(score, reason=None, details=None):
    return SignalResult(
        status=SignalStatus.AVAILABLE, score=score, reason=reason, details=details
    )


def unavailable(reason=None):
    return SignalResult(status=SignalStatus.UNAVAILABLE, score=None, reason=reason)


def strong_signals(*, text=0.92, location=0.95, category=1.0, time=0.80):
    """Four supportive signals: a well-evidenced candidate."""
    return {
        "text": available(text, "TEXT_SIMILARITY"),
        "location": available(
            location, "LOCATION_IDENTIFIER_MATCH", {"basis": "identifier"}
        ),
        "category": available(category, "CATEGORY_EXACT_MATCH", {"relation": "exact"}),
        "time": available(time, "TIME_DECAY"),
    }


def low_signals():
    """Four AVAILABLE signals that still clear the evidence gates but are weak.

    ``location`` and ``category`` are supportive, so the minimum-evidence,
    core-anchor and corroboration gates all pass; the combined score is low.
    """
    return {
        "text": available(0.10, "TEXT_SIMILARITY_LOW"),
        "location": available(0.55, "LOCATION_PROXIMITY", {"basis": "coordinates"}),
        "category": available(0.60, "CATEGORY_COMPATIBLE", {"relation": "compatible"}),
        "time": available(0.10, "TIME_DECAY"),
    }


def candidate(incident_id, score, signals=None, contradictions=(), reasons=()):
    return CandidateScore(
        incident_id=incident_id,
        score=score,
        signals=dict(signals) if signals is not None else strong_signals(),
        contradictions=tuple(contradictions),
        reasons=tuple(reasons),
    )


# --------------------------------------------------------------------------- #
# Threshold bands
# --------------------------------------------------------------------------- #
def test_high_score_with_sufficient_evidence_is_duplicate():
    outcome = POLICY.decide([candidate("CMP-1", 0.90)])
    assert outcome.decision is Decision.DUPLICATE
    assert outcome.matched_incident_id == "CMP-1"
    assert outcome.score == pytest.approx(0.90)
    assert REASON_SCORE_ABOVE_HIGH in outcome.reasons
    assert outcome.leading_candidate_id == "CMP-1"


def test_intermediate_score_is_review_required():
    outcome = POLICY.decide([candidate("CMP-1", 0.70)])
    assert outcome.decision is Decision.REVIEW_REQUIRED
    assert outcome.matched_incident_id is None
    assert outcome.score == pytest.approx(0.70)
    assert REASON_SCORE_BETWEEN_THRESHOLDS in outcome.reasons


def test_low_scores_with_complete_retrieval_are_new():
    weaker = dict(low_signals())
    weaker["location"] = available(0.05, "LOCATION_PROXIMITY", {"basis": "coordinates"})
    weaker["category"] = available(0.05, "CATEGORY_COMPATIBLE", {"relation": "compatible"})
    outcome = POLICY.decide(
        [
            candidate("CMP-LOW-A", 0.24, low_signals()),
            candidate("CMP-LOW-B", 0.10, weaker),
        ]
    )
    assert outcome.decision is Decision.NEW
    assert outcome.decision is not Decision.DUPLICATE
    assert outcome.matched_incident_id is None
    assert outcome.score is None
    assert REASON_SCORE_BELOW_LOW in outcome.reasons
    assert outcome.leading_candidate_id == "CMP-LOW-A"


def test_single_low_candidate_is_new():
    outcome = POLICY.decide([candidate("CMP-1", 0.20, low_signals())])
    assert outcome.decision is Decision.NEW
    assert REASON_SCORE_BELOW_LOW in outcome.reasons


def test_thresholds_are_configurable():
    strict = DecisionPolicy(Settings(thresholds=DecisionThresholds(high=0.99, low=0.10)))
    outcome = strict.decide([candidate("CMP-1", 0.90)])
    assert outcome.decision is Decision.REVIEW_REQUIRED
    assert REASON_SCORE_BETWEEN_THRESHOLDS in outcome.reasons


# --------------------------------------------------------------------------- #
# Candidate-set size and retrieval completeness
# --------------------------------------------------------------------------- #
def test_no_candidates_with_complete_retrieval_is_new():
    outcome = POLICY.decide([])
    assert outcome.decision is Decision.NEW
    assert outcome.matched_incident_id is None
    assert outcome.score is None
    assert outcome.reasons == (REASON_NO_ELIGIBLE_CANDIDATES,)
    assert outcome.candidates == ()


@pytest.mark.parametrize(
    "status, reason",
    [
        (RetrievalStatus.INCOMPLETE, REASON_RETRIEVAL_INCOMPLETE),
        (RetrievalStatus.FAILED, REASON_RETRIEVAL_FAILED),
    ],
)
def test_retrieval_not_complete_is_never_new(status, reason):
    outcome = POLICY.decide([], retrieval_status=status)
    assert outcome.decision is Decision.REVIEW_REQUIRED
    assert outcome.decision is not Decision.NEW
    assert reason in outcome.reasons


def test_unknown_retrieval_status_is_rejected():
    with pytest.raises(ValueError):
        POLICY.decide([], retrieval_status="MAYBE")


def test_incomplete_retrieval_with_low_candidate_is_not_new():
    outcome = POLICY.decide(
        [candidate("CMP-1", 0.30, low_signals())],
        retrieval_status=RetrievalStatus.INCOMPLETE,
    )
    assert outcome.decision is Decision.REVIEW_REQUIRED
    assert outcome.decision is not Decision.NEW
    assert REASON_RETRIEVAL_INCOMPLETE in outcome.reasons
    assert REASON_SCORE_BELOW_LOW in outcome.reasons


# --------------------------------------------------------------------------- #
# Evidence sufficiency
# --------------------------------------------------------------------------- #
def test_single_available_signal_is_insufficient_evidence():
    signals = {
        "text": available(0.95, "TEXT_SIMILARITY"),
        "location": unavailable("LOCATION_UNAVAILABLE"),
        "category": unavailable("CATEGORY_UNAVAILABLE"),
        "time": unavailable("TIME_UNAVAILABLE"),
    }
    outcome = POLICY.decide([candidate("CMP-1", 0.95, signals)])
    assert outcome.decision is Decision.REVIEW_REQUIRED
    assert outcome.decision is not Decision.DUPLICATE
    assert REASON_INSUFFICIENT_EVIDENCE in outcome.reasons


def test_two_signals_without_core_anchor_is_reviewed():
    signals = {
        "text": unavailable("TEXT_UNAVAILABLE"),
        "location": unavailable("LOCATION_UNAVAILABLE"),
        "category": available(1.0, "CATEGORY_EXACT_MATCH", {"relation": "exact"}),
        "time": available(0.90, "TIME_DECAY"),
    }
    outcome = POLICY.decide([candidate("CMP-1", 0.90, signals)])
    assert outcome.decision is Decision.REVIEW_REQUIRED
    assert REASON_MISSING_CORE_ANCHOR in outcome.reasons


def test_single_supportive_signal_fails_corroboration():
    # Two available signals (min count ok) and a core anchor, but only one is
    # supportive, so corroboration fails.
    signals = {
        "text": available(0.60, "TEXT_SIMILARITY"),
        "location": available(0.30, "LOCATION_PROXIMITY", {"basis": "coordinates"}),
        "category": unavailable("CATEGORY_UNAVAILABLE"),
        "time": unavailable("TIME_UNAVAILABLE"),
    }
    outcome = POLICY.decide([candidate("CMP-1", 0.80, signals)])
    assert outcome.decision is Decision.REVIEW_REQUIRED
    assert REASON_INSUFFICIENT_EVIDENCE in outcome.reasons


def test_custom_min_available_signals_is_enforced():
    settings = Settings(decision=DecisionPolicySettings(min_available_signals=3))
    policy = DecisionPolicy(settings)
    signals = {
        "text": available(0.95, "TEXT_SIMILARITY"),
        "location": available(0.95, "LOCATION_IDENTIFIER_MATCH", {"basis": "identifier"}),
        "category": unavailable("CATEGORY_UNAVAILABLE"),
        "time": unavailable("TIME_UNAVAILABLE"),
    }
    outcome = policy.decide([candidate("CMP-1", 0.95, signals)])
    assert outcome.decision is Decision.REVIEW_REQUIRED
    assert REASON_INSUFFICIENT_EVIDENCE in outcome.reasons


# --------------------------------------------------------------------------- #
# Contradictions
# --------------------------------------------------------------------------- #
def test_location_identifier_conflict_is_reviewed_not_duplicate():
    signals = {
        "text": available(0.95, "TEXT_SIMILARITY"),
        "location": available(
            0.0,
            "LOCATION_IDENTIFIER_CONFLICT",
            {"conflict": True, "conflict_code": "LOCATION_IDENTIFIER_CONFLICT"},
        ),
        "category": available(1.0, "CATEGORY_EXACT_MATCH", {"relation": "exact"}),
        "time": available(0.80, "TIME_DECAY"),
    }
    outcome = POLICY.decide([candidate("CMP-1", 0.72, signals)])
    assert outcome.decision is Decision.REVIEW_REQUIRED
    assert outcome.decision is not Decision.DUPLICATE
    assert REASON_CONTRADICTION_LOCATION in outcome.reasons
    assert "LOCATION_IDENTIFIER_CONFLICT" in outcome.candidates[0].contradictions


def test_c1_text_similar_but_location_far_is_reviewed():
    signals = {
        "text": available(0.95, "TEXT_SIMILARITY"),
        "location": available(0.05, "LOCATION_PROXIMITY", {"basis": "coordinates"}),
        "category": available(1.0, "CATEGORY_EXACT_MATCH", {"relation": "exact"}),
        "time": available(0.80, "TIME_DECAY"),
    }
    outcome = POLICY.decide([candidate("CMP-1", 0.75, signals)])
    assert outcome.decision is Decision.REVIEW_REQUIRED
    assert REASON_CONTRADICTION_LOCATION in outcome.reasons


def test_category_conflict_is_reviewed_not_duplicate():
    signals = {
        "text": available(0.95, "TEXT_SIMILARITY"),
        "location": unavailable("LOCATION_UNAVAILABLE"),
        "category": available(
            0.0,
            "CATEGORY_INCOMPATIBLE",
            {"relation": "incompatible", "conflict": True, "conflict_code": "CATEGORY_INCOMPATIBLE"},
        ),
        "time": unavailable("TIME_UNAVAILABLE"),
    }
    outcome = POLICY.decide([candidate("CMP-1", 0.76, signals)])
    assert outcome.decision is Decision.REVIEW_REQUIRED
    assert outcome.decision is not Decision.DUPLICATE
    assert REASON_CONTRADICTION_CATEGORY in outcome.reasons


@pytest.mark.parametrize(
    "code, expected_reason",
    [
        ("LOCATION_IDENTIFIER_CONFLICT", REASON_CONTRADICTION_LOCATION),
        ("LOCATION_FACILITY_CONFLICT", REASON_CONTRADICTION_LOCATION),
        ("CATEGORY_INCOMPATIBLE", REASON_CONTRADICTION_CATEGORY),
        (REASON_CONTRADICTION_LOCATION, REASON_CONTRADICTION_LOCATION),
        (REASON_CONTRADICTION_CATEGORY, REASON_CONTRADICTION_CATEGORY),
    ],
)
def test_explicit_contradiction_blocks_duplicate(code, expected_reason):
    # The M3 -> M4 contract allows conflict codes to be attached directly.
    # They must be honoured even when the signal details are not repeated.
    outcome = POLICY.decide([candidate("CMP-1", 0.95, contradictions=(code,))])
    assert outcome.decision is Decision.REVIEW_REQUIRED
    assert outcome.decision is not Decision.DUPLICATE
    assert outcome.matched_incident_id is None
    assert expected_reason in outcome.reasons
    assert code in outcome.candidates[0].contradictions


def test_unrecognised_explicit_contradiction_is_still_disqualifying():
    # The reason-code set is additive. An upstream code the policy does not
    # know must not be silently dropped: block DUPLICATE and surface it.
    outcome = POLICY.decide(
        [candidate("CMP-1", 0.95, contradictions=("UPSTREAM_CONFLICT",))]
    )
    assert outcome.decision is Decision.REVIEW_REQUIRED
    assert outcome.decision is not Decision.DUPLICATE
    assert "UPSTREAM_CONFLICT" in outcome.reasons
    assert "UPSTREAM_CONFLICT" in outcome.candidates[0].contradictions


def test_absent_identifiers_are_not_a_false_conflict():
    # A coordinate-only location match: neither side carries identifiers, so
    # there is no conflict and a strong candidate is still a duplicate.
    signals = {
        "text": available(0.90, "TEXT_SIMILARITY"),
        "location": available(
            0.97,
            "LOCATION_PROXIMITY",
            {
                "basis": "coordinates",
                "distance_m": 5.0,
                "facility_a": None,
                "location_a": None,
                "facility_b": None,
                "location_b": None,
            },
        ),
        "category": available(1.0, "CATEGORY_EXACT_MATCH", {"relation": "exact"}),
        "time": available(0.85, "TIME_DECAY"),
    }
    outcome = POLICY.decide([candidate("CMP-1", 0.92, signals)])
    assert outcome.decision is Decision.DUPLICATE
    assert REASON_CONTRADICTION_LOCATION not in outcome.reasons
    assert outcome.candidates[0].contradictions == ()


# --------------------------------------------------------------------------- #
# Ambiguity / ties
# --------------------------------------------------------------------------- #
def test_near_equal_top_candidates_are_ambiguous():
    outcome = POLICY.decide([candidate("CMP-A", 0.90), candidate("CMP-B", 0.88)])
    assert outcome.decision is Decision.REVIEW_REQUIRED
    assert REASON_AMBIGUOUS_TIED in outcome.reasons
    assert {c.incident_id for c in outcome.candidates} == {"CMP-A", "CMP-B"}
    assert outcome.leading_candidate_id == "CMP-A"


def test_equal_scores_are_ranked_deterministically():
    inputs = [candidate("CMP-B", 0.80), candidate("CMP-A", 0.80)]
    first = POLICY.decide(inputs)
    second = POLICY.decide(inputs)
    assert first.decision is Decision.REVIEW_REQUIRED
    assert REASON_AMBIGUOUS_TIED in first.reasons
    assert [c.incident_id for c in first.candidates] == ["CMP-A", "CMP-B"]
    assert [c.incident_id for c in second.candidates] == ["CMP-A", "CMP-B"]


def test_two_low_tied_candidates_are_reviewed_not_new():
    # Documented conservative reading of the section 6.4 gate order: ambiguity
    # is checked before the threshold bands.
    outcome = POLICY.decide(
        [
            candidate("CMP-A", 0.30, low_signals()),
            candidate("CMP-B", 0.29, low_signals()),
        ]
    )
    assert outcome.decision is Decision.REVIEW_REQUIRED
    assert REASON_AMBIGUOUS_TIED in outcome.reasons


def test_ambiguity_margin_is_configurable():
    wide = DecisionPolicy(Settings(tie_margin=0.30))
    outcome = wide.decide([candidate("CMP-A", 0.90), candidate("CMP-B", 0.70)])
    assert outcome.decision is Decision.REVIEW_REQUIRED
    assert REASON_AMBIGUOUS_TIED in outcome.reasons


def test_one_clearly_better_candidate_is_duplicate():
    outcome = POLICY.decide(
        [
            candidate("CMP-NEAR", 0.95),
            candidate("CMP-MID", 0.62, low_signals()),
            candidate("CMP-FAR", 0.40, low_signals()),
        ]
    )
    assert outcome.decision is Decision.DUPLICATE
    assert outcome.matched_incident_id == "CMP-NEAR"
    assert [c.incident_id for c in outcome.candidates] == [
        "CMP-NEAR",
        "CMP-MID",
        "CMP-FAR",
    ]


# --------------------------------------------------------------------------- #
# Invalid scores and malformed evidence
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "bad_score",
    [float("nan"), float("inf"), float("-inf"), -0.1, 1.5, 2.0],
)
def test_invalid_numeric_score_never_produces_duplicate(bad_score):
    outcome = POLICY.decide([candidate("CMP-1", bad_score)])
    assert outcome.decision is Decision.REVIEW_REQUIRED
    assert outcome.decision is not Decision.DUPLICATE
    assert REASON_INVALID_SCORE in outcome.reasons


def test_missing_score_for_scoreable_candidate_is_invalid():
    # The signals contain AVAILABLE evidence, so a score was owed.
    outcome = POLICY.decide([candidate("CMP-1", None)])
    assert outcome.decision is Decision.REVIEW_REQUIRED
    assert REASON_INVALID_SCORE in outcome.reasons


def test_missing_score_without_available_signals_is_reviewed():
    signals = {
        "text": unavailable("TEXT_UNAVAILABLE"),
        "location": unavailable("LOCATION_UNAVAILABLE"),
        "category": unavailable("CATEGORY_UNAVAILABLE"),
        "time": unavailable("TIME_UNAVAILABLE"),
    }
    outcome = POLICY.decide([candidate("CMP-1", None, signals)])
    assert outcome.decision is Decision.REVIEW_REQUIRED
    assert outcome.decision is not Decision.DUPLICATE
    assert outcome.matched_incident_id is None
    assert REASON_INSUFFICIENT_EVIDENCE in outcome.reasons


def test_available_signal_without_score_marks_candidate_invalid():
    broken = SignalResult.model_construct(
        status=SignalStatus.AVAILABLE, score=None, reason="X", details=None
    )
    signals = {"text": broken, "location": available(0.9, "LOCATION_PROXIMITY")}
    outcome = POLICY.decide([candidate("CMP-1", 0.95, signals)])
    assert outcome.decision is Decision.REVIEW_REQUIRED
    assert REASON_INVALID_SCORE in outcome.reasons


def test_non_signal_evidence_marks_candidate_invalid():
    signals = {"text": {"status": "AVAILABLE", "score": 0.9}}  # not a SignalResult
    outcome = POLICY.decide([CandidateScore("CMP-1", 0.95, signals)])
    assert outcome.decision is Decision.REVIEW_REQUIRED
    assert REASON_INVALID_SCORE in outcome.reasons


def test_missing_incident_id_marks_candidate_invalid():
    outcome = POLICY.decide([CandidateScore("   ", 0.95, strong_signals())])
    assert outcome.decision is Decision.REVIEW_REQUIRED
    assert REASON_INVALID_SCORE in outcome.reasons


# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #
def test_default_settings_expose_decision_policy():
    assert isinstance(DEFAULT_SETTINGS.decision, DecisionPolicySettings)
    assert DEFAULT_SETTINGS.decision.min_available_signals == 2
    assert DEFAULT_SETTINGS.decision.require_core_anchor is True
    assert DEFAULT_SETTINGS.decision.require_corroboration is True


@pytest.mark.parametrize(
    "kwargs",
    [
        {"min_available_signals": 0},
        {"min_available_signals": 5},
        {"core_anchor_floor": -0.1},
        {"core_anchor_floor": 1.5},
        {"supportive_floor": float("nan")},
        {"location_conflict_text_floor": 0.2, "location_conflict_location_ceiling": 0.8},
    ],
)
def test_invalid_decision_config_is_rejected(kwargs):
    with pytest.raises(ValidationError):
        DecisionPolicySettings(**kwargs)


def _settings_without_validation(**overrides):
    base = dict(
        weights=DEFAULT_SETTINGS.weights,
        thresholds=DEFAULT_SETTINGS.thresholds,
        comparators=DEFAULT_SETTINGS.comparators,
        decision=DEFAULT_SETTINGS.decision,
        tie_margin=DEFAULT_SETTINGS.tie_margin,
        policy_version=DEFAULT_SETTINGS.policy_version,
    )
    base.update(overrides)
    return Settings.model_construct(**base)


def test_policy_rejects_misordered_thresholds_without_validation():
    bad = _settings_without_validation(
        thresholds=DecisionThresholds.model_construct(high=0.4, low=0.9)
    )
    with pytest.raises(ValueError):
        DecisionPolicy(bad)


def test_policy_rejects_negative_tie_margin_without_validation():
    bad = _settings_without_validation(tie_margin=-0.1)
    with pytest.raises(ValueError):
        DecisionPolicy(bad)


# --------------------------------------------------------------------------- #
# Outcome contract
# --------------------------------------------------------------------------- #
def test_outcome_adapts_to_v1_response():
    outcome = POLICY.decide([candidate("CMP-1", 0.90)])
    response = outcome.to_response("CMP-NEW-1")
    assert response.complaint_id == "CMP-NEW-1"
    assert response.decision is Decision.DUPLICATE
    assert response.matched_incident_id == "CMP-1"
    assert response.score == pytest.approx(0.90)
    assert response.signals
    assert REASON_SCORE_ABOVE_HIGH in response.reasons


def test_review_outcome_adapts_without_asserting_a_match():
    outcome = POLICY.decide([candidate("CMP-1", 0.70)])
    response = outcome.to_response("CMP-NEW-1")
    assert response.decision is Decision.REVIEW_REQUIRED
    assert response.matched_incident_id is None
    assert outcome.leading_candidate_id == "CMP-1"


def test_outcome_carries_policy_version():
    outcome = POLICY.decide([candidate("CMP-1", 0.90)])
    assert outcome.policy_version == DEFAULT_SETTINGS.policy_version


def test_policy_does_not_mutate_inputs():
    signals = strong_signals()
    before = {name: (sig.status, sig.score, sig.reason) for name, sig in signals.items()}
    cand = candidate("CMP-1", 0.90, signals)
    POLICY.decide([cand])
    after = {name: (sig.status, sig.score, sig.reason) for name, sig in signals.items()}
    assert before == after
    assert cand.score == 0.90
    assert cand.incident_id == "CMP-1"


def test_decide_is_deterministic():
    inputs = [candidate("CMP-B", 0.90), candidate("CMP-A", 0.90)]
    assert POLICY.decide(inputs) == POLICY.decide(inputs)
