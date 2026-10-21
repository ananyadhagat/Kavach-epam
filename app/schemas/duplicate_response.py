"""Decision, signal and response schemas for duplicate detection.

This implements the response side of the V1 contract in
``docs/duplicate_detection/api_contract.md`` and the signal model in
``docs/duplicate_detection/matching_policy.md``.

Response invariants (documented here, enforced later by the decision engine —
deliberately **not** enforced as cross-field validation in this foundation
phase, so that ``REVIEW_REQUIRED`` and ambiguous/empty responses remain
representable):

* ``decision == DUPLICATE`` requires ``matched_incident_id`` to be set and a
  non-null ``score``.
* ``decision == NEW`` requires ``matched_incident_id`` to be ``None``.
* ``decision == REVIEW_REQUIRED`` requires ``matched_incident_id`` to be
  ``None`` unless a candidate is explicitly labelled as a *leading candidate for
  review* (representation added in a later phase).
* ``score`` is a **ranking score in [0, 1]**, never a calibrated probability.
* For every entry in ``signals``: a non-``AVAILABLE`` status must carry a
  ``null`` score. Missing evidence is never coerced to ``0``. This one *is*
  enforced here, because it is a per-signal invariant rather than a decision
  rule.
"""

from __future__ import annotations

import math
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Decision(str, Enum):
    """Overall duplicate-detection outcome."""

    DUPLICATE = "DUPLICATE"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    NEW = "NEW"


class SignalStatus(str, Enum):
    """Availability of a single evidence signal.

    ``AVAILABLE``    — input was sufficient and a score in [0, 1] was computed.
    ``UNAVAILABLE``  — input was absent (or the comparator is disabled).
    ``INVALID``      — input was present but unusable.
    ``ERROR``        — the comparator raised unexpectedly.
    """

    AVAILABLE = "AVAILABLE"
    UNAVAILABLE = "UNAVAILABLE"
    INVALID = "INVALID"
    ERROR = "ERROR"


def _validate_unit_interval(
    value: float | None,
    field_name: str,
) -> float | None:
    """Validate that a score is finite and within [0, 1] when present."""
    if value is None:
        return None
    if not math.isfinite(value):
        raise ValueError(f"{field_name} must be a finite number")
    if not (0.0 <= value <= 1.0):
        raise ValueError(f"{field_name} must be between 0 and 1")
    return value


class SignalResult(BaseModel):
    """Result of a single evidence signal for one candidate comparison."""

    model_config = ConfigDict(extra="forbid")

    status: SignalStatus = Field(description="Availability of this signal.")
    score: float | None = Field(
        default=None,
        description="Similarity contribution in [0, 1]; null unless status is AVAILABLE.",
    )
    reason: str | None = Field(
        default=None,
        description="Optional reason code explaining the signal outcome.",
    )
    details: dict[str, Any] | None = Field(
        default=None,
        description="Optional structured supporting facts (method, distance, etc.).",
    )

    @model_validator(mode="after")
    def _score_matches_status(self) -> "SignalResult":
        if self.status is SignalStatus.AVAILABLE:
            if self.score is None:
                raise ValueError("an AVAILABLE signal must provide a score")
            _validate_unit_interval(self.score, "signal score")
        elif self.score is not None:
            raise ValueError(
                f"a {self.status.value} signal must have a null score; "
                "missing evidence must not be represented as a numeric score"
            )
        return self


class DuplicateDetectionResponse(BaseModel):
    """Response contract for ``POST /api/v1/duplicate-detection/check`` (V1).

    Additional blocks from Phase 1 (``candidates``, ``search``, ``policy``,
    ``request_id``) are intentionally deferred to a later phase.
    """

    model_config = ConfigDict(extra="forbid")

    complaint_id: str = Field(
        min_length=1,
        max_length=64,
        description="Echoes the submitted complaint identifier.",
    )
    decision: Decision = Field(description="Overall outcome.")
    matched_incident_id: str | None = Field(
        default=None,
        max_length=64,
        description="Proposed matching incident id, or null when not asserted.",
    )
    score: float | None = Field(
        default=None,
        description="Ranking score in [0, 1]; not a calibrated probability.",
    )
    signals: dict[str, SignalResult] = Field(
        default_factory=dict,
        description="Per-signal results keyed by signal name "
        "(text, location, category, time, image).",
    )
    reasons: list[str] = Field(
        default_factory=list,
        description="Explicit reason codes; treat as an open, additive set.",
    )

    @model_validator(mode="after")
    def _validate_score(self) -> "DuplicateDetectionResponse":
        _validate_unit_interval(self.score, "score")
        return self
