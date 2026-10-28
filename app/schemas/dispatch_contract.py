from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.integration import ApprovalStatus
from app.schemas.supervisor_contract import RoutingInfo


class DispatchContract(BaseModel):
    """Proposed sanitation work package; not a worker assignment."""

    model_config = ConfigDict(extra="ignore")

    plan_id: str = "SAN-PLAN-PROPOSED"
    incident_id: str = "INC-PROPOSED"
    complaint_id: str = Field(min_length=1)
    location: str = "UNSPECIFIED"
    department: str = "SANITATION"
    priority: Any = "MEDIUM"
    routing: RoutingInfo = Field(default_factory=RoutingInfo)
    tasks: list[Any] = Field(default_factory=list)
    safety_notes: list[str] = Field(default_factory=list)
    safety_constraints: list[str] = Field(default_factory=list)
    approval_status: ApprovalStatus = ApprovalStatus.APPROVED
    requires_human_review: bool = True
    planning_status: str = "PROPOSED"
    dispatch_eligible: bool = False
    resource_estimate: dict[str, Any] = Field(default_factory=dict)
    resource_demand: dict[str, Any] = Field(default_factory=dict)
    duration_estimate: dict[str, Any] = Field(default_factory=dict)
    assigned_worker_id: None = None
    assignment_status: Literal["UNASSIGNED"] = "UNASSIGNED"
    availability_confirmed: Literal[False] = False

    @model_validator(mode="after")
    def enforce_dispatch_safety(self):
        if self.dispatch_eligible:
            raise ValueError(
                "Dispatch eligibility cannot be enabled directly."
            )

        if not self.requires_human_review:
            raise ValueError(
                "Human review must remain enabled for proposed plans."
            )

        if self.planning_status != "PROPOSED":
            raise ValueError(
                "Sanitation planning may only produce PROPOSED plans."
            )

        if self.assigned_worker_id is not None:
            raise ValueError("Module 04 cannot assign workers.")

        if self.availability_confirmed is not False:
            raise ValueError("Module 04 cannot confirm resource availability.")

        return self


class DispatchWorkPackage(BaseModel):
    """Module 05 Dispatch Work Package.

    Represents a validated work package handed off to Module 05 Dispatch.
    Strict Module 04 boundary invariants:
      - Module 04 NEVER assigns workers (assigned_worker_id is None).
      - Module 04 NEVER confirms availability (availability_confirmed is False).
      - Module 04 NEVER starts or tracks execution (assignment_status is UNASSIGNED).
    """

    model_config = ConfigDict(extra="ignore")

    plan_id: str = "SAN-PLAN-PROPOSED"
    incident_id: str = "INC-PROPOSED"
    complaint_id: str = Field(min_length=1)
    location: str = "UNSPECIFIED"
    department: str = "SANITATION"
    priority: Any = "MEDIUM"
    routing: RoutingInfo = Field(default_factory=RoutingInfo)
    tasks: list[Any] = Field(default_factory=list)
    safety_notes: list[str] = Field(default_factory=list)
    safety_constraints: list[str] = Field(default_factory=list)
    approval_status: ApprovalStatus = ApprovalStatus.APPROVED
    requires_human_review: bool = True
    planning_status: str = "PROPOSED"
    dispatch_eligible: bool = True
    resource_estimate: dict[str, Any] = Field(default_factory=dict)
    resource_demand: dict[str, Any] = Field(default_factory=dict)
    duration_estimate: dict[str, Any] = Field(default_factory=dict)
    assigned_worker_id: None = None
    assignment_status: Literal["UNASSIGNED"] = "UNASSIGNED"
    availability_confirmed: Literal[False] = False

    @model_validator(mode="after")
    def enforce_module04_boundaries(self):
        if self.assigned_worker_id is not None:
            raise ValueError("Module 04 cannot assign workers.")

        if self.availability_confirmed is not False:
            raise ValueError("Module 04 cannot confirm resource availability.")

        if self.assignment_status != "UNASSIGNED":
            raise ValueError("Module 04 work package assignment status must remain UNASSIGNED.")

        return self
