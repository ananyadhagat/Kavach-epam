from app.schemas.duplicate_contract import DuplicateDecision
from app.schemas.sanitation_response import PlanningStatus
from app.schemas.supervisor_contract import SupervisorDecisionStatus
from app.services.context_builder import PlanningContext


def evaluate_dispatch_eligibility(
    planning_status: PlanningStatus,
    context: PlanningContext,
    template_enabled: bool,
    hold_reason_codes: list[str],
) -> bool:
    """Determine whether the sanitation plan is eligible for handoff to Module 05 Dispatch.

    Rules:
    - Supervisor decision must be APPROVED_TO_PROCEED.
    - Duplicate decision must be NEW.
    - Routing must be RESOLVED.
    - Template must be enabled and matched.
    - Planning status must be PLAN_READY.
    - No hold reason codes may be present.
    """
    if hold_reason_codes:
        return False

    if context.supervisor_decision_status != SupervisorDecisionStatus.APPROVED_TO_PROCEED.value:
        return False

    if context.duplicate_decision != DuplicateDecision.NEW.value:
        return False

    if context.routing_status != "RESOLVED":
        return False

    if not template_enabled:
        return False

    if planning_status != PlanningStatus.PLAN_READY:
        # Preliminary or review plans are not dispatch eligible by default
        return False

    return True
