from datetime import datetime
from enum import Enum
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.sanitation_task import SanitationTask, SanitationTaskStatus
from app.schemas.supervisor_contract import RoutingInfo


class PlanningStatus(str, Enum):
    PLAN_READY = "PLAN_READY"
    PRELIMINARY_PLAN = "PRELIMINARY_PLAN"
    NEEDS_INFORMATION = "NEEDS_INFORMATION"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    BLOCKED = "BLOCKED"


class EstimateStatus(str, Enum):
    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"
    NEEDS_MORE_DATA = "NEEDS_MORE_DATA"


class DurationStatus(str, Enum):
    CALCULATED = "CALCULATED"
    RANGE_ESTIMATE = "RANGE_ESTIMATE"
    NEEDS_MORE_DATA = "NEEDS_MORE_DATA"


class ReasonCode(str, Enum):
    MISSING_INFORMATION = "MISSING_INFORMATION"
    INVALID_INPUT = "INVALID_INPUT"
    DUPLICATE_REVIEW_REQUIRED = "DUPLICATE_REVIEW_REQUIRED"
    SUPERVISOR_APPROVAL_REQUIRED = "SUPERVISOR_APPROVAL_REQUIRED"
    ROUTING_UNRESOLVED = "ROUTING_UNRESOLVED"
    TEMPLATE_UNAVAILABLE = "TEMPLATE_UNAVAILABLE"
    RESOURCE_DATA_INCOMPLETE = "RESOURCE_DATA_INCOMPLETE"
    DURATION_DATA_INCOMPLETE = "DURATION_DATA_INCOMPLETE"
    HUMAN_REVIEW_REQUIRED = "HUMAN_REVIEW_REQUIRED"


class TemplateReference(BaseModel):
    """Resolved template details."""

    model_config = ConfigDict(extra="ignore")

    template_id: str
    template_version: str = "1"
    policy_version: str = "sanitation-template-policy-1"


class WorkerDemand(BaseModel):
    """Estimated crew/worker demand; not an assignment."""

    model_config = ConfigDict(extra="forbid")

    count: int | None = Field(default=None, ge=1)
    roles: list[str] = Field(default_factory=list)
    basis: str = Field(default="CREW_RULE_NOT_CONFIGURED")


class ResourceEstimate(BaseModel):
    """Aggregated resource demand for the plan."""

    model_config = ConfigDict(extra="forbid")

    status: EstimateStatus = EstimateStatus.NEEDS_MORE_DATA
    required_resources: list[str] = Field(default_factory=list)
    estimated_worker_demand: WorkerDemand = Field(default_factory=WorkerDemand)
    availability_confirmed: Literal[False] = False
    resource_policy_version: str = "resource-policy-1"


class DurationEstimate(BaseModel):
    """Aggregated duration and SLA comparison."""

    model_config = ConfigDict(extra="forbid")

    status: DurationStatus = DurationStatus.NEEDS_MORE_DATA
    total_minutes: float | None = Field(default=None, ge=0)
    range_minutes: list[float] | None = None
    method: str = "DEPENDENCY_CRITICAL_PATH"
    basis: list[str] = Field(default_factory=list)
    sla_response_due_at: datetime | None = None
    sla_resolution_due_at: datetime | None = None


class SanitationPlanResult(BaseModel):
    """Proposed sanitation plan output contract (KAVACH Module 04)."""

    model_config = ConfigDict(extra="forbid")

    contract_version: Literal["1.0.0"] = "1.0.0"
    plan_id: str = Field(min_length=1)
    event_id: str = Field(min_length=1)
    incident_id: str = Field(min_length=1)
    complaint_id: str = Field(min_length=1)
    supervisor_decision_id: str = Field(min_length=1)
    planning_status: PlanningStatus
    dispatch_eligible: bool = False
    hold_reason_codes: list[str] = Field(default_factory=list)
    department: str = "SANITATION"
    priority: str = "MEDIUM"
    routing: RoutingInfo = Field(default_factory=RoutingInfo)
    template: TemplateReference | None = None
    objective: str | None = None
    tasks: list[SanitationTask] = Field(default_factory=list)
    resource_estimate: ResourceEstimate = Field(default_factory=ResourceEstimate)
    duration_estimate: DurationEstimate = Field(default_factory=DurationEstimate)
    safety_constraints: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    reason_codes: list[str] = Field(default_factory=list)
    policy_versions: dict[str, str] = Field(default_factory=dict)
    created_at: datetime
    previous_plan_id: str | None = None
    replan_reason: str | None = None

    @model_validator(mode="after")
    def validate_task_dependencies(self):
        task_ids = [t.task_id for t in self.tasks]
        if len(task_ids) != len(set(task_ids)):
            raise ValueError("Task IDs must be unique within a plan.")

        known = set(task_ids)
        for t in self.tasks:
            missing = set(t.depends_on) - known
            if missing:
                raise ValueError(
                    f"Task '{t.task_id}' references unknown dependencies: {sorted(missing)}"
                )

        dependencies = {t.task_id: t.depends_on for t in self.tasks}
        visiting = set()
        visited = set()

        def has_cycle(tid: str) -> bool:
            if tid in visiting:
                return True
            if tid in visited:
                return False
            visiting.add(tid)
            for dep in dependencies.get(tid, []):
                if has_cycle(dep):
                    return True
            visiting.remove(tid)
            visited.add(tid)
            return False

        for tid in dependencies:
            if has_cycle(tid):
                raise ValueError(f"Circular task dependency detected involving task '{tid}'.")

        return self

    @model_validator(mode="after")
    def validate_dispatch_and_status_invariants(self):
        if self.resource_estimate.availability_confirmed is not False:
            raise ValueError("Module 04 cannot confirm resource availability.")

        for t in self.tasks:
            if t.status != SanitationTaskStatus.NOT_STARTED:
                raise ValueError(
                    f"Planned task '{t.task_id}' has status '{t.status}', must be NOT_STARTED."
                )

        if self.dispatch_eligible:
            if self.hold_reason_codes:
                raise ValueError(
                    f"Plan with hold reason codes {self.hold_reason_codes} cannot be dispatch-eligible."
                )
            if self.planning_status != PlanningStatus.PLAN_READY:
                raise ValueError(
                    f"Plan with status '{self.planning_status}' cannot be dispatch-eligible. "
                    "Only PLAN_READY plans can be dispatch-eligible."
                )
            if not self.tasks:
                raise ValueError("Dispatch-eligible plan must contain at least one task.")
            if self.routing.status != "RESOLVED":
                raise ValueError("Dispatch-eligible plan requires RESOLVED routing.")

        if self.created_at.tzinfo is None or self.created_at.utcoffset() is None:
            raise ValueError("created_at timestamp must be timezone-aware.")

        return self


# Backward-compatible response models for test suite
class LegacyResourceEstimate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: EstimateStatus = EstimateStatus.NEEDS_MORE_DATA
    required_resources: list[str] = Field(default_factory=list)
    worker_count: int | None = Field(default=None, ge=1)
    availability_confirmed: bool = False


class LegacyDurationEstimate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: DurationStatus = DurationStatus.NEEDS_MORE_DATA
    estimated_minutes: int | None = Field(default=None, ge=0)
    minimum_minutes: int | None = Field(default=None, ge=0)
    maximum_minutes: int | None = Field(default=None, ge=0)


class SanitationResponse(BaseModel):
    """Legacy proposed sanitation plan response model."""

    model_config = ConfigDict(extra="forbid")

    contract_version: Literal["1.0.0"]
    request_id: str = Field(min_length=1)
    complaint_id: str = Field(min_length=1)
    planning_status: PlanningStatus
    tasks: list[SanitationTask] = Field(default_factory=list)
    resource_estimate: LegacyResourceEstimate = Field(default_factory=LegacyResourceEstimate)
    duration_estimate: LegacyDurationEstimate = Field(default_factory=LegacyDurationEstimate)
    reason_codes: list[ReasonCode] = Field(default_factory=list)
    requires_human_review: bool = True
    dispatch_eligible: bool = False

    @model_validator(mode="after")
    def validate_task_dependencies(self):
        task_ids = [t.task_id for t in self.tasks]
        if len(task_ids) != len(set(task_ids)):
            raise ValueError("Task IDs must be unique.")
        known = set(task_ids)
        for t in self.tasks:
            missing = set(t.depends_on) - known
            if missing:
                raise ValueError(f"Task '{t.task_id}' references unknown dependencies: {sorted(missing)}")
        deps = {t.task_id: t.depends_on for t in self.tasks}
        visiting, visited = set(), set()

        def has_cycle(tid: str) -> bool:
            if tid in visiting:
                return True
            if tid in visited:
                return False
            visiting.add(tid)
            for d in deps.get(tid, []):
                if has_cycle(d):
                    return True
            visiting.remove(tid)
            visited.add(tid)
            return False

        for tid in deps:
            if has_cycle(tid):
                raise ValueError("Circular task dependencies are not allowed.")
        return self

    @model_validator(mode="after")
    def enforce_dispatch_safety(self):
        if self.dispatch_eligible:
            raise ValueError("Dispatch eligibility requires a separately validated workflow.")
        if not self.requires_human_review:
            raise ValueError("Human review must remain enabled for proposed plans.")
        if self.resource_estimate.availability_confirmed:
            raise ValueError("Module 04 cannot confirm resource availability.")
        if any(t.status.value != "NOT_STARTED" for t in self.tasks):
            raise ValueError("Proposed tasks must remain NOT_STARTED.")
        return self
