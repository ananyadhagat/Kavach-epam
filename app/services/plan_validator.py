from app.policies.safety_rules import check_forbidden_operational_claims
from app.schemas.sanitation_response import PlanningStatus, SanitationPlanResult
from app.schemas.sanitation_task import SanitationTaskStatus


class PlanValidationError(Exception):
    """Raised when semantic plan validation fails."""

    def __init__(self, message: str, reason_codes: list[str] | None = None):
        super().__init__(message)
        self.reason_codes = reason_codes or ["PLAN_VALIDATION_FAILED"]


def validate_plan_result(plan: SanitationPlanResult) -> SanitationPlanResult:
    """Validate safety rules, operational invariants, and output consistency."""
    # 1. Check forbidden operational claims in text fields
    text_corpus = " ".join([
        plan.objective or "",
        *(t.title for t in plan.tasks),
        *(t.description for t in plan.tasks),
        *(c for t in plan.tasks for c in t.completion_criteria),
        *plan.safety_constraints,
        *plan.assumptions,
    ])

    violations = check_forbidden_operational_claims(text_corpus)
    if violations:
        raise PlanValidationError(
            f"Safety validation failed: plan text contains forbidden claims: {violations}",
            reason_codes=["SAFETY_VALIDATION_FAILED", "PLAN_VALIDATION_FAILED"],
        )

    # 2. Invariant: Every task must be NOT_STARTED
    for t in plan.tasks:
        if t.status != SanitationTaskStatus.NOT_STARTED:
            raise PlanValidationError(
                f"Task '{t.task_id}' has invalid status '{t.status}'. All planned tasks must be NOT_STARTED.",
                reason_codes=["PLAN_VALIDATION_FAILED"],
            )

    # 3. Invariant: availability_confirmed must be False
    if plan.resource_estimate.availability_confirmed is not False:
        raise PlanValidationError(
            "Resource availability cannot be confirmed by Module 04.",
            reason_codes=["AVAILABILITY_CONFIRMATION_FORBIDDEN", "PLAN_VALIDATION_FAILED"],
        )

    # 4. Invariant: Dispatch eligibility checks
    if plan.dispatch_eligible:
        if plan.hold_reason_codes:
            raise PlanValidationError(
                f"Plan with hold reason codes {plan.hold_reason_codes} cannot be dispatch-eligible.",
                reason_codes=["DISPATCH_ELIGIBILITY_INVALID", "PLAN_VALIDATION_FAILED"],
            )
        if plan.planning_status != PlanningStatus.PLAN_READY:
            raise PlanValidationError(
                f"Status '{plan.planning_status}' is not eligible for dispatch.",
                reason_codes=["DISPATCH_ELIGIBILITY_INVALID", "PLAN_VALIDATION_FAILED"],
            )
        if not plan.tasks:
            raise PlanValidationError(
                "Dispatch-eligible plan must contain at least one task.",
                reason_codes=["DISPATCH_ELIGIBILITY_INVALID", "PLAN_VALIDATION_FAILED"],
            )
        if plan.routing.status != "RESOLVED":
            raise PlanValidationError(
                "Routing must be RESOLVED for dispatch eligibility.",
                reason_codes=["ROUTING_UNRESOLVED", "PLAN_VALIDATION_FAILED"],
            )

    return plan
