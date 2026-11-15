# src/kavach/schemas/supervisor.py
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class PriorityLevel(str, Enum):
    P1 = "P1"
    P2 = "P2"
    P3 = "P3"
    P4 = "P4"


PRIORITY_RANK: dict[PriorityLevel, int] = {
    PriorityLevel.P1: 1,
    PriorityLevel.P2: 2,
    PriorityLevel.P3: 3,
    PriorityLevel.P4: 4,
}


def most_severe(a: PriorityLevel, b: PriorityLevel) -> PriorityLevel:
    """P1 is the most severe. Returns the more severe of the two."""
    return a if PRIORITY_RANK[a] <= PRIORITY_RANK[b] else b


class DecisionStatus(str, Enum):
    APPROVED_TO_PROCEED = "APPROVED_TO_PROCEED"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    NEEDS_REVIEW = "NEEDS_REVIEW"


class ApprovalStatus(str, Enum):
    # APPROVED / REJECTED are set by humans in a later phase and are not produced here.
    NOT_REQUIRED = "NOT_REQUIRED"
    PENDING = "PENDING"
    NOT_APPLICABLE = "NOT_APPLICABLE"


# Agent 1 severity labels (or P1-P4 strings) -> canonical priority
SEVERITY_TO_PRIORITY_MAP: dict[str, PriorityLevel] = {
    "CRITICAL": PriorityLevel.P1,
    "P1": PriorityLevel.P1,
    "HIGH": PriorityLevel.P2,
    "P2": PriorityLevel.P2,
    "MEDIUM": PriorityLevel.P3,
    "MODERATE": PriorityLevel.P3,
    "P3": PriorityLevel.P3,
    "LOW": PriorityLevel.P4,
    "MINOR": PriorityLevel.P4,
    "P4": PriorityLevel.P4,
}


class IncidentLocationInput(BaseModel):
    model_config = ConfigDict(extra="ignore")

    latitude: Optional[float] = Field(default=None, ge=-90.0, le=90.0)
    longitude: Optional[float] = Field(default=None, ge=-180.0, le=180.0)
    locality: Optional[str] = Field(default=None, max_length=512)
    ward_hint: Optional[str] = Field(default=None, max_length=128)
    verification_status: str = Field(default="VERIFIED", max_length=64)


class IncidentEvidenceInput(BaseModel):
    model_config = ConfigDict(extra="ignore")

    evidence_id: Optional[UUID] = None
    media_reference: Optional[str] = None
    file_hash: Optional[str] = None
    evidence_type: str = Field(default="IMAGE", max_length=64)
    location_metadata: Optional[str] = None


class DuplicateCandidateInput(BaseModel):
    """Mirrors Duplicate_Candidate in the ER diagram."""

    model_config = ConfigDict(extra="ignore")

    matched_incident_id: Optional[UUID] = None
    similarity_score: float = Field(default=0.0, ge=0.0, le=1.0)
    reason_codes: Optional[Any] = None


class DuplicateCheckInput(BaseModel):
    """Mirrors Duplicate_Check in the ER diagram (result from process 2.0)."""

    model_config = ConfigDict(extra="ignore")

    check_id: Optional[UUID] = None
    decision: str = Field(..., min_length=1, max_length=64)  # NEW | DUPLICATE | REVIEW_REQUIRED
    processing_status: str = Field(..., min_length=1, max_length=64)
    policy_version: Optional[str] = None
    checked_at: Optional[datetime] = None
    candidates: list[DuplicateCandidateInput] = Field(default_factory=list)


class SupervisorIncidentInput(BaseModel):
    """
    Canonical JSON input for the Supervisor Agent.
    Accepts flat Incident JSON or the nested StructuredIncidentRecord from Agent 1.
    """

    model_config = ConfigDict(extra="ignore")

    incident_id: UUID = Field(default_factory=uuid4)
    citizen_id: Optional[UUID] = None
    description: str = Field(..., min_length=1, max_length=4000)
    category: str = Field(..., min_length=1, max_length=128)
    incident_type: str = Field(..., min_length=1, max_length=128)
    severity: str = Field(..., min_length=1, max_length=64)
    reported_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    incident_status: str = Field(default="OPEN", max_length=64)
    location_metadata: IncidentLocationInput = Field(default_factory=IncidentLocationInput)
    evidence: list[IncidentEvidenceInput] = Field(default_factory=list)
    duplicate_check_id: Optional[UUID] = None
    duplicate_check: Optional[DuplicateCheckInput] = None

    @model_validator(mode="before")
    @classmethod
    def adapt_nested_agent1_payload(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data

        adapted = dict(data)

        classification = adapted.get("classification")
        if isinstance(classification, dict):
            adapted.setdefault("category", classification.get("category"))
            adapted.setdefault("incident_type", classification.get("incident_type"))
            if not adapted.get("description") and classification.get("Normalized_summary"):
                adapted["description"] = classification.get("Normalized_summary")

        intake = adapted.get("intake")
        if isinstance(intake, dict) and not adapted.get("description"):
            adapted["description"] = (
                intake.get("complaint_text") or intake.get("voice_transcript") or ""
            )

        severity_block = adapted.get("severity_assessment")
        if isinstance(severity_block, dict):
            adapted.setdefault(
                "severity",
                severity_block.get("final_severity")
                or severity_block.get("priority")
                or severity_block.get("severity"),
            )

        if "severity" not in adapted and "priority" in adapted:
            adapted["severity"] = adapted["priority"]

        if "location_metadata" not in adapted and isinstance(adapted.get("location"), dict):
            loc = adapted["location"]
            pin = loc.get("citizen_pin") or loc.get("resolved_coordinates") or {}
            adapted["location_metadata"] = {
                "latitude": loc.get("latitude", pin.get("latitude")),
                "longitude": loc.get("longitude", pin.get("longitude")),
                "locality": loc.get("locality") or loc.get("address_text"),
                "verification_status": loc.get("verification_status", "VERIFIED"),
            }

        if "reported_at" not in adapted and "created_at" in adapted:
            adapted["reported_at"] = adapted["created_at"]

        # Accept top-level duplicate_candidates and fold them into duplicate_check
        dc = adapted.get("duplicate_check")
        top_candidates = adapted.get("duplicate_candidates")
        if isinstance(dc, dict) and isinstance(top_candidates, list) and not dc.get("candidates"):
            dc = dict(dc)
            dc["candidates"] = top_candidates
            adapted["duplicate_check"] = dc

        return adapted

    @field_validator("reported_at", mode="after")
    @classmethod
    def ensure_timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    @model_validator(mode="after")
    def link_duplicate_check_id(self) -> "SupervisorIncidentInput":
        if self.duplicate_check_id is None and self.duplicate_check is not None:
            self.duplicate_check_id = self.duplicate_check.check_id
        return self

    @property
    def resolved_priority(self) -> Optional[PriorityLevel]:
        return SEVERITY_TO_PRIORITY_MAP.get(self.severity.strip().upper())


class GeminiSupervisorSuggestion(BaseModel):
    """
    Advisory output requested from Gemini.
    Gemini NEVER sets deadlines, approval status, or decision status.
    Its suggested_priority can only RAISE the priority (enforced in code).
    """

    model_config = ConfigDict(extra="ignore")

    department: str = Field(..., min_length=1, max_length=128)
    ward_or_route: str = Field(..., min_length=1, max_length=128)
    suggested_priority: PriorityLevel
    reason_codes: list[str] = Field(default_factory=list, max_length=10)
    rationale: str = Field(..., min_length=5, max_length=1000)


class LlmResponseRecord(BaseModel):
    """What happened with the LLM call. Shown in the output so Gemini's answer is always visible."""

    model_config = ConfigDict(extra="forbid")

    mode: str                                   # "gemini" or "mock"
    model: Optional[str] = None                 # model name (gemini mode only)
    called: bool                                # True only if a real API request was sent
    skipped_reason: Optional[str] = None        # e.g. HARD_GATE_FAILED, MOCK_MODE_NO_API_CALL
    raw_text: Optional[str] = None              # exact text returned by Gemini
    parsed_suggestion: Optional[GeminiSupervisorSuggestion] = None  # Gemini's answer after parsing
    error: Optional[str] = None                 # error class if the call or parsing failed


class SupervisorDecisionRecord(BaseModel):
    """Maps 1-to-1 with the Supervisor_Decision table (D3) in the ER diagram."""

    model_config = ConfigDict(extra="forbid")

    decision_id: UUID = Field(default_factory=uuid4)
    incident_id: UUID
    duplicate_check_id: Optional[UUID] = None
    department: Optional[str] = None
    priority: PriorityLevel
    ward_or_route: Optional[str] = None
    response_deadline: Optional[datetime] = None
    resolution_deadline: Optional[datetime] = None
    decision_status: DecisionStatus
    approval_status: ApprovalStatus
    policy_version: str


class RoutingDirective(BaseModel):
    model_config = ConfigDict(extra="forbid")

    next_process: str
    dispatch_eligible: bool


class AuditLogRecord(BaseModel):
    """Maps 1-to-1 with the Audit_Log table in the ER diagram."""

    model_config = ConfigDict(extra="forbid")

    audit_id: UUID = Field(default_factory=uuid4)
    entity_type: str = "SUPERVISOR_DECISION"
    entity_id: UUID
    actor: str
    action: str
    reason_codes: list[str]
    rationale: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class SupervisorEvaluationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    supervisor_decision: SupervisorDecisionRecord
    routing: RoutingDirective
    audit: AuditLogRecord
    llm_response: Optional[LlmResponseRecord] = None
