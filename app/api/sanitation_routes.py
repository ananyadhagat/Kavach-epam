from fastapi import APIRouter, HTTPException
from pydantic import ValidationError

from app.ai.sanitation_graph import sanitation_graph
from app.schemas.dispatch_contract import DispatchContract
from app.schemas.integration import ApprovalStatus
from app.schemas.sanitation import SanitationPlan, SanitationRequest
from app.schemas.supervisor_request import SupervisorSanitationRequest
from app.services.sanitation_handoff import prepare_dispatch_contract

router = APIRouter(
    prefix="/api/v1/sanitation",
    tags=["Sanitation"],
)


@router.post("/plan", response_model=SanitationPlan)
def create_sanitation_plan(request: SanitationRequest) -> SanitationPlan:
    """Create a sanitation plan directly from a sanitation request."""
    try:
        result = sanitation_graph.invoke(
            {"request": request.model_dump(mode="json")}
        )
        return SanitationPlan.model_validate(result["plan"])

    except ValidationError as exc:
        raise HTTPException(
            status_code=422,
            detail="The generated plan failed validation.",
        ) from exc

    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail="The sanitation planning workflow failed.",
        ) from exc


@router.post("/handoff", response_model=DispatchContract)
def create_dispatch_handoff(
    request: SupervisorSanitationRequest,
) -> DispatchContract:
    """Prepare a proposed dispatch contract from an approved Supervisor request."""
    if request.approval_status != ApprovalStatus.APPROVED:
        raise HTTPException(
            status_code=403,
            detail="Only approved complaints can be handed off for dispatch planning.",
        )

    try:
        return prepare_dispatch_contract(request)

    except ValueError as exc:
        raise HTTPException(
            status_code=403,
            detail=str(exc),
        ) from exc

    except ValidationError as exc:
        raise HTTPException(
            status_code=422,
            detail="The dispatch contract failed validation.",
        ) from exc

    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail="The sanitation handoff workflow failed.",
        ) from exc
