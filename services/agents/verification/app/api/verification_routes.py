from fastapi import APIRouter, Depends, HTTPException, Request

from ..schemas import VerificationRequest, VerificationResponse
from ..adapters.agent_contracts import ContractAdapterError
from ..security import require_principal
from ..services.verification_service import UnknownSubmission, UnknownTask
from ..validators.evidence_validator import EvidenceTaskMismatch

router = APIRouter()


@router.post("/api/v1/tasks/{task_id}/verification", response_model=VerificationResponse)
def create_verification(task_id: str, body: VerificationRequest, request: Request,
                        _principal: dict = Depends(require_principal)) -> dict:
    service = request.app.state.verification_service
    try:
        return service.verify(task_id, body)
    except UnknownTask as exc:
        raise HTTPException(status_code=404, detail="Unknown task ID") from exc
    except UnknownSubmission as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except EvidenceTaskMismatch as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ContractAdapterError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
