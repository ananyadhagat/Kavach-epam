from datetime import datetime
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator


class LocationData(BaseModel):
    """Normalized incident location from Module 01."""

    model_config = ConfigDict(extra="ignore")

    latitude: float | None = None
    longitude: float | None = None
    facility_id: str | None = None
    location_id: str | None = None
    source: str | None = None
    accuracy_m: float | None = None


class MediaItem(BaseModel):
    """Media evidence reference from Module 01."""

    model_config = ConfigDict(extra="ignore")

    media_id: str
    media_type: str = "image"
    sha256: str | None = None
    storage_ref: str | None = None


class LocationEvidenceSummary(BaseModel):
    """Location evidence assessment from Module 01."""

    model_config = ConfigDict(extra="ignore")

    status: str = "INCONCLUSIVE"
    reason_codes: list[str] = Field(default_factory=list)


class QualityAssessment(BaseModel):
    """Data quality and completeness assessment from Module 01."""

    model_config = ConfigDict(extra="ignore")

    missing_information: list[str] = Field(default_factory=list)
    conflicting_information: list[str] = Field(default_factory=list)
    needs_clarification: bool = False


class IncidentRecord(BaseModel):
    """Module 01 Incident Intelligence upstream contract."""

    model_config = ConfigDict(extra="ignore")

    incident_id: str = Field(min_length=1)
    complaint_id: str = Field(min_length=1)
    incident_summary: str = Field(default="")
    complaint_text: str = Field(default="")
    category: str = Field(min_length=1)
    incident_type: str = Field(min_length=1)
    reported_at: datetime
    location: LocationData = Field(default_factory=LocationData)
    media: list[MediaItem] = Field(default_factory=list)
    location_evidence_summary: LocationEvidenceSummary = Field(
        default_factory=LocationEvidenceSummary
    )
    quality: QualityAssessment = Field(default_factory=QualityAssessment)

    # Optional physical attributes if available from upstream
    estimated_waste_kg: float | None = Field(default=None, ge=0)
    affected_area_sqm: float | None = Field(default=None, ge=0)
    path_obstructed: bool | None = None
    hazard_detected: bool | None = None

    @field_validator("reported_at")
    @classmethod
    def validate_timezone(cls, v: datetime) -> datetime:
        if v.tzinfo is None or v.utcoffset() is None:
            raise ValueError("reported_at timestamp must be timezone-aware")
        return v
