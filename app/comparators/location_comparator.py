"""Location comparator.

Compares the location objects of a new complaint and an existing candidate using
two independent kinds of evidence: authoritative **identifiers** and
**coordinates**.

Identifier precedence (documented, first decisive rule wins)
------------------------------------------------------------
1. Both sides carry a non-empty ``location_id``:
   * the ``location_id`` values are equal:
       - if both ``facility_id`` values are present and differ -> **conflict**
         (different facilities can share a location-id *string* but are not the
         same site);
       - otherwise -> identifier match.
   * the ``location_id`` values differ:
       - if both ``facility_id`` values are present and equal -> facility match
         (same facility, different named sub-site);
       - otherwise -> identifier conflict.
2. Otherwise, both sides carry a non-empty ``facility_id``:
   * equal -> facility match;
   * differ -> conflict.
3. Otherwise, fall back to coordinates (Haversine distance) when both sides
   carry a valid coordinate pair.
4. Otherwise -> ``UNAVAILABLE`` (no usable location evidence).

Missing identifiers are never treated as a mismatch: rule 3/4 simply take over.
Differing *present* identifiers, by contrast, are genuinely conflicting
evidence and are surfaced explicitly.

Conflicting identifiers are **always** reported even when the coordinates look
close. A conflict yields ``AVAILABLE`` score ``0.0`` with
``details["conflict"] is True`` and ``details["conflict_code"]`` set, and the
coordinate distance (when computable) is preserved alongside it so Phase 4 can
reason about the contradiction. ``SignalResult`` has no dedicated conflict
field, so the flag lives in ``details`` without changing the shared contract.

Geographic distance
-------------------
Distance uses the Haversine formula with Earth's mean radius of 6,371,000 m.
The coordinate-to-score mapping is a **configurable linear decay** consistent
with the Phase 1 radius idea::

    score = clamp(1 - distance_m / distance_scale_m, 0, 1)

so identical points score ``1.0`` and scores never increase with distance. The
scale is provisional and does **not** mean "within the radius => duplicate";
that judgement belongs to Phase 4.

Outcomes
--------
* usable identifier or coordinate evidence ... ``AVAILABLE``
* present-but-malformed coordinates .......... ``INVALID`` (score ``None``)
* no usable location evidence ................ ``UNAVAILABLE`` (score ``None``)

Malformed coordinates are only *fatal* when coordinates are the chosen basis. If
a decisive identifier comparison exists, it still decides and the malformed
coordinates are noted in ``details``.
"""

from __future__ import annotations

import math
from typing import Any

from app.comparators.base import (
    Comparator,
    available_signal,
    invalid_signal,
    unavailable_signal,
)
from app.config.settings import DEFAULT_SETTINGS
from app.schemas.complaint import Complaint, Location
from app.schemas.duplicate_response import SignalResult

#: Earth's mean radius in metres (Haversine).
EARTH_RADIUS_M = 6_371_000.0

_LATITUDE_MIN = -90.0
_LATITUDE_MAX = 90.0
_LONGITUDE_MIN = -180.0
_LONGITUDE_MAX = 180.0

# Coordinate-state tags.
_OK = "ok"
_NONE = "none"
_INVALID = "invalid"


def haversine_meters(
    latitude_a: float, longitude_a: float, latitude_b: float, longitude_b: float
) -> float:
    """Great-circle distance in metres between two WGS84 points."""
    phi_a = math.radians(latitude_a)
    phi_b = math.radians(latitude_b)
    delta_phi = math.radians(latitude_b - latitude_a)
    delta_lambda = math.radians(longitude_b - longitude_a)

    haversine = (
        math.sin(delta_phi / 2.0) ** 2
        + math.cos(phi_a) * math.cos(phi_b) * math.sin(delta_lambda / 2.0) ** 2
    )
    return 2.0 * EARTH_RADIUS_M * math.asin(min(1.0, math.sqrt(haversine)))


def _norm_identifier(value: object) -> str | None:
    """Trim an identifier; blank/non-string input becomes ``None``."""
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped if stripped else None


def _coordinate_state(
    location: Location,
) -> tuple[str, float | None, float | None, str | None]:
    """Classify a location's coordinates.

    Returns ``(state, latitude, longitude, invalid_reason)`` where ``state`` is
    one of ``_OK`` (both valid), ``_NONE`` (both absent) or ``_INVALID`` (one
    present only, non-numeric, non-finite, or out of range).
    """
    latitude = getattr(location, "latitude", None)
    longitude = getattr(location, "longitude", None)

    if latitude is None and longitude is None:
        return (_NONE, None, None, None)

    if (latitude is None) != (longitude is None):
        return (_INVALID, None, None, "LONE_COORDINATE")

    for name, value in (("latitude", latitude), ("longitude", longitude)):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return (_INVALID, None, None, f"NON_NUMERIC_{name.upper()}")
        if not math.isfinite(value):
            return (_INVALID, None, None, f"NON_FINITE_{name.upper()}")

    if not (_LATITUDE_MIN <= latitude <= _LATITUDE_MAX):
        return (_INVALID, None, None, "LATITUDE_OUT_OF_RANGE")
    if not (_LONGITUDE_MIN <= longitude <= _LONGITUDE_MAX):
        return (_INVALID, None, None, "LONGITUDE_OUT_OF_RANGE")

    return (_OK, float(latitude), float(longitude), None)


class LocationComparator(Comparator):
    """Compare complaint locations using identifiers and/or coordinates.

    Parameters
    ----------
    distance_scale_m:
        Distance scale (metres) for the linear coordinate decay. Must be finite
        and positive. Defaults to the configured provisional value (500 m).
    facility_match_score:
        Score for a same-facility (different sub-site) match. Must be finite and
        inside ``[0, 1]``. Defaults to the configured
        ``category_compatible_score``-style partial value (0.60).
    """

    name = "location"

    def __init__(
        self,
        distance_scale_m: float | None = None,
        facility_match_score: float | None = None,
    ) -> None:
        if distance_scale_m is None:
            distance_scale_m = DEFAULT_SETTINGS.comparators.location_distance_scale_m
        if facility_match_score is None:
            facility_match_score = 0.60
        if not math.isfinite(distance_scale_m) or distance_scale_m <= 0:
            raise ValueError(
                "distance_scale_m must be a finite value greater than zero"
            )
        if (
            not math.isfinite(facility_match_score)
            or not (0.0 <= facility_match_score <= 1.0)
        ):
            raise ValueError(
                "facility_match_score must be a finite value between 0 and 1"
            )
        self._distance_scale_m = float(distance_scale_m)
        self._facility_match_score = float(facility_match_score)

    # -- record-level entry point ------------------------------------------ #
    def compare(self, complaint: Complaint, candidate: Complaint) -> SignalResult:
        """Compare ``complaint.location`` with ``candidate.location``."""
        return self.compare_locations(complaint.location, candidate.location)

    # -- field-level entry point ------------------------------------------- #
    def compare_locations(
        self, location_a: Location | None, location_b: Location | None
    ) -> SignalResult:
        """Compare two raw location objects."""
        if location_a is None or location_b is None:
            return unavailable_signal(
                "LOCATION_UNAVAILABLE",
                _id_details(None, None, None, None),
            )

        facility_a = _norm_identifier(location_a.facility_id)
        location_id_a = _norm_identifier(location_a.location_id)
        facility_b = _norm_identifier(location_b.facility_id)
        location_id_b = _norm_identifier(location_b.location_id)

        ids = _id_details(facility_a, location_id_a, facility_b, location_id_b)

        # Rule 1 — both location ids present.
        if location_id_a and location_id_b:
            if facility_a and facility_b and facility_a != facility_b:
                return self._conflict(
                    "LOCATION_FACILITY_CONFLICT",
                    ids,
                    location_a,
                    location_b,
                )
            if location_id_a == location_id_b:
                return self._identifier_match(
                    "LOCATION_IDENTIFIER_MATCH", 1.0, ids, location_a, location_b
                )
            if facility_a and facility_b and facility_a == facility_b:
                return self._identifier_match(
                    "LOCATION_FACILITY_MATCH",
                    self._facility_match_score,
                    ids,
                    location_a,
                    location_b,
                )
            return self._conflict(
                "LOCATION_IDENTIFIER_CONFLICT", ids, location_a, location_b
            )

        # Rule 2 — both facility ids present.
        if facility_a and facility_b:
            if facility_a != facility_b:
                return self._conflict(
                    "LOCATION_FACILITY_CONFLICT", ids, location_a, location_b
                )
            return self._identifier_match(
                "LOCATION_FACILITY_MATCH",
                self._facility_match_score,
                ids,
                location_a,
                location_b,
            )

        # Rule 3 — coordinates.
        state_a = _coordinate_state(location_a)
        state_b = _coordinate_state(location_b)

        if state_a[0] == _INVALID:
            return invalid_signal(
                "LOCATION_INVALID",
                {**ids, "invalid_reason": state_a[3], "side": "a",
                 "coordinates_valid": False},
            )
        if state_b[0] == _INVALID:
            return invalid_signal(
                "LOCATION_INVALID",
                {**ids, "invalid_reason": state_b[3], "side": "b",
                 "coordinates_valid": False},
            )

        if state_a[0] == _OK and state_b[0] == _OK:
            distance = haversine_meters(state_a[1], state_a[2], state_b[1], state_b[2])
            score = max(0.0, 1.0 - distance / self._distance_scale_m)
            return available_signal(
                score,
                "LOCATION_PROXIMITY",
                {
                    **ids,
                    "basis": "coordinates",
                    "distance_m": distance,
                    "distance_scale_m": self._distance_scale_m,
                    "latitude_a": state_a[1],
                    "longitude_a": state_a[2],
                    "latitude_b": state_b[1],
                    "longitude_b": state_b[2],
                },
            )

        # Rule 4 — no usable evidence.
        return unavailable_signal(
            "LOCATION_UNAVAILABLE",
            {**ids, "coordinates_valid": False},
        )

    # -- helpers ----------------------------------------------------------- #
    def _identifier_match(
        self,
        reason: str,
        score: float,
        ids: dict[str, Any],
        location_a: Location,
        location_b: Location,
    ) -> SignalResult:
        details: dict[str, Any] = {**ids, "basis": "identifier"}
        distance = self._supporting_distance(location_a, location_b)
        if distance is not None:
            details["distance_m"] = distance
        return available_signal(score, reason, details)

    def _conflict(
        self,
        conflict_code: str,
        ids: dict[str, Any],
        location_a: Location,
        location_b: Location,
    ) -> SignalResult:
        details: dict[str, Any] = {
            **ids,
            "basis": "identifier",
            "conflict": True,
            "conflict_code": conflict_code,
        }
        distance = self._supporting_distance(location_a, location_b)
        if distance is not None:
            # Preserve the (possibly contradictory) proximity evidence for Phase 4.
            details["distance_m"] = distance
            details["distance_scale_m"] = self._distance_scale_m
        return available_signal(0.0, conflict_code, details)

    @staticmethod
    def _supporting_distance(
        location_a: Location, location_b: Location
    ) -> float | None:
        """Best-effort Haversine distance, or ``None`` when not computable."""
        state_a = _coordinate_state(location_a)
        state_b = _coordinate_state(location_b)
        if state_a[0] != _OK or state_b[0] != _OK:
            return None
        return haversine_meters(state_a[1], state_a[2], state_b[1], state_b[2])


def _id_details(
    facility_a: str | None,
    location_id_a: str | None,
    facility_b: str | None,
    location_id_b: str | None,
) -> dict[str, Any]:
    return {
        "facility_a": facility_a,
        "location_a": location_id_a,
        "facility_b": facility_b,
        "location_b": location_id_b,
    }


__all__ = ["EARTH_RADIUS_M", "LocationComparator", "haversine_meters"]
