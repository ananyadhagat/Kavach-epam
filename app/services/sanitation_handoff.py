from app.ai.sanitation_graph import sanitation_graph
from app.schemas.dispatch_contract import DispatchContract
from app.schemas.integration import ApprovalStatus
from app.schemas.sanitation import SanitationRequest
from app.schemas.supervisor_request import SupervisorSanitationRequest


def prepare_dispatch_contract(
    supervisor_request: SupervisorSanitationRequest,
) -> DispatchContract:
    """Prepare a proposed dispatch plan without assigning workers."""

    if supervisor_request.approval_status != ApprovalStatus.APPROVED:
        raise ValueError(
            "Sanitation planning handoff requires an approved complaint."
        )

    sanitation_request = SanitationRequest(
        complaint_id=supervisor_request.complaint_id,
        description=supervisor_request.description,
        location=supervisor_request.location,
        priority=supervisor_request.priority,
        estimated_waste_kg=supervisor_request.estimated_waste_kg,
    )

    result = sanitation_graph.invoke(
        {"request": sanitation_request.model_dump(mode="json")}
    )

    plan = result["plan"]

    return DispatchContract(
        complaint_id=plan["complaint_id"],
        location=supervisor_request.location,
        priority=supervisor_request.priority,
        tasks=plan["tasks"],
        safety_notes=plan["safety_notes"],
        approval_status=supervisor_request.approval_status,
        requires_human_review=True,
        planning_status="PROPOSED",
        resource_estimate=plan["resource_estimate"],
        duration_estimate=plan["duration_estimate"],
    )
