"""Backward-compatible imports for the shared location verification service."""

from .location_service import combine_location_checks, haversine_m, verify_location

__all__ = ["combine_location_checks", "haversine_m", "verify_location"]
