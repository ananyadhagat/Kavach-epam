"""Great-circle (straight-line) distance. Not road/walking distance. PostGIS can replace this later."""
from __future__ import annotations

from math import asin, cos, radians, sin, sqrt

from kavach.services.location.coordinate_conversion import validate_coordinates

EARTH_RADIUS_M = 6_371_000


def haversine_meters(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    validate_coordinates(lat1, lon1)
    validate_coordinates(lat2, lon2)
    lat1, lon1, lat2, lon2 = map(radians, (lat1, lon1, lat2, lon2))
    dlat, dlon = lat2 - lat1, lon2 - lon1
    a = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
    a = min(1.0, max(0.0, a))  # floating-point drift guard
    return 2 * EARTH_RADIUS_M * asin(sqrt(a))
