from typing import Any
from pydantic import BaseModel, ConfigDict, Field

from app.schemas.sanitation_request import SanitationPlanRequest


class PlanningContext(BaseModel):
    """Normalized planning context holding known facts, unknowns, and constraints."""

    model_config = ConfigDict(extra="ignore")

    incident_id: str
    complaint_id: str
    event_id: str
    category: str
    incident_type: str
    department: str
    priority: str
    supervisor_evaluation_status: str = "COMPLETED"
    supervisor_decision_status: str
    duplicate_processing_status: str = "COMPLETED"
    duplicate_retrieval_status: str = "COMPLETE"
    duplicate_decision: str
    routing_status: str
    routing: dict[str, Any]
    sla: dict[str, Any] | None = None
    action_plan_template_id: str | None = None
    action_plan_template_version: str | None = None
    action_plan_objective: str | None = None
    supervisor_required_actions: list[str] = Field(default_factory=list)
    supervisor_constraints: list[str] = Field(default_factory=list)

    # Physical / environmental measurements (tri-state: value, or None if unknown)
    estimated_waste_kg: float | None = None
    affected_area_sqm: float | None = None
    path_obstructed: bool | None = None
    hazard_detected: bool | None = None

    # Missing / quality flags
    missing_information: list[str] = Field(default_factory=list)
    conflicting_information: list[str] = Field(default_factory=list)
    needs_clarification: bool = False

    def is_fact_true(self, fact_name: str) -> bool:
        return getattr(self, fact_name, None) is True

    def is_fact_known(self, fact_name: str) -> bool:
        return getattr(self, fact_name, None) is not None


def build_planning_context(request: SanitationPlanRequest) -> PlanningContext:
    """Extract tri-state facts, unknowns, routing, and constraints from the canonical request."""
    inc = request.incident
    sup = request.supervisor_decision
    dup = request.duplicate_result

    sla_dict = sup.sla.model_dump() if sup.sla else None
    action_plan = sup.action_plan

    return PlanningContext(
        incident_id=inc.incident_id,
        complaint_id=inc.complaint_id,
        event_id=request.event_id,
        category=inc.category.strip().upper(),
        incident_type=inc.incident_type.strip().upper(),
        department=sup.department.strip().upper(),
        priority=(sup.priority.value if hasattr(sup.priority, "value") else str(sup.priority)).split(".")[-1].strip().upper(),
        supervisor_evaluation_status=getattr(sup, "evaluation_status", "COMPLETED").strip().upper(),
        supervisor_decision_status=sup.decision_status.value,
        duplicate_processing_status=getattr(dup, "processing_status", "COMPLETED").strip().upper(),
        duplicate_retrieval_status=getattr(getattr(dup, "retrieval", None), "status", "COMPLETE").strip().upper(),
        duplicate_decision=dup.decision.value,
        routing_status=sup.routing.status.strip().upper(),
        routing=sup.routing.model_dump(),
        sla=sla_dict,
        action_plan_template_id=action_plan.template_id if action_plan else None,
        action_plan_template_version=action_plan.template_version if action_plan else "1",
        action_plan_objective=action_plan.objective if action_plan else None,
        supervisor_required_actions=action_plan.required_actions if action_plan else [],
        supervisor_constraints=action_plan.constraints if action_plan else [],
        estimated_waste_kg=inc.estimated_waste_kg,
        affected_area_sqm=inc.affected_area_sqm,
        path_obstructed=inc.path_obstructed,
        hazard_detected=inc.hazard_detected,
        missing_information=inc.quality.missing_information,
        conflicting_information=inc.quality.conflicting_information,
        needs_clarification=inc.quality.needs_clarification,
    )
