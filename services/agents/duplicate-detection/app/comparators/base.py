"""Shared contract for the core duplicate-detection comparators (Phase 3).

Every comparator compares one *new* complaint against one *existing candidate*
and returns a single :class:`~app.schemas.duplicate_response.SignalResult`.

Reusing ``SignalResult`` keeps the whole signal contract in one place:

* ``status``  — ``AVAILABLE`` / ``UNAVAILABLE`` / ``INVALID`` / ``ERROR``.
* ``score``   — finite value in ``[0, 1]`` **only** when the status is
  ``AVAILABLE``; otherwise ``None``.
* ``reason``  — a short, machine-readable reason code.
* ``details`` — optional structured evidence (distance, basis, conflict flags…).

Design rules that every comparator must honour (mirrored by the contract tests
in ``tests/test_comparator_contract.py``):

1. An available score is always finite and inside ``[0, 1]``.
2. Missing evidence becomes ``UNAVAILABLE`` with a ``None`` score — never ``0``.
3. Present-but-unusable evidence becomes ``INVALID`` — never an ordinary low
   score.
4. Expected missing optional fields never raise; only genuine programming
   errors (e.g. a non-finite score) do.
5. Comparators are pure and deterministic: they never mutate the complaint
   models or repository records and never consult mutable global state.
6. No comparator decides the final outcome. They emit *evidence only*; the
   weighted scoring engine and the decision policy are in Phase 4.

This module intentionally avoids a deep inheritance hierarchy: a single small
ABC plus a few result builders is enough to keep the four comparators
consistent.
"""

from __future__ import annotations

import math
from abc import ABC, abstractmethod
from typing import Any, ClassVar

from app.schemas.complaint import Complaint
from app.schemas.duplicate_response import SignalResult, SignalStatus


def clamp_unit_score(value: float) -> float:
    """Clamp a computed similarity into ``[0, 1]``.

    Raises ``ValueError`` when ``value`` is not finite: a non-finite score is a
    programming error and must not be silently swallowed (design rule 4).
    """
    if not math.isfinite(value):
        raise ValueError(f"comparator produced a non-finite score: {value!r}")
    if value < 0.0:
        return 0.0
    if value > 1.0:
        return 1.0
    return float(value)


def available_signal(
    score: float,
    reason: str | None = None,
    details: dict[str, Any] | None = None,
) -> SignalResult:
    """Build an ``AVAILABLE`` signal with a clamped, finite score."""
    return SignalResult(
        status=SignalStatus.AVAILABLE,
        score=clamp_unit_score(score),
        reason=reason,
        details=details or None,
    )


def unavailable_signal(
    reason: str | None = None,
    details: dict[str, Any] | None = None,
) -> SignalResult:
    """Build an ``UNAVAILABLE`` signal (missing evidence; score is ``None``)."""
    return SignalResult(
        status=SignalStatus.UNAVAILABLE,
        score=None,
        reason=reason,
        details=details or None,
    )


def invalid_signal(
    reason: str | None = None,
    details: dict[str, Any] | None = None,
) -> SignalResult:
    """Build an ``INVALID`` signal (present but unusable; score is ``None``)."""
    return SignalResult(
        status=SignalStatus.INVALID,
        score=None,
        reason=reason,
        details=details or None,
    )


def error_signal(
    reason: str | None = None,
    details: dict[str, Any] | None = None,
) -> SignalResult:
    """Build an ``ERROR`` signal (unexpected comparator failure)."""
    return SignalResult(
        status=SignalStatus.ERROR,
        score=None,
        reason=reason,
        details=details or None,
    )


class Comparator(ABC):
    """Minimal interface shared by all core comparators.

    A comparator is stateless with respect to the complaints it reads; its only
    state is immutable configuration supplied at construction time.
    """

    #: Short, stable identifier matching the response's ``signals`` key.
    name: ClassVar[str] = "comparator"

    @abstractmethod
    def compare(self, complaint: Complaint, candidate: Complaint) -> SignalResult:
        """Return the signal result for ``complaint`` versus ``candidate``.

        Implementations must not mutate either argument.
        """
        raise NotImplementedError


__all__ = [
    "Comparator",
    "available_signal",
    "clamp_unit_score",
    "error_signal",
    "invalid_signal",
    "unavailable_signal",
]
