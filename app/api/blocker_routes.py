import secrets

from fastapi import APIRouter, Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.api.worker_task_routes import _unauthorized, get_worker_id
from app.schemas.blocker import (
    BlockerReasonCodeOption,
    BlockerReasonCodesResponse,
    BlockerReport,
    BlockerResolution,
)
from app.services.blocker_service import (
    BlockerService,
    get_permitted_blocker_reason_codes,
)

worker_router = APIRouter(prefix="/worker/tasks", tags=["Task Blockers"])
reason_codes_router = APIRouter(
    prefix="/worker/blockers",
    tags=["Task Blockers"],
)
operator_router = APIRouter(prefix="/operator",
                            tags=["Dispatch/Supervisor Blocker Handling"])

operator_scheme = HTTPBearer(
    auto_error=False,
    scheme_name="OperatorBearer",
    description="Demo Dispatch/Supervisor token (local development only).",
)


def get_operator_id(
    credentials: HTTPAuthorizationCredentials | None = Depends(operator_scheme),
) -> str:
    # Demo authentication only, until the shared KAVACH identity contract
    # for Dispatch/Supervisor callers exists.
    from app.config import settings

    if settings.app_env == "production":
        raise _unauthorized("Demo authentication is disabled in production.")

    if credentials is None:
        raise _unauthorized()

    expected = settings.demo_operator_token.get_secret_value()

    if not secrets.compare_digest(
        credentials.credentials.encode("utf-8"),
        expected.encode("utf-8"),
    ):
        raise _unauthorized()

    return settings.demo_operator_id


def get_blocker_service(request: Request) -> BlockerService:
    return request.app.state.blocker_service


@reason_codes_router.get(
    "/reason-codes",
    response_model=BlockerReasonCodesResponse,
)
async def list_blocker_reason_codes(
    worker_id: str = Depends(get_worker_id),
) -> BlockerReasonCodesResponse:
    return BlockerReasonCodesResponse(
        reason_codes=[
            BlockerReasonCodeOption(code=code)
            for code in get_permitted_blocker_reason_codes()
        ]
    )


@worker_router.post("/{task_id}/blockers")
async def report_blocker(
    task_id: str,
    payload: BlockerReport,
    worker_id: str = Depends(get_worker_id),
    service: BlockerService = Depends(get_blocker_service),
):
    blocker, task = await service.report(task_id, worker_id, payload)
    return {
        "blocker": blocker,
        "task": task,
        "message": "Blocker reported; Dispatch must resolve it.",
    }


@worker_router.get("/{task_id}/blockers")
async def list_task_blockers(
    task_id: str,
    worker_id: str = Depends(get_worker_id),
    service: BlockerService = Depends(get_blocker_service),
):
    return {
        "task_id": task_id,
        "blockers": await service.list_for_task(task_id, worker_id),
    }


@operator_router.get("/blockers")
async def list_open_blockers(
    operator_id: str = Depends(get_operator_id),
    service: BlockerService = Depends(get_blocker_service),
):
    return {"blockers": await service.list_open()}


@operator_router.post("/tasks/{task_id}/unblock")
async def unblock_task(
    task_id: str,
    payload: BlockerResolution | None = None,
    operator_id: str = Depends(get_operator_id),
    service: BlockerService = Depends(get_blocker_service),
):
    blocker, task = await service.unblock(
        task_id, operator_id, payload or BlockerResolution()
    )
    return {
        "blocker": blocker,
        "task": task,
        "message": "Blocker resolved; task returned to its previous status.",
    }
