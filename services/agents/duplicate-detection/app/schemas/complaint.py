"""Complaint and location input schemas.

These models are the proposed **V1** contract from
``docs/duplicate_detection/api_contract.md``. Field names are placeholders and
may be mapped from the final KAVACH canonical names by an integration layer.

Validation policy (deliberate and documented):

* ``complaint_id`` is required, trimmed, and must be non-empty. Ids are opaque
  strings to this agent (1-64 characters).
* Optional free-text fields (``description``, ``category``, ``facility_id``,
  ``location_id``, ``image_hash``) are trimmed; a blank/whitespace-only value is
  normalised to ``None`` ("missing"), never invented into a real value.
* ``latitude``/``longitude`` must be finite numbers, within valid ranges, and
  supplied together.
* ``reported_at`` must be timezone-aware (Phase 1 requires an explicit UTC
  offset and forbids guessing the timezone).
* ``image_hash`` stays optional and only receives provisional validation
  (non-empty, <= 128 characters). Its exact format is a TEAM-DECISION in Phase 1
  and is not enforced here.
* Missing optional values are preserved as ``None``. Unknown extra fields are
  rejected so that typos and unmapped names surface early; an integration
  mapping layer is expected to translate names first.
"""

from __future__ import annotations

import math
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

_LATITUDE_MIN = -90.0
_LATITUDE_MAX = 90.0
_LONGITUDE_MIN = -180.0
_LONGITUDE_MAX = 180.0


def _blank_to_none(value: object) -> object:
    """Trim a string and treat blank/whitespace-only input as missing.

    Non-string values are returned unchanged so Pydantic raises the type error.
    """
    if isinstance(value, str):
        stripped = value.strip()
        return stripped if stripped else None
    return value


class Location(BaseModel):
    """Location context for a complaint.

    Every field is optional, but ``latitude`` and ``longitude`` must be supplied
    as a pair. Identifier-only locations (facility/location without coordinates)
    are valid.
    """

    model_config = ConfigDict(extra="forbid")

    facility_id: str | None = Field(
        default=None,
        max_length=64,
        description="Coarse facility identifier, e.g. 'FAC-CENTRAL-MARKET'.",
    )
    location_id: str | None = Field(
        default=None,
        max_length=64,
        description="Fine-grained location identifier, e.g. 'LOC-CM-GATE-NORTH'.",
    )
    latitude: float | None = Field(
        default=None,
        description="WGS84 latitude in decimal degrees, between -90 and 90.",
    )
    longitude: float | None = Field(
        default=None,
        description="WGS84 longitude in decimal degrees, between -180 and 180.",
    )

    @field_validator("facility_id", "location_id", mode="before")
    @classmethod
    def _normalise_identifiers(cls, value: object) -> object:
        return _blank_to_none(value)

    @field_validator("latitude", mode="after")
    @classmethod
    def _validate_latitude(cls, value: float | None) -> float | None:
        if value is None:
            return None
        if not math.isfinite(value):
            raise ValueError("latitude must be a finite number")
        if not (_LATITUDE_MIN <= value <= _LATITUDE_MAX):
            raise ValueError("latitude must be between -90 and 90")
        return value

    @field_validator("longitude", mode="after")
    @classmethod
    def _validate_longitude(cls, value: float | None) -> float | None:
        if value is None:
            return None
        if not math.isfinite(value):
            raise ValueError("longitude must be a finite number")
        if not (_LONGITUDE_MIN <= value <= _LONGITUDE_MAX):
            raise ValueError("longitude must be between -180 and 180")
        return value

    @model_validator(mode="after")
    def _require_coordinates_as_pair(self) -> "Location":
        has_latitude = self.latitude is not None
        has_longitude = self.longitude is not None
        if has_latitude != has_longitude:
            raise ValueError(
                "latitude and longitude must be supplied together "
                "(or both omitted)"
            )
        return self


class Complaint(BaseModel):
    """A single civic complaint submitted for duplicate detection.

    The same shape is reused as the stored record type by the repository, since
    Phase 1 defines an incident record as the comparable fields of a complaint.
    """

    model_config = ConfigDict(extra="forbid")

    complaint_id: str = Field(
        min_length=1,
        max_length=64,
        description="Opaque, non-empty complaint identifier.",
    )
    description: str | None = Field(
        default=None,
        max_length=5000,
        description="Free-text complaint description. Optional but improves matching.",
    )
    category: str | None = Field(
        default=None,
        max_length=64,
        description="Opaque category code; compatibility mapping arrives in a later phase.",
    )
    location: Location | None = Field(
        default=None,
        description="Optional location context.",
    )
    reported_at: datetime | None = Field(
        default=None,
        description="Timezone-aware timestamp of the report (ISO-8601 with offset).",
    )
    image_hash: str | None = Field(
        default=None,
        max_length=128,
        description="Optional perceptual image hash, e.g. 'phash:<hex>'. Provisional validation.",
    )

    @field_validator("complaint_id", mode="before")
    @classmethod
    def _normalise_complaint_id(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value

    @field_validator(
        "description",
        "category",
        "image_hash",
        mode="before",
    )
    @classmethod
    def _normalise_optional_text(cls, value: object) -> object:
        return _blank_to_none(value)

    @field_validator("reported_at", mode="after")
    @classmethod
    def _require_timezone_aware(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(
                "reported_at must be timezone-aware; include a UTC offset "
                "(e.g. 2026-10-14T09:15:00+05:30 or a trailing 'Z')"
            )
        return value
