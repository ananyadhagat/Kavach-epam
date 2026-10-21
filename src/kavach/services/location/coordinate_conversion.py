"""EXIF GPS (degrees/minutes/seconds rationals) -> signed decimal degrees."""
from __future__ import annotations

import math
from typing import Any, Sequence


def _to_float(value: Any) -> float:
    """Accept IFDRational, Fraction, (num, den) tuples, ints, floats."""
    if isinstance(value, tuple) and len(value) == 2:
        num, den = value
        if den == 0:
            raise ValueError("zero denominator")
        return float(num) / float(den)
    f = float(value)
    if not math.isfinite(f):
        raise ValueError("non-finite component")
    return f


def dms_to_decimal(dms: Sequence[Any], ref: str | bytes | None) -> float:
    """Convert (deg, min, sec) + hemisphere ref (N/S/E/W) to signed decimal degrees.

    S and W are negative. Raises ValueError on anything malformed.
    """
    if dms is None or len(dms) != 3:
        raise ValueError("DMS must have exactly 3 components")
    if isinstance(ref, bytes):
        ref = ref.decode("ascii", errors="ignore")
    ref = (ref or "").strip().upper()
    if ref not in {"N", "S", "E", "W"}:
        raise ValueError(f"invalid hemisphere reference: {ref!r}")
    deg, minutes, seconds = (_to_float(c) for c in dms)
    if deg < 0 or not (0 <= minutes < 60) or not (0 <= seconds < 60):
        raise ValueError("DMS component out of range")
    value = deg + minutes / 60.0 + seconds / 3600.0
    return -value if ref in {"S", "W"} else value


def validate_coordinates(latitude: float, longitude: float) -> None:
    if not (math.isfinite(latitude) and math.isfinite(longitude)):
        raise ValueError("coordinates must be finite")
    if not (-90 <= latitude <= 90) or not (-180 <= longitude <= 180):
        raise ValueError("coordinates out of range")
