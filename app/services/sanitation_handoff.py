from datetime import datetime, timezone
from typing import Union

from app.schemas.dispatch_contract import DispatchWorkPackage
from app.schemas.duplicate_contract import DuplicateDecision, DuplicateResult
from app.schemas.incident_contract import IncidentRecord, LocationData
from app.schemas.integration import ApprovalStatus
from app.schemas.sanitation_request import SanitationPlanRequest
from app.schemas.sanitation_response import SanitationPlanResult
from app.schemas.supervisor_contract import (
    ActionPlan,
    RoutingInfo,
    SupervisorDecision,
    SupervisorDecisionStatus,
)
from app.schemas.supervisor_request import SupervisorSanitationRequest
from app.services.sanitation_planning_service import planning_service


def adapt_plan_to_dispatch(plan: SanitationPlanResult) -> DispatchWorkPackage:
    """Explicit boundary adapter from Module 04 Sanitation Plan to Module 05 Dispatch Contract.

    Crucial: Module 04 NEVER assigns workers or confirms availability.
    """
    if not plan.dispatch_eligible:
        raise ValueError(
            f"Plan '{plan.plan_id}' is not dispatch-eligible (status: {plan.planning_status.value}). "
            f"Hold reason codes: {plan.hold_reason_codes}"
        )

    return DispatchWorkPackage(
        plan_id=plan.plan_id,
        incident_id=plan.incident_id,
        complaint_id=plan.complaint_id,
        department=plan.department,
        priority=plan.priority,
        routing=plan.routing,
        tasks=plan.tasks,
        resource_demand=plan.resource_estimate.model_dump(),
        duration_estimate=plan.duration_estimate.model_dump(),
        safety_constraints=plan.safety_constraints,
        planning_status=plan.planning_status.value,
        dispatch_eligible=plan.dispatch_eligible,
        assigned_worker_id=None,
        assignment_status="UNASSIGNED",
        availability_confirmed=False,
    )


def prepare_dispatch_contract(
    supervisor_request: SupervisorSanitationRequest,
) -> DispatchWorkPackage:
    """Legacy boundary adapter from SupervisorSanitationRequest to DispatchContract."""
    if supervisor_request.approval_status != ApprovalStatus.APPROVED:
        raise ValueError("Sanitation planning handoff requires an approved complaint.")

    now = datetime(2026, 10, 26, 12, 0, 0, tzinfo=timezone.utc)
    canonical_request = SanitationPlanRequest(
        contract_version="1.0.0",
        event_id=f"evt-handoff-{supervisor_request.complaint_id}",
        incident=IncidentRecord(
            incident_id=f"INC-{supervisor_request.complaint_id}",
            complaint_id=supervisor_request.complaint_id,
            incident_summary=supervisor_request.description,
            complaint_text=supervisor_request.description,
            category="WASTE_OVERFLOW",
            incident_type="BIN_OVERFLOW",
            reported_at=now,
            location=LocationData(location_id=supervisor_request.location),
            estimated_waste_kg=supervisor_request.estimated_waste_kg,
        ),
        duplicate_result=DuplicateResult(
            processing_status="COMPLETED",
            decision=DuplicateDecision.NEW,
        ),
        supervisor_decision=SupervisorDecision(
            decision_id=f"SUP-{supervisor_request.complaint_id}",
            decision_status=SupervisorDecisionStatus.APPROVED_TO_PROCEED,
            department="SANITATION",
            priority=(supervisor_request.priority.value if hasattr(supervisor_request.priority, "value") else str(supervisor_request.priority)).upper(),
            routing=RoutingInfo(status="RESOLVED", location_id=supervisor_request.location),
            action_plan=ActionPlan(
                template_id="BIN_OVERFLOW_RESPONSE",
                template_version="1",
                objective="Resolve sanitation complaint",
            ),
        ),
    )

    plan, _ = planning_service.create_plan(canonical_request)

    return DispatchWorkPackage(
        plan_id=plan.plan_id,
        incident_id=plan.incident_id,
        complaint_id=plan.complaint_id,
        location=supervisor_request.location,
        department=plan.department,
        priority=plan.priority,
        routing=plan.routing,
        tasks=plan.tasks,
        resource_demand=plan.resource_estimate.model_dump(),
        duration_estimate=plan.duration_estimate.model_dump(),
        safety_constraints=plan.safety_constraints,
        planning_status="PROPOSED",
        dispatch_eligible=False,
        assigned_worker_id=None,
        assignment_status="UNASSIGNED",
        availability_confirmed=False,
    )
