"""Shared deterministic location checks used by KAVACH workflow agents."""

import math

from ..contracts.v1 import LocationStatus
from ..schemas.gps_findings import GPSLocation


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius = 6_371_000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi, d_lambda = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return 2 * radius * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def verify_location(site: dict, location: dict | None, max_accuracy_m: float, tolerance_m: float | None) -> dict:
    for name, lower, upper in (("latitude", -90.0, 90.0), ("longitude", -180.0, 180.0)):
        value = site.get(name) if isinstance(site, dict) else None
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not lower <= value <= upper:
            return {"status": LocationStatus.INCONCLUSIVE.value, "score": None, "distance_m": None,
                    "reasons": [f"Task site {name} is invalid; location cannot be checked safely."]}
    if (isinstance(tolerance_m, bool) or not isinstance(tolerance_m, (int, float))
            or not math.isfinite(tolerance_m) or tolerance_m <= 0):
        return {"status": LocationStatus.INCONCLUSIVE.value, "score": None, "distance_m": None,
                "reasons": ["Task site tolerance is invalid; location cannot be checked safely."]}
    if location is None or (isinstance(location, dict) and location.get("capture_status") == "UNAVAILABLE"):
        return {"status": LocationStatus.UNAVAILABLE.value, "score": None, "distance_m": None,
                "reasons": ["No usable GPS event was submitted."]}
    if not isinstance(location, dict):
        return {"status": LocationStatus.INCONCLUSIVE.value, "score": None, "distance_m": None,
                "reasons": ["GPS location event is invalid; location cannot be checked safely."]}
    if location.get("capture_status") == "INACCURATE":
        return {"status": LocationStatus.INCONCLUSIVE.value, "score": None, "distance_m": None,
                "reasons": ["The submitted location event was marked INACCURATE."]}
    try:
        loc = GPSLocation.model_validate(location)
    except Exception as exc:
        detail = exc.errors()[0]["msg"] if hasattr(exc, "errors") else "invalid value"
        return {"status": LocationStatus.INCONCLUSIVE.value, "score": None, "distance_m": None,
                "reasons": [f"GPS coordinates or accuracy are invalid: {detail}"]}
    if loc.accuracy_m > max_accuracy_m or not loc.timestamp_valid:
        return {"status": LocationStatus.INCONCLUSIVE.value, "score": None, "distance_m": None,
                "reasons": [f"GPS accuracy must be at most {max_accuracy_m:g} m and timestamp must be valid."]}
    distance = haversine_m(site["latitude"], site["longitude"], loc.latitude, loc.longitude)
    if distance <= tolerance_m:
        return {"status": LocationStatus.CONSISTENT.value, "score": 100.0, "distance_m": round(distance, 1),
                "reasons": [f"Reported location is {distance:.1f} m from the task site (within {tolerance_m:g} m)."]}
    return {"status": LocationStatus.MISMATCH.value, "score": 0.0, "distance_m": round(distance, 1),
            "reasons": [f"Reported location is {distance:.1f} m from the task site, beyond the {tolerance_m:g} m tolerance."]}


def check_location(*, target: dict | None, evidence: dict | None, requested: bool = True,
                   max_accuracy_m: float, tolerance_m: float | None = None) -> dict:
    """Use cross-agent statuses; missing requested evidence is INCONCLUSIVE."""
    if not requested or target is None:
        return {"status": LocationStatus.NOT_CHECKED.value, "score": None, "distance_m": None,
                "reasons": ["Location was not checked because it was not requested or no target was supplied."]}
    if evidence is None:
        return {"status": LocationStatus.INCONCLUSIVE.value, "score": None, "distance_m": None,
                "reasons": ["Requested location evidence is unavailable."]}
    result = verify_location(target, evidence, max_accuracy_m, tolerance_m)
    if result["status"] == LocationStatus.UNAVAILABLE.value:
        result["status"] = LocationStatus.INCONCLUSIVE.value
    return result


def combine_location_checks(*statuses: str | LocationStatus) -> LocationStatus:
    """Elevate mutually conflicting source checks to the shared review status."""
    normalized = {status.value if isinstance(status, LocationStatus) else status for status in statuses}
    if "REVIEW_REQUIRED" in normalized or ({"CONSISTENT", "MISMATCH"} <= normalized):
        return LocationStatus.REVIEW_REQUIRED
    for status in ("INCONCLUSIVE", "UNAVAILABLE", "MISMATCH", "CONSISTENT", "NOT_CHECKED"):
        if status in normalized:
            return LocationStatus(status)
    return LocationStatus.NOT_CHECKED
