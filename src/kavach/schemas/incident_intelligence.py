"""Input / output contracts for Agent 1 (Incident Intelligence)."""
from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field

from kavach.schemas.location import (
    Coordinates,
    DeviceLocation,
    ImageMetadataResult,
    LocationCheckSummary,
    LocationSource,
)


# ---------------------------------------------------------------- taxonomy enums
class Category(str, Enum):
    """Aligned with the Supervisor Agent's department names so routing is a simple mapping."""
    SANITATION = "SANITATION"
    ELECTRICAL = "ELECTRICAL"
    WATER_SUPPLY = "WATER_SUPPLY"
    MAINTENANCE = "MAINTENANCE"
    PUBLIC_SAFETY = "PUBLIC_SAFETY"
    OTHER = "OTHER"


class IncidentType(str, Enum):
    WASTE_OVERFLOW = "WASTE_OVERFLOW"
    DIRTY_PUBLIC_TOILET = "DIRTY_PUBLIC_TOILET"
    LITTERING = "LITTERING"
    BROKEN_STREETLIGHT = "BROKEN_STREETLIGHT"
    EXPOSED_WIRING = "EXPOSED_WIRING"
    BROKEN_PIPE = "BROKEN_PIPE"
    WATER_LEAKAGE = "WATER_LEAKAGE"
    DAMAGED_BENCH = "DAMAGED_BENCH"
    ROAD_DAMAGE = "ROAD_DAMAGE"
    CROWD_CONGESTION = "CROWD_CONGESTION"
    FIRE_HAZARD = "FIRE_HAZARD"
    UNKNOWN = "UNKNOWN"


class Severity(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    UNKNOWN = "UNKNOWN"


class FactSource(str, Enum):
    COMPLAINT_TEXT = "COMPLAINT_TEXT"
    VOICE_TRANSCRIPT = "VOICE_TRANSCRIPT"
    IMAGE = "IMAGE"


class EvidenceSource(str, Enum):
    COMPLAINT_TEXT = "COMPLAINT_TEXT"
    VOICE_TRANSCRIPT = "VOICE_TRANSCRIPT"
    IMAGE = "IMAGE"
    IMAGE_EXIF = "IMAGE_EXIF"
    DEVICE_GEOLOCATION = "DEVICE_GEOLOCATION"
    USER_SELECTED_PIN = "USER_SELECTED_PIN"
    FACILITY_REFERENCE = "FACILITY_REFERENCE"
    LOCATION_CHECK = "LOCATION_CHECK"
    SEVERITY_RULE = "SEVERITY_RULE"
    LLM = "LLM"


# ---------------------------------------------------------------- request side

class IncidentSubmission(BaseModel):
    """What the API layer assembles from the citizen's request (before enrichment)."""
    request_id: str = Field(min_length=1, max_length=100)
    complaint_text: str | None = Field(default=None, max_length=5000)
    selected_incident_location: Coordinates | None = None
    device_location: DeviceLocation | None = None
    voice_transcript: str | None = Field(default=None, max_length=5000)
    facility_reference: Coordinates | None = None  # server-side lookup only; never client-trusted

class MediaReference(BaseModel):
    media_id: str
    accepted: bool
    mime_type: str | None = None
    width: int | None = None
    height: int | None = None
    sha256: str | None = None              # exact-file identity (full 64 hex chars)
    perceptual_hash: str | None = None     # 64-bit dHash (16 hex chars) for Duplicate Detection's image signal
    storage_ref: str | None = None         # where the accepted original is stored (see services/media/storage.py)
    reject_reason: str | None = None



class IncidentIntelligenceInput(BaseModel):
    request_id: str
    complaint_text: str | None = None
    selected_incident_location: Coordinates | None = None
    device_location: DeviceLocation | None = None
    image_refs: list[MediaReference] = Field(default_factory=list)
    image_exif_results: list[ImageMetadataResult] = Field(default_factory=list)  # server-generated
    voice_transcript: str | None = None
    location_check: LocationCheckSummary | None = None  # server-generated
    submitted_at: datetime  # server-generated
    taxonomy_version: str



# ---------------------------------------------------------------- model proposal
class ExtractedFact(BaseModel):
    fact: str = Field(min_length=1, max_length=300)
    source: FactSource = FactSource.COMPLAINT_TEXT


class GeminiIncidentProposal(BaseModel):
    """What the LLM may return. Enum-like fields stay strings here; the validator normalizes them."""
    incident_summary: str = Field(min_length=1, max_length=600)
    category: str
    incident_type: str
    severity_recommendation: str
    severity_reason: str = Field(default="", max_length=400)
    extracted_facts: list[ExtractedFact] = Field(default_factory=list, max_length=20)
    claimed_location_text: str | None = Field(default=None, max_length=300)
    claimed_time_text: str | None = Field(default=None, max_length=200)  # text as stated; never invented
    image_observations: list[str] = Field(default_factory=list, max_length=20)
    missing_information: list[str] = Field(default_factory=list, max_length=20)
    conflicting_information: list[str] = Field(default_factory=list, max_length=20)
    needs_clarification: bool = False
    clarification_questions: list[str] = Field(default_factory=list, max_length=5)


# ---------------------------------------------------------------- final record
class EvidenceReference(BaseModel):
    source: EvidenceSource
    ref_id: str | None = None
    note: str | None = None


class LocationEvidenceSummary(BaseModel):
    check: LocationCheckSummary
    reported_location_source: LocationSource | None = None
    device_location_available: bool = False
    images_with_gps: int = 0
    images_total: int = 0


class StructuredIncidentRecord(BaseModel):
    incident_id: str
    request_id: str
    incident_summary: str
    category: Category
    incident_type: IncidentType
    severity_recommendation: Severity
    severity_reason: str
    severity_rule_matches: list[str] = Field(default_factory=list)
    extracted_facts: list[ExtractedFact] = Field(default_factory=list)
    claimed_location_text: str | None = None
    claimed_time_text: str | None = None
    reported_incident_location: Coordinates | None = None
    location_evidence_summary: LocationEvidenceSummary
    image_observations: list[str] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)
    conflicting_information: list[str] = Field(default_factory=list)
    needs_clarification: bool = False
    clarification_questions: list[str] = Field(default_factory=list)
    evidence_provenance: list[EvidenceReference] = Field(default_factory=list)
    taxonomy_version: str
    prompt_version: str
    created_at: datetime  # server-generated
    # --- original inputs and raw evidence, preserved for audit and downstream agents (audit C-01/C-02/C-03).
    # Defaults keep records stored before this change loadable.
    complaint_text: str | None = None                 # citizen's original words, verbatim
    voice_transcript: str | None = None
    submitted_at: datetime | None = None              # server receipt time (before any processing)
    device_location: DeviceLocation | None = None     # as submitted; client-supplied, untrusted
    image_exif_results: list[ImageMetadataResult] = Field(default_factory=list)
    media: list[MediaReference] = Field(default_factory=list)
    request_fingerprint: str | None = None            # sha256 of the request payload, for idempotency checks
