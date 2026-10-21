import secrets

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.schemas.checklist import ChecklistStepUpdate
from app.schemas.completion import CompletionClaim
from app.schemas.worker_task import TaskActionRequest, TaskAction
from app.services.field_work_service import FieldWorkService
from app.services.completion_submission_service import (
    CompletionSubmissionService,
)

router = APIRouter(prefix="/worker/tasks", tags=["Worker Tasks"])

# Declared as a security scheme so Swagger UI shows "Authorize" and
# actually sends the header. OpenAPI ignores plain header parameters
# named "Authorization", which caused every Swagger request to fail.
bearer_scheme = HTTPBearer(
    auto_error=False,
    description="Demo worker token (local development only).",
)


def _unauthorized(detail: str = "Invalid authentication.") -> HTTPException:
    return HTTPException(
        status_code=401,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def get_worker_id(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> str:
    # Demo authentication only. Use a real JWT/OIDC provider in production.
    from app.config import settings

    if settings.app_env == "production":
        raise _unauthorized("Demo authentication is disabled in production.")

    # HTTPBearer returns None for a missing header, a non-Bearer scheme,
    # or an empty token.
    if credentials is None:
        raise _unauthorized()

    expected = settings.demo_worker_token.get_secret_value()

    if not secrets.compare_digest(
        credentials.credentials.encode("utf-8"),
        expected.encode("utf-8"),
    ):
        raise _unauthorized()

    return settings.demo_worker_id


def get_field_service(request: Request) -> FieldWorkService:
    return request.app.state.field_work_service


def get_completion_service(request: Request) -> CompletionSubmissionService:
    return request.app.state.completion_service


@router.get("")
async def list_worker_tasks(
    worker_id: str = Depends(get_worker_id),
    service: FieldWorkService = Depends(get_field_service),
):
    return {"tasks": await service.list_tasks(worker_id)}


@router.get("/{task_id}")
async def get_worker_task(
    task_id: str,
    worker_id: str = Depends(get_worker_id),
    service: FieldWorkService = Depends(get_field_service),
):
    return await service.get_task(task_id, worker_id)


@router.post("/{task_id}/accept")
async def accept_task(
    task_id: str,
    worker_id: str = Depends(get_worker_id),
    service: FieldWorkService = Depends(get_field_service),
):
    task = await service.accept_task(task_id, worker_id)
    return {"task": task, "message": "Task accepted."}


@router.post("/{task_id}/reject")
async def reject_task(
    task_id: str,
    payload: TaskActionRequest,
    worker_id: str = Depends(get_worker_id),
    service: FieldWorkService = Depends(get_field_service),
):
    if payload.action != TaskAction.REJECT:
        raise HTTPException(422, "Action must be REJECT.")

    task = await service.reject_task(task_id, worker_id)
    return {"task": task, "message": "Task rejected."}


@router.post("/{task_id}/start")
async def start_task(
    task_id: str,
    worker_id: str = Depends(get_worker_id),
    service: FieldWorkService = Depends(get_field_service),
):
    task = await service.start_task(task_id, worker_id)
    return {"task": task, "message": "Task started or resumed."}


@router.post("/{task_id}/resume")
async def resume_task(
    task_id: str,
    worker_id: str = Depends(get_worker_id),
    service: FieldWorkService = Depends(get_field_service),
):
    task = await service.resume_task(task_id, worker_id)
    return {"task": task, "message": "Task resumed."}


@router.post("/{task_id}/pause")
async def pause_task(
    task_id: str,
    worker_id: str = Depends(get_worker_id),
    service: FieldWorkService = Depends(get_field_service),
):
    task = await service.pause_task(task_id, worker_id)
    return {"task": task, "message": "Task paused."}


@router.get("/{task_id}/checklist")
async def get_checklist(
    task_id: str,
    worker_id: str = Depends(get_worker_id),
    service: FieldWorkService = Depends(get_field_service),
):
    return {
        "task_id": task_id,
        "steps": await service.get_checklist(task_id, worker_id),
    }


@router.patch("/{task_id}/checklist/{step_id}")
async def update_checklist(
    task_id: str,
    step_id: str,
    payload: ChecklistStepUpdate,
    worker_id: str = Depends(get_worker_id),
    service: FieldWorkService = Depends(get_field_service),
):
    return await service.update_checklist(
        task_id, worker_id, step_id, payload
    )


@router.post("/{task_id}/completion")
async def submit_completion(
    task_id: str,
    payload: CompletionClaim,
    idempotency_key: str = Header(alias="Idempotency-Key"),
    worker_id: str = Depends(get_worker_id),
    service: CompletionSubmissionService = Depends(get_completion_service),
):
    submission = await service.submit(
        task_id=task_id,
        worker_id=worker_id,
        idempotency_key=idempotency_key,
        claim=payload,
    )

    return {
        "submission": submission,
        "message": "Completion claim recorded for independent verification.",
    }
