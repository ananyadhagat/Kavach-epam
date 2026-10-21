from fastapi import APIRouter, Depends, File, Form, Request, UploadFile

from app.api.worker_task_routes import get_worker_id
from app.schemas.evidence import EvidenceType
from app.services.evidence_service import EvidenceService

router = APIRouter(prefix="/worker/tasks", tags=["Task Evidence"])


def get_evidence_service(request: Request) -> EvidenceService:
    return request.app.state.evidence_service


@router.post("/{task_id}/evidence")
async def upload_evidence(
    task_id: str,
    evidence_type: EvidenceType = Form(...),
    file: UploadFile = File(...),
    worker_id: str = Depends(get_worker_id),
    service: EvidenceService = Depends(get_evidence_service),
):
    evidence, duplicate = await service.upload(
        task_id=task_id,
        worker_id=worker_id,
        evidence_type=evidence_type,
        file=file,
    )

    return {
        "evidence": evidence,
        "duplicate": duplicate,
        "message": (
            "Existing evidence reused."
            if duplicate
            else "Image validated and stored."
        ),
    }