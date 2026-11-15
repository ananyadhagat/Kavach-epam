from datetime import datetime
from enum import Enum
from pydantic import BaseModel, ConfigDict, Field, field_validator


class SupervisorDecisionStatus(str, Enum):
    APPROVED_TO_PROCEED = "APPROVED_TO_PROCEED"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    NEEDS_REVIEW = "NEEDS_REVIEW"


class RoutingInfo(BaseModel):
    """Routing resolution details from Module 03."""

    model_config = ConfigDict(extra="ignore")

    status: str = "RESOLVED"
    facility_id: str | None = None
    location_id: str | None = None
    ward_id: str | None = None
    queue_id: str | None = None


class SLAInfo(BaseModel):
    """SLA deadlines computed by Module 03."""

    model_config = ConfigDict(extra="ignore")

    status: str = "CALCULATED"
    policy_version: str = "sla-policy-1"
    rule_id: str = "SANITATION_DEFAULT"
    started_at: datetime
    response_due_at: datetime | None = None
    resolution_due_at: datetime | None = None

    @field_validator("started_at", "response_due_at", "resolution_due_at")
    @classmethod
    def validate_timezone(cls, v: datetime | None) -> datetime | None:
        if v is not None and (v.tzinfo is None or v.utcoffset() is None):
            raise ValueError("SLA timestamps must be timezone-aware")
        return v


class ActionPlan(BaseModel):
    """Supervisor-authorized action plan and template reference."""

    model_config = ConfigDict(extra="ignore")

    template_id: str
    template_version: str = "1"
    objective: str = ""
    required_actions: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)


class ApprovalInfo(BaseModel):
    """Supervisor human approval status."""

    model_config = ConfigDict(extra="ignore")

    required: bool = False
    status: str = "NOT_REQUIRED"


class SupervisorPolicyVersions(BaseModel):
    """Policy versions applied by Supervisor."""

    model_config = ConfigDict(extra="ignore")

    department: str = "department-policy-1"
    priority: str = "priority-policy-1"
    approval: str = "approval-policy-1"
    action_plan: str = "action-plan-policy-1"


class SupervisorDecision(BaseModel):
    """Module 03 Supervisor Decision upstream contract."""

    model_config = ConfigDict(extra="ignore")

    decision_id: str = Field(min_length=1)
    evaluation_status: str = "COMPLETED"
    decision_status: SupervisorDecisionStatus
    department: str = "SANITATION"
    priority: str = "MEDIUM"
    duplicate_decision: str = "NEW"
    linked_incident_id: str | None = None
    routing: RoutingInfo = Field(default_factory=RoutingInfo)
    sla: SLAInfo | None = None
    action_plan: ActionPlan | None = None
    approval: ApprovalInfo = Field(default_factory=ApprovalInfo)
    policy_versions: SupervisorPolicyVersions = Field(
        default_factory=SupervisorPolicyVersions
    )
