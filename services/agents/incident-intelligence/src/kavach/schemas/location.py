"""Location contracts. Every source is kept separate; none silently overwrites another."""
from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class LocationSource(str, Enum):
    USER_SELECTED_PIN = "USER_SELECTED_PIN"      # where the citizen says the incident is
    DEVICE_GEOLOCATION = "DEVICE_GEOLOCATION"    # where the device says it is now
    IMAGE_EXIF = "IMAGE_EXIF"                    # GPS embedded in an image (editable!)
    FACILITY_REFERENCE = "FACILITY_REFERENCE"    # admin-approved site coordinate


class LocationStatus(str, Enum):
    CONSISTENT = "CONSISTENT"
    MISMATCH = "MISMATCH"
    INCONCLUSIVE = "INCONCLUSIVE"
    NOT_CHECKED = "NOT_CHECKED"


class ReasonCode(str, Enum):
    NO_TARGET_COORDINATE = "NO_TARGET_COORDINATE"
    NO_COMPARISON_SOURCE = "NO_COMPARISON_SOURCE"
    WITHIN_CONFIGURED_RADIUS = "WITHIN_CONFIGURED_RADIUS"
    OUTSIDE_CONFIGURED_RADIUS = "OUTSIDE_CONFIGURED_RADIUS"
    WITHIN_ACCURACY_UNCERTAINTY = "WITHIN_ACCURACY_UNCERTAINTY"
    POOR_DEVICE_ACCURACY = "POOR_DEVICE_ACCURACY"
    DEVICE_LOCATION_UNAVAILABLE = "DEVICE_LOCATION_UNAVAILABLE"
    EXIF_GPS_MISSING = "EXIF_GPS_MISSING"
    EXIF_UNREADABLE = "EXIF_UNREADABLE"
    EXIF_TIME_MISSING = "EXIF_TIME_MISSING"
    SOURCE_CONFLICT = "SOURCE_CONFLICT"
    REMOTE_REPORT_POSSIBLE = "REMOTE_REPORT_POSSIBLE"


class Coordinates(BaseModel):
    model_config = ConfigDict(frozen=True)
    latitude: float = Field(ge=-90, le=90, allow_inf_nan=False)
    longitude: float = Field(ge=-180, le=180, allow_inf_nan=False)


class DeviceLocation(Coordinates):
    accuracy_meters: float | None = Field(default=None, ge=0, le=100_000, allow_inf_nan=False)
    observed_at: datetime | None = None  # client-supplied: untrusted
    source: LocationSource = LocationSource.DEVICE_GEOLOCATION


class ImageMetadataStatus(str, Enum):
    GPS_FOUND = "GPS_FOUND"
    GPS_MISSING = "GPS_MISSING"
    INVALID_GPS = "INVALID_GPS"
    UNREADABLE = "UNREADABLE"


class ImageMetadataResult(BaseModel):
    """Server-generated. Only the fields KAVACH needs are kept - never the raw EXIF dump."""
    media_id: str
    status: ImageMetadataStatus
    coordinates: Coordinates | None = None
    claimed_captured_at: datetime | None = None  # EXIF time is editable: a claim, not proof
    reason_codes: list[ReasonCode] = Field(default_factory=list)


class SourceComparison(BaseModel):
    source: LocationSource
    media_id: str | None = None
    status: LocationStatus
    distance_meters: float | None = None
    accuracy_meters: float | None = None
    reason_codes: list[ReasonCode] = Field(default_factory=list)


class LocationCheckSummary(BaseModel):
    status: LocationStatus
    distance_meters: float | None = None  # smallest distance among comparable sources
    target_source: LocationSource | None = None
    evidence_sources: list[LocationSource] = Field(default_factory=list)
    comparisons: list[SourceComparison] = Field(default_factory=list)
    reason_codes: list[ReasonCode] = Field(default_factory=list)
    requires_human_review: bool = False
    rule_version: str
    warning: str = "Location consistency is a signal, not proof that the complaint is true."
