from pydantic import BaseModel, Field

from app.schemas.integration import ApprovalStatus
from app.schemas.sanitation import SanitationPriority, SanitationTask


class DispatchContract(BaseModel):
    """Proposed sanitation work package for the Dispatch Agent."""

    complaint_id: str = Field(min_length=1)
    location: str = Field(min_length=1)
    priority: SanitationPriority
    tasks: list[SanitationTask] = Field(default_factory=list)
    safety_notes: list[str] = Field(default_factory=list)
    approval_status: ApprovalStatus
    requires_human_review: bool = True
    planning_status: str = "PROPOSED"
    resource_estimate: dict = Field(default_factory=dict)
    duration_estimate: dict = Field(default_factory=dict)
