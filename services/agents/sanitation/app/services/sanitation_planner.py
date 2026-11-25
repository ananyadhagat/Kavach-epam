"""Backward compatibility layer for legacy planning calls."""

from app.schemas.sanitation_request import SanitationPlanRequest
from app.schemas.sanitation_response import SanitationPlanResult
from app.services.sanitation_planning_service import planning_service


def create_sanitation_plan(request: SanitationPlanRequest) -> SanitationPlanResult:
    """Delegate to deterministic SanitationPlanningService."""
    plan, _ = planning_service.create_plan(request)
    return plan
