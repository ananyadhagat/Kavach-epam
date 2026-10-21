from enum import Enum
from typing import Literal
from pydantic import BaseModel, Field

from ..contracts.v1 import CONTRACT_VERSION, ReasonCode


class VerificationStatus(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    INCONCLUSIVE = "INCONCLUSIVE"
    MANUAL_REVIEW = "MANUAL_REVIEW"


class ComponentFinding(BaseModel):
    status: str
    score: float | None = None
    reasons: list[str] = Field(default_factory=list)


class VerificationResponse(BaseModel):
    contract_version: Literal["1.1"] = CONTRACT_VERSION
    verification_id: str
    task_id: str
    submission_id: str
    verification_status: VerificationStatus
    verification_score: float | None
    score_status: Literal["AVAILABLE", "PARTIAL", "UNAVAILABLE"]
    score_breakdown: dict[str, float | None] | None
    image_findings: dict
    location_finding: ComponentFinding
    plan_compliance_findings: list[dict]
    remarks: list[str]
    requires_manual_review: bool
    rule_version: str
    vision_provider: Literal["mock", "gemini"] = "mock"
    vision_model_version: str
    vision_prompt_version: str
    evidence_refs: list[str]
    created_at: str
    reason_codes: list[ReasonCode]
    failed_requirement_ids: list[str]
