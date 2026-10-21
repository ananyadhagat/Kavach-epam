"""Shared, versioned KAVACH contracts used at agent boundaries."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, model_validator


CONTRACT_VERSION = "1.1"


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    contract_version: Literal["1.1"] = CONTRACT_VERSION


class ReasonCode(str, Enum):
    MANDATORY_REQUIREMENT_CONTRADICTED = "MANDATORY_REQUIREMENT_CONTRADICTED"
    MANDATORY_REQUIREMENT_NOT_CLAIMED = "MANDATORY_REQUIREMENT_NOT_CLAIMED"
    GPS_MISMATCH = "GPS_MISMATCH"
    EVIDENCE_MISSING = "EVIDENCE_MISSING"
    ANALYSIS_UNAVAILABLE = "ANALYSIS_UNAVAILABLE"
    IMAGE_UNCERTAIN = "IMAGE_UNCERTAIN"
    SCORE_BELOW_THRESHOLD = "SCORE_BELOW_THRESHOLD"
    INTEGRATION_CONTRACT_INCOMPLETE = "INTEGRATION_CONTRACT_INCOMPLETE"
    IMAGE_BLURRY = "IMAGE_BLURRY"
    IMAGE_TOO_DARK = "IMAGE_TOO_DARK"
    IMAGE_TOO_BRIGHT = "IMAGE_TOO_BRIGHT"
    IMAGE_LOW_RESOLUTION = "IMAGE_LOW_RESOLUTION"
    BEFORE_AFTER_IDENTICAL = "BEFORE_AFTER_IDENTICAL"
    QUALITY_NOT_CHECKED = "QUALITY_NOT_CHECKED"


class EvidenceType(str, Enum):
    BEFORE = "BEFORE"
    AFTER = "AFTER"


class EvidenceUploadStatus(str, Enum):
    PENDING = "PENDING"
    STORED = "STORED"
    FAILED = "FAILED"


class LocationEventType(str, Enum):
    ARRIVAL = "ARRIVAL"
    COMPLETION = "COMPLETION"


class LocationCaptureStatus(str, Enum):
    CAPTURED = "CAPTURED"
    UNAVAILABLE = "UNAVAILABLE"
    INACCURATE = "INACCURATE"


class LocationStatus(str, Enum):
    CONSISTENT = "CONSISTENT"
    MISMATCH = "MISMATCH"
    INCONCLUSIVE = "INCONCLUSIVE"
    NOT_CHECKED = "NOT_CHECKED"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    UNAVAILABLE = "UNAVAILABLE"  # Compatibility status for a requested but missing event.


class Coordinates(ContractModel):
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)


class EvidenceRecord(ContractModel):
    evidence_id: str = Field(min_length=1)
    task_id: str = Field(min_length=1)
    submitted_by_worker_id: str | None = None
    evidence_type: EvidenceType
    storage_key: str | None = None
    validated_mime_type: str | None = None
    file_size_bytes: int | None = Field(default=None, ge=0)
    sha256: str | None = None
    uploaded_at_server: datetime | None = None
    upload_status: EvidenceUploadStatus

    @model_validator(mode="after")
    def stored_evidence_has_storage_reference(self):
        if self.upload_status == EvidenceUploadStatus.STORED and not self.storage_key:
            raise ValueError("STORED evidence requires a server storage_key")
        return self


class LocationEvent(ContractModel):
    location_event_id: str = Field(min_length=1)
    task_id: str = Field(min_length=1)
    worker_id: str | None = None
    source: str | None = None
    event_type: LocationEventType
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    accuracy_meters: float | None = Field(default=None, ge=0)
    captured_at_device: datetime | None = None
    received_at_server: datetime | None = None
    capture_status: LocationCaptureStatus

    @model_validator(mode="after")
    def captured_event_has_coordinates(self):
        if self.capture_status == LocationCaptureStatus.CAPTURED:
            if self.latitude is None or self.longitude is None:
                raise ValueError("CAPTURED location events require latitude and longitude")
        return self


class Requirement(ContractModel):
    """A task requirement whose ID and mandatory policy come from an owner."""
    requirement_id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    mandatory: bool
    target_observation: str | None = None


class FieldWorkerCompletion(ContractModel):
    task_id: str = Field(min_length=1)
    submission_id: str | None = Field(default=None, min_length=3, max_length=80)
    completion_note: str | None = None
    checklist_completed: list[str] = Field(
        default_factory=list,
        validation_alias=AliasChoices("checklist_completed", "checklist_step_ids"),
    )
    before_evidence_ids: list[str] = Field(default_factory=list)
    after_evidence_ids: list[str] = Field(default_factory=list)
    completion_location_event_id: str | None = None


class SanitationChecklistItem(ContractModel):
    task_id: str = Field(min_length=1)
    sequence: int = Field(ge=1)
    description: str = Field(min_length=1)
    depends_on: list[str] = Field(default_factory=list)
    required_resources: list[str] = Field(default_factory=list)
    completion_criteria: list[str] = Field(default_factory=list)
    status: str | None = None
    # These are optional upstream extensions. The adapter must flag their absence.
    requirement_id: str | None = None
    mandatory: bool | None = None
    target_observation: str | None = None


class SanitationLocation(ContractModel):
    site_id: str | None = None
    zone: str | None = None
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    tolerance_m: float | None = Field(default=None, gt=0)


class SanitationPlan(ContractModel):
    incident_id: str = Field(min_length=1)
    planning_status: str
    job_type: str | None = None
    location: SanitationLocation | None = None
    cleaning_plan: dict | None = None
    resources_required: dict | None = None
    estimated_time: dict | None = None
    task_checklist: list[SanitationChecklistItem] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class LocationCheckSummary(ContractModel):
    status: LocationStatus
    distance_meters: float | None = Field(default=None, ge=0)
    target_source: str | None = None
    evidence_sources: list[str] = Field(default_factory=list)
    reason_codes: list[str] = Field(default_factory=list)
    requires_human_review: bool = False
    warning: str | None = None


class DispatchAssignmentRequest(ContractModel):
    task_id: str
    incident_id: str
    required_workers: int = Field(ge=1)
    required_skills: list[str]
    location: Coordinates
    required_resources: list[str]
    estimated_task_duration_minutes: int = Field(ge=0)
    priority: Literal["LOW", "MEDIUM", "HIGH"]


class DuplicateDetectionRequest(ContractModel):
    complaint_id: str
    description: str
    category: str
    location: DuplicateLocation
    reported_at: datetime
    image_hash: str | None = None


class DuplicateLocation(ContractModel):
    facility_id: str | None = None
    location_id: str | None = None
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)


class DeviceLocation(ContractModel):
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    accuracy_meters: float | None = Field(default=None, ge=0)
    observed_at: datetime | None = None
    source: str = "DEVICE_GEOLOCATION"


class GeolocationRequest(ContractModel):
    description: str
    reported_location: ReportedLocation | None = None
    device_location: DeviceLocation | None = None
    media_ids: list[str] = Field(default_factory=list)


class ReportedLocation(ContractModel):
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    source: str = "USER_SELECTED_PIN"


class IncidentIntelligenceRequest(ContractModel):
    request_id: str
    complaint_text: str
    selected_incident_location: Coordinates | None = None
    device_location: DeviceLocation | None = None
    image_refs: list[dict] = Field(default_factory=list)
    image_exif_results: list[dict] = Field(default_factory=list)
    voice_transcript: str | None = None
    location_check: LocationCheckSummary | None = None
    submitted_at: datetime
    taxonomy_version: str


class SupervisorLocation(ContractModel):
    site_id: str | None = None
    zone: str | None = None


class SeverityIndicators(ContractModel):
    walking_path_obstructed: bool | None = None
    immediate_safety_risk: bool | None = None


class SupervisorEvaluationRequest(ContractModel):
    incident_id: str
    description: str
    category: str
    location: SupervisorLocation
    severity_indicators: SeverityIndicators
    evidence_complete: bool


class VerificationRequestV1(ContractModel):
    submission_id: str | None = Field(default=None, min_length=3, max_length=80)
    field_worker_completion: FieldWorkerCompletion | None = None

    @model_validator(mode="after")
    def requires_submission_reference(self):
        completion_id = self.field_worker_completion.submission_id if self.field_worker_completion else None
        if not self.submission_id and not completion_id:
            raise ValueError("submission_id is required for verification")
        if self.submission_id and completion_id and self.submission_id != completion_id:
            raise ValueError("submission_id must match the Field Worker completion")
        return self


class VerificationResponseV1(ContractModel):
    verification_id: str
    task_id: str
    submission_id: str
    verification_status: Literal["PASS", "FAIL", "INCONCLUSIVE", "MANUAL_REVIEW"]
    verification_score: float | None
    score_status: Literal["AVAILABLE", "PARTIAL", "UNAVAILABLE"]
    remarks: list[str]
    reason_codes: list[ReasonCode] = Field(default_factory=list)
    failed_requirement_ids: list[str] = Field(default_factory=list)


class StandardResponse(ContractModel):
    """Base for cross-agent responses; every response carries a contract version."""


DuplicateDetectionRequest.model_rebuild()
GeolocationRequest.model_rebuild()

