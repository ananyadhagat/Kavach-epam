"""Time comparator.

Compares the ``reported_at`` timestamps of a new complaint and a candidate using
a configurable, strictly-monotonic exponential decay::

    score = exp(-time_gap_seconds / decay_scale_seconds)

Properties guaranteed by this module:

* Equal instants score ``1.0`` — including two different UTC offsets that
  represent the *same* instant.
* The score is monotonically non-increasing as the absolute gap grows; it never
  rises as reports get further apart in time.
* The decay scale is configuration, not a hard-coded window, so it can be tuned
  without editing this file.

Outcomes
--------
* both aware timestamps ...................... ``AVAILABLE`` (finite score)
* either timestamp missing ................... ``UNAVAILABLE`` (score ``None``)
* naive, non-datetime or otherwise unusable ... ``INVALID`` (score ``None``)

Policy note
-----------
This comparator only measures *temporal closeness*. It does **not** decide
whether two reports a given number of hours apart are the same incident; that
eligibility/weighted policy belongs to Phase 4.

The provisional decay above is the plain exponential suggested for Phase 3. The
Phase 1 ``matching_policy.md`` sketched a variant with a non-zero floor
(``FLOOR + (1 - FLOOR) * exp(...)``). Adding that floor is a Phase 4 policy
choice and is deliberately not applied here.
"""

from __future__ import annotations

import math
from datetime import datetime
from typing import Any

from app.comparators.base import (
    Comparator,
    available_signal,
    invalid_signal,
    unavailable_signal,
)
from app.config.settings import DEFAULT_SETTINGS
from app.schemas.complaint import Complaint
from app.schemas.duplicate_response import SignalResult


def _is_aware(value: object) -> bool:
    """Return True for a timezone-aware :class:`datetime`."""
    return (
        isinstance(value, datetime)
        and value.tzinfo is not None
        and value.utcoffset() is not None
    )


class TimeComparator(Comparator):
    """Compare report timestamps with an exponential decay.

    Parameters
    ----------
    decay_scale_seconds:
        The exponential time scale in seconds. Must be finite and positive.
        Defaults to the configured provisional value (48 hours).
    """

    name = "time"

    def __init__(self, decay_scale_seconds: float | None = None) -> None:
        if decay_scale_seconds is None:
            decay_scale_seconds = DEFAULT_SETTINGS.comparators.time_decay_scale_seconds
        if (
            not math.isfinite(decay_scale_seconds)
            or decay_scale_seconds <= 0
        ):
            raise ValueError(
                "decay_scale_seconds must be a finite value greater than zero"
            )
        self._decay_scale_seconds = float(decay_scale_seconds)

    # -- record-level entry point ------------------------------------------ #
    def compare(self, complaint: Complaint, candidate: Complaint) -> SignalResult:
        """Compare ``complaint.reported_at`` with ``candidate.reported_at``."""
        return self.compare_timestamps(complaint.reported_at, candidate.reported_at)

    # -- field-level entry point ------------------------------------------- #
    def compare_timestamps(self, time_a: object, time_b: object) -> SignalResult:
        """Compare two raw timestamp values."""
        details: dict[str, Any] = {
            "reported_at_a": _render(time_a),
            "reported_at_b": _render(time_b),
            "decay_scale_seconds": self._decay_scale_seconds,
        }

        if time_a is None or time_b is None:
            return unavailable_signal("TIME_UNAVAILABLE", details)

        if not _is_aware(time_a) or not _is_aware(time_b):
            return invalid_signal("TIME_INVALID", details)

        # Both are aware datetimes; subtraction is well-defined across offsets
        # and yields the true absolute gap.
        gap_seconds = abs((time_a - time_b).total_seconds())
        score = math.exp(-gap_seconds / self._decay_scale_seconds)

        return available_signal(
            score,
            "TIME_DECAY",
            {
                **details,
                "difference_seconds": gap_seconds,
                "difference_hours": gap_seconds / 3600.0,
            },
        )


def _render(value: object) -> str | None:
    """Render a raw timestamp value for the ``details`` block."""
    if value is None:
        return None
    return value.isoformat() if isinstance(value, datetime) else str(value)


__all__ = ["TimeComparator"]
