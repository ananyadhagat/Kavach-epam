from pydantic import BaseModel, Field, HttpUrl

from app.schemas.integration import ApprovalStatus
from app.schemas.sanitation import SanitationPriority


class SupervisorSanitationRequest(BaseModel):
    """Validated sanitation request received from the Supervisor Agent."""

    complaint_id: str = Field(min_length=1)
    description: str = Field(min_length=5)
    location: str = Field(min_length=1)
    priority: SanitationPriority
    estimated_waste_kg: float | None = Field(default=None, ge=0)
    approval_status: ApprovalStatus
    evidence_urls: list[HttpUrl] = Field(default_factory=list)
