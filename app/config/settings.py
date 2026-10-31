"""Configurable policy values for the Duplicate Detection Agent.

These values are **provisional hypotheses** taken from the Phase 1
specification (``docs/duplicate_detection/matching_policy.md`` section 2 and
section 6.3). They have **not** been validated against labelled data and must be
tuned in a later phase against a labelled dataset.

This module only *stores and validates* configuration. It intentionally contains
no scoring or decision logic.
"""

from __future__ import annotations

import math
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

_CORE_SIGNAL_NAMES = ("text", "location", "category", "time")


class MatchingWeights(BaseModel):
    """Per-signal weights used to combine evidence.

    Weights must be finite and non-negative, and at least one must be positive
    (their sum must be greater than zero).
    """

    model_config = ConfigDict(extra="forbid")

    text: float = 0.40
    location: float = 0.30
    category: float = 0.15
    time: float = 0.15

    @field_validator(*_CORE_SIGNAL_NAMES)
    @classmethod
    def _finite_non_negative(cls, value: float, info) -> float:
        if not math.isfinite(value):
            raise ValueError(f"{info.field_name} weight must be a finite number")
        if value < 0:
            raise ValueError(f"{info.field_name} weight must be non-negative")
        return value

    @model_validator(mode="after")
    def _sum_must_be_positive(self) -> "MatchingWeights":
        if self.total() <= 0:
            raise ValueError(
                "the sum of the weights must be positive; at least one weight "
                "must be greater than zero"
            )
        return self

    def total(self) -> float:
        """Return the sum of all core weights."""
        return self.text + self.location + self.category + self.time


class DecisionThresholds(BaseModel):
    """Score thresholds that separate the decision outcomes.

    ``high`` and ``low`` are provisional. Results are only hypotheses until
    validated against labelled examples.
    """

    model_config = ConfigDict(extra="forbid")

    high: float = 0.85
    low: float = 0.55

    @field_validator("high", "low")
    @classmethod
    def _finite_unit_interval(cls, value: float, info) -> float:
        if not math.isfinite(value):
            raise ValueError(f"{info.field_name} threshold must be a finite number")
        if not (0.0 <= value <= 1.0):
            raise ValueError(f"{info.field_name} threshold must be between 0 and 1")
        return value

    @model_validator(mode="after")
    def _high_must_exceed_low(self) -> "DecisionThresholds":
        if self.high <= self.low:
            raise ValueError("high threshold must be greater than low threshold")
        return self


# --------------------------------------------------------------------------- #
# Comparator-specific configuration (Phase 3)
#
# These values are the only comparator-specific knobs. Final scoring weights and
# duplicate-decision thresholds deliberately stay in ``MatchingWeights`` /
# ``DecisionThresholds`` and are NOT used by individual comparators.
# --------------------------------------------------------------------------- #

#: Provisional, fictional civic-complaint category families used by the sample
#: compatibility map. Categories within the same group are treated as
#: "compatible". Replace with KAVACH's real vocabulary later.
_DEFAULT_COMPATIBLE_GROUPS: tuple[frozenset[str], ...] = (
    frozenset({"ROAD_DAMAGE", "POTHOLE", "ROAD_SURFACE"}),
    frozenset({"WASTE_MANAGEMENT", "GARBAGE_OVERFLOW", "LITTER"}),
    frozenset({"DRAINAGE", "SEWAGE", "WATERLOGGING"}),
    frozenset({"STREETLIGHT", "PUBLIC_LIGHTING"}),
)

#: Provisional explicit "mutually exclusive" pairs. Incompatibility takes
#: precedence over compatibility if a pair appears in both.
_DEFAULT_INCOMPATIBLE_PAIRS: tuple[frozenset[str], ...] = (
    frozenset({"WASTE_MANAGEMENT", "STREETLIGHT"}),
    frozenset({"ROAD_DAMAGE", "STREETLIGHT"}),
    frozenset({"DRAINAGE", "STREETLIGHT"}),
)


def _normalise_category_groups(
    value: object,
) -> tuple[frozenset[str], ...] | None:
    """Uppercase/trim categories inside each supplied group or pair."""
    if value is None:
        return None
    groups: list[frozenset[str]] = []
    for group in value:  # type: ignore[union-attr]
        groups.append(
            frozenset(str(item).strip().upper() for item in group if str(item).strip())
        )
    return tuple(g for g in groups if g)


class CategoryCompatibilityMap(BaseModel):
    """Provisional category compatibility mapping.

    * ``compatible_groups`` — categories in the same group are "compatible".
    * ``incompatible_pairs`` — explicitly mutually-exclusive category pairs.

    Both are data, not logic, so the real KAVACH taxonomy can replace the sample
    without touching the comparator. Incompatibility wins over compatibility.
    """

    model_config = ConfigDict(extra="forbid")

    compatible_groups: tuple[frozenset[str], ...] = Field(
        default_factory=lambda: _DEFAULT_COMPATIBLE_GROUPS
    )
    incompatible_pairs: tuple[frozenset[str], ...] = Field(
        default_factory=lambda: _DEFAULT_INCOMPATIBLE_PAIRS
    )

    @field_validator("compatible_groups", "incompatible_pairs", mode="before")
    @classmethod
    def _normalise(cls, value: object) -> object:
        return _normalise_category_groups(value)

    def are_incompatible(self, category_a: str, category_b: str) -> bool:
        """Return True if the two (normalised) categories are explicitly exclusive."""
        return frozenset({category_a, category_b}) in self.incompatible_pairs

    def are_compatible(self, category_a: str, category_b: str) -> bool:
        """Return True if the two (normalised) categories share a compatibility group."""
        if self.are_incompatible(category_a, category_b):
            return False
        return any(
            category_a in group and category_b in group
            for group in self.compatible_groups
        )


class ComparatorSettings(BaseModel):
    """Comparator-specific configuration (provisional).

    All values are starting hypotheses and have not been validated. They only
    parameterise individual comparators; they do not encode scoring or the final
    duplicate decision.
    """

    model_config = ConfigDict(extra="forbid")

    text_backend: Literal["tfidf", "embedding"] = Field(
        default="embedding",
        description=(
            "Single text-similarity backend: the semantic embedding comparator "
            "or the lexical TF-IDF baseline."
        ),
    )
    embedding_model: str = Field(
        default="sentence-transformers/all-MiniLM-L6-v2",
        min_length=1,
        max_length=256,
        description=(
            "Sentence Transformers model identifier; downloaded on first use "
            "unless already present in the local Hugging Face cache."
        ),
    )
    time_decay_scale_seconds: float = Field(
        default=172_800.0,
        description="Time-decay scale (seconds); 48 hours provisionally.",
    )
    location_distance_scale_m: float = Field(
        default=500.0,
        description="Distance scale (metres) for the linear location decay.",
    )
    category_compatible_score: float = Field(
        default=0.60,
        ge=0.0,
        le=1.0,
        description="Score returned for a known-compatible category pair.",
    )
    category_map: CategoryCompatibilityMap = Field(
        default_factory=CategoryCompatibilityMap,
        description="Provisional category compatibility mapping.",
    )

    @field_validator("embedding_model")
    @classmethod
    def _non_blank_embedding_model(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("embedding_model must be a non-empty string")
        return cleaned

    @field_validator("time_decay_scale_seconds", "location_distance_scale_m")
    @classmethod
    def _finite_positive(cls, value: float, info) -> float:
        if not math.isfinite(value):
            raise ValueError(f"{info.field_name} must be a finite number")
        if value <= 0:
            raise ValueError(f"{info.field_name} must be greater than zero")
        return value


# --------------------------------------------------------------------------- #
# Decision-policy configuration (Phase 4 / M4)
#
# These knobs drive only ``app/scoring/decision_policy.py``: they turn
# already-computed candidate scores and per-signal evidence into a DUPLICATE /
# REVIEW_REQUIRED / NEW outcome. They never compute similarities or combine
# signals into a score (that is ``app/scoring/engine.py``, M3). Every value is a
# starting hypothesis, not a validated value.
# --------------------------------------------------------------------------- #


class DecisionPolicySettings(BaseModel):
    """Decision-policy configuration (Phase 4 / M4 — provisional).

    See ``docs/duplicate_detection/matching_policy.md`` section 6 for the
    evidence, contradiction and gate rules these knobs parameterise, and
    ``docs/duplicate_detection/phase4_decision_policy.md`` for how the policy
    applies them. None of these values has been validated against labelled data.
    """

    model_config = ConfigDict(extra="forbid")

    min_available_signals: int = Field(
        default=2,
        ge=1,
        le=len(_CORE_SIGNAL_NAMES),
        description="Minimum AVAILABLE core signals required before DUPLICATE.",
    )
    require_core_anchor: bool = Field(
        default=True,
        description="When True, DUPLICATE requires a supportive text or location signal.",
    )
    core_anchor_floor: float = Field(
        default=0.50,
        description="Minimum score for text/location to count as the core anchor.",
    )
    supportive_floor: float = Field(
        default=0.50,
        description="Minimum score for a signal to count as supportive evidence.",
    )
    require_corroboration: bool = Field(
        default=True,
        description="When True, DUPLICATE requires at least two supportive signals.",
    )
    location_conflict_text_floor: float = Field(
        default=0.80,
        description="C1: text score at/above which a very low location score conflicts.",
    )
    location_conflict_location_ceiling: float = Field(
        default=0.20,
        description="C1: location score at/below which C1 triggers (with the floor above).",
    )

    @field_validator(
        "core_anchor_floor",
        "supportive_floor",
        "location_conflict_text_floor",
        "location_conflict_location_ceiling",
    )
    @classmethod
    def _finite_unit_interval(cls, value: float, info) -> float:
        if not math.isfinite(value):
            raise ValueError(f"{info.field_name} must be a finite number")
        if not (0.0 <= value <= 1.0):
            raise ValueError(f"{info.field_name} must be between 0 and 1")
        return value

    @model_validator(mode="after")
    def _location_conflict_band_is_ordered(self) -> "DecisionPolicySettings":
        if self.location_conflict_location_ceiling >= self.location_conflict_text_floor:
            raise ValueError(
                "location_conflict_location_ceiling must be less than "
                "location_conflict_text_floor, otherwise the C1 contradiction "
                "rule would fire on ordinary matches"
            )
        return self


class Settings(BaseModel):
    """Aggregate, validated configuration for the matching policy."""

    model_config = ConfigDict(extra="forbid")

    weights: MatchingWeights = Field(default_factory=MatchingWeights)
    thresholds: DecisionThresholds = Field(default_factory=DecisionThresholds)
    comparators: ComparatorSettings = Field(default_factory=ComparatorSettings)
    decision: DecisionPolicySettings = Field(default_factory=DecisionPolicySettings)
    tie_margin: float = Field(
        default=0.05,
        ge=0.0,
        le=1.0,
        description="Score gap below which top candidates are treated as tied.",
    )
    policy_version: str = Field(
        default="v1-draft",
        description="Identifier echoed in responses for reproducibility.",
    )


DEFAULT_SETTINGS = Settings()
"""The default (provisional) policy configuration."""
