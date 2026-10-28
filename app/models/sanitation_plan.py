from datetime import datetime
from typing import Any
from pydantic import BaseModel, ConfigDict, Field

from app.schemas.sanitation_response import (
    DurationEstimate,
    PlanningStatus,
    ResourceEstimate,
    SanitationPlanResult,
    TemplateReference,
)
from app.models.sanitation_plan_task import SanitationPlanTaskModel


class SanitationPlanModel(BaseModel):
    """In-memory domain model for a stored sanitation plan."""

    model_config = ConfigDict(extra="ignore")

    plan_id: str
    incident_id: str
    complaint_id: str
    supervisor_decision_id: str
    event_id: str
    planning_status: PlanningStatus
    dispatch_eligible: bool = False
    hold_reason_codes: list[str] = Field(default_factory=list)
    department: str = "SANITATION"
    priority: str = "MEDIUM"
    routing: dict[str, Any] = Field(default_factory=dict)
    template: TemplateReference | None = None
    objective: str | None = None
    tasks: list[SanitationPlanTaskModel] = Field(default_factory=list)
    resource_estimate: ResourceEstimate = Field(default_factory=ResourceEstimate)
    duration_estimate: DurationEstimate = Field(default_factory=DurationEstimate)
    safety_constraints: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    reason_codes: list[str] = Field(default_factory=list)
    policy_versions: dict[str, str] = Field(default_factory=dict)
    raw_result: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    previous_plan_id: str | None = None
    replan_reason: str | None = None
