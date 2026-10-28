from enum import Enum
from pydantic import BaseModel, ConfigDict, Field


class DuplicateDecision(str, Enum):
    NEW = "NEW"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    DUPLICATE = "DUPLICATE"


class DuplicateRetrieval(BaseModel):
    """Retrieval details from Module 02."""

    model_config = ConfigDict(extra="ignore")

    status: str = "COMPLETE"


class DuplicateResult(BaseModel):
    """Module 02 Duplicate Detection upstream contract."""

    model_config = ConfigDict(extra="ignore")

    processing_status: str = "COMPLETED"
    decision: DuplicateDecision
    matched_incident_id: str | None = None
    retrieval: DuplicateRetrieval = Field(default_factory=DuplicateRetrieval)
    policy_version: str = "duplicate-policy-1"
