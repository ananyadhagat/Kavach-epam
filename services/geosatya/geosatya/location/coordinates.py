"""Coordinate validation and straight-line distance."""

import math

# Mean Earth radius (IUGG). Haversine vs. the WGS-84 ellipsoid differs by
# under 0.5%, i.e. centimetres over the distances that matter here.
EARTH_RADIUS_M = 6_371_008.8


class CoordinateError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def is_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def validate_coordinates(latitude: object, longitude: object) -> tuple[float, float]:
    """Return (lat, lon) as floats or raise CoordinateError."""
    if not is_number(latitude) or not is_number(longitude):
        raise CoordinateError("COORDINATES_NOT_FINITE", "Latitude and longitude must be finite numbers.")
    if not -90.0 <= latitude <= 90.0:
        raise CoordinateError("LATITUDE_OUT_OF_RANGE", "Latitude must be between -90 and 90.")
    if not -180.0 <= longitude <= 180.0:
        raise CoordinateError("LONGITUDE_OUT_OF_RANGE", "Longitude must be between -180 and 180.")
    if latitude == 0 and longitude == 0:  # open ocean; almost always an unset default
        raise CoordinateError("NULL_ISLAND", "Coordinates (0, 0) are treated as missing.")
    return float(latitude), float(longitude)


def is_valid_pair(latitude: object, longitude: object) -> bool:
    try:
        validate_coordinates(latitude, longitude)
    except CoordinateError:
        return False
    return True


def validate_accuracy(accuracy_m: object) -> float | None:
    """Accuracy is optional; when given it must be a sane positive number."""
    if accuracy_m is None:
        return None
    if not is_number(accuracy_m) or accuracy_m <= 0 or accuracy_m > 100_000:
        raise CoordinateError("ACCURACY_INVALID", "Accuracy must be a positive number of metres.")
    return float(accuracy_m)


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in metres. Straight line, not travel distance."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    a = (math.sin((phi2 - phi1) / 2) ** 2
         + math.cos(phi1) * math.cos(phi2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2)
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(min(1.0, max(0.0, a))))
