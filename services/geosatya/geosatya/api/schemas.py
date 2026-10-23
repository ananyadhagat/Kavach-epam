"""Request contracts. They check shape and ranges; they do not prove the
values are genuine."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

Float = dict(allow_inf_nan=False)
DeviceError = Literal["PERMISSION_DENIED", "TIMEOUT", "POSITION_UNAVAILABLE", "UNSUPPORTED", "NOT_REQUESTED"]


def _aware(value):
    if value is not None and value.tzinfo is None:
        raise ValueError("timestamps must include a timezone")
    return value


class DeviceLocation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    latitude: float = Field(ge=-90, le=90, **Float)
    longitude: float = Field(ge=-180, le=180, **Float)
    accuracy_m: float | None = Field(default=None, gt=0, le=100_000, **Float)
    # When the device says it measured this position (not when it was sent).
    observed_at: datetime | None = None
    # SIMULATED is a labelled development mode, never real GPS.
    mode: Literal["LIVE", "SIMULATED"] = "LIVE"

    _tz = field_validator("observed_at")(_aware)


class UserLocation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    latitude: float = Field(ge=-90, le=90, **Float)
    longitude: float = Field(ge=-180, le=180, **Float)


class PhotoMeta(BaseModel):
    model_config = ConfigDict(extra="forbid")

    capture_source: Literal["CAMERA_LIVE", "CAMERA_INPUT", "GALLERY"] = "GALLERY"
    captured_at: datetime | None = None  # only meaningful for CAMERA_LIVE
    uploaded_at: datetime | None = None

    _tz = field_validator("captured_at", "uploaded_at")(_aware)


class IncidentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    category: str = Field(min_length=1, max_length=50)
    title: str = Field(min_length=3, max_length=120)
    description: str = Field(min_length=10, max_length=2000)
    asset_identifier: str | None = Field(default=None, max_length=120)
    device_location: DeviceLocation | None = None
    device_location_error: DeviceError | None = None
    user_location: UserLocation | None = None
    photos_meta: list[PhotoMeta] = Field(default_factory=list, max_length=3)


class CompletionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    description: str = Field(default="", max_length=2000)
    photo_meta: PhotoMeta = PhotoMeta()
    device_location: DeviceLocation | None = None
    device_location_error: DeviceError | None = None


class ReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Literal["APPROVE", "REJECT", "REQUEST_EVIDENCE"]
    reason: str = Field(default="", max_length=1000)


class CorrectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    latitude: float = Field(ge=-90, le=90, **Float)
    longitude: float = Field(ge=-180, le=180, **Float)
    reason: str = Field(min_length=5, max_length=300)


class SettingsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    geofence_radius_m: float = Field(**Float)
    max_accuracy_m: float = Field(**Float)
