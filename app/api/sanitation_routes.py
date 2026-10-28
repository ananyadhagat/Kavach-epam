import logging
from typing import Optional, Union
from fastapi import APIRouter, Header, HTTPException, status
from pydantic import ValidationError

from app.repositories.idempotency_repository import IdempotencyConflictError
from app.schemas.dispatch_contract import DispatchWorkPackage
from app.schemas.integration import ApprovalStatus
from app.schemas.sanitation_request import SanitationPlanRequest
from app.schemas.sanitation_response import SanitationPlanResult
from app.schemas.supervisor_request import SupervisorSanitationRequest
from app.services.plan_validator import PlanValidationError
from app.services.sanitation_handoff import adapt_plan_to_dispatch, prepare_dispatch_contract
from app.services.sanitation_planning_service import planning_service

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1/sanitation",
    tags=["Sanitation Planning"],
)


@router.post(
    "/plan",
    response_model=SanitationPlanResult,
    status_code=status.HTTP_200_OK,
    responses={
        200: {"description": "Sanitation plan created or retrieved via idempotency."},
        409: {"description": "Idempotency conflict."},
        422: {"description": "Malformed input or schema validation error."},
        503: {"description": "Service or repository unavailable."},
    },
)
def create_sanitation_plan(
    request: SanitationPlanRequest,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
) -> SanitationPlanResult:
    """Create a deterministic sanitation plan from upstream incident and supervisor decision."""
    try:
        plan, is_replay = planning_service.create_plan(
            request=request,
            idempotency_key=idempotency_key,
        )
        return plan

    except IdempotencyConflictError as exc:
        logger.warning("Idempotency conflict detected for key: %s", exc.key)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "Idempotency conflict",
                "reason_code": exc.reason_code,
                "message": str(exc),
            },
        )

    except PlanValidationError as exc:
        logger.error("Plan validation failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error": "Plan validation failure",
                "reason_codes": exc.reason_codes,
                "message": str(exc),
            },
        )

    except Exception as exc:
        logger.exception("Unexpected error during sanitation planning.")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unexpected sanitation planning error.",
        ) from exc


@router.get(
    "/plan/{plan_id}",
    response_model=SanitationPlanResult,
    status_code=status.HTTP_200_OK,
    responses={
        200: {"description": "Sanitation plan found."},
        404: {"description": "Plan not found."},
    },
)
def get_sanitation_plan(plan_id: str) -> SanitationPlanResult:
    """Retrieve an existing sanitation plan by its stable plan ID."""
    plan = planning_service.plan_repo.get_by_id(plan_id)
    if plan is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Plan '{plan_id}' not found.",
        )
    return plan


@router.get(
    "/plans/by-incident/{incident_id}",
    response_model=list[SanitationPlanResult],
    status_code=status.HTTP_200_OK,
    responses={
        200: {"description": "List of sanitation plans associated with the incident."},
    },
)
def get_sanitation_plans_by_incident(incident_id: str) -> list[SanitationPlanResult]:
    """Retrieve all sanitation plans associated with an incident ID."""
    return planning_service.plan_repo.get_by_incident_id(incident_id)


@router.post(
    "/handoff",
    response_model=DispatchWorkPackage,
    status_code=status.HTTP_200_OK,
    responses={
        200: {"description": "Dispatch work package prepared."},
        403: {"description": "Plan is not eligible for dispatch."},
        409: {"description": "Idempotency conflict."},
        422: {"description": "Malformed input."},
    },
)
def handoff_sanitation_plan(
    request: Union[SanitationPlanRequest, SupervisorSanitationRequest],
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
) -> DispatchWorkPackage:
    """Prepare a Module 05 Dispatch Work Package from an eligible plan or supervisor request."""
    if isinstance(request, SupervisorSanitationRequest):
        if request.approval_status != ApprovalStatus.APPROVED:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only approved complaints can be handed off for dispatch planning.",
            )
        try:
            return prepare_dispatch_contract(request)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=str(exc),
            ) from exc

    try:
        plan, _ = planning_service.create_plan(
            request=request,
            idempotency_key=idempotency_key,
        )

        if not plan.dispatch_eligible:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "error": "Plan not dispatch-eligible",
                    "plan_id": plan.plan_id,
                    "planning_status": plan.planning_status.value,
                    "hold_reason_codes": plan.hold_reason_codes,
                },
            )

        return adapt_plan_to_dispatch(plan)

    except IdempotencyConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "Idempotency conflict",
                "reason_code": exc.reason_code,
                "message": str(exc),
            },
        )

    except HTTPException:
        raise

    except Exception as exc:
        logger.exception("Unexpected error during sanitation handoff.")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unexpected sanitation handoff error.",
        ) from exc
