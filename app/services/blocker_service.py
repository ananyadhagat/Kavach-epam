from collections.abc import Callable
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import HTTPException

from app.config import settings, validate_blocker_reason_codes
from app.db.database import UnitOfWork
from app.schemas.blocker import BlockerRecord, BlockerReport, BlockerResolution
from app.schemas.checklist import ChecklistStatus
from app.schemas.worker_task import TaskStatus
from app.services.task_state_service import TaskStateService

BLOCKABLE_STATES = {
    TaskStatus.ACCEPTED,
    TaskStatus.IN_PROGRESS,
    TaskStatus.PAUSED,
}


def get_permitted_blocker_reason_codes() -> tuple[str, ...]:
    if (
        settings.app_env == "production"
        and not settings.blocker_reason_codes_approved
    ):
        raise HTTPException(
            503,
            "Production blocker reporting is disabled until an approved "
            "BLOCKER_REASON_CODES list is configured and "
            "BLOCKER_REASON_CODES_APPROVED is true.",
        )

    codes = settings.blocker_reason_codes
    if not codes:
        raise HTTPException(
            503,
            "Blocker reason codes are not configured. Set "
            "BLOCKER_REASON_CODES to the agreed list.",
        )

    try:
        return validate_blocker_reason_codes(codes)
    except ValueError as exc:
        raise HTTPException(
            503,
            "Blocker reason code configuration is invalid.",
        ) from exc


class BlockerService:
    """Worker blocker reports and their resolution by Dispatch/Supervisor."""

    def __init__(
        self,
        unit_of_work: Callable[[], UnitOfWork],
        state_service: TaskStateService,
    ):
        self.unit_of_work = unit_of_work
        self.state_service = state_service

    async def report(self, task_id: str, worker_id: str,
                     payload: BlockerReport):
        codes = get_permitted_blocker_reason_codes()

        if payload.reason_code not in codes:
            raise HTTPException(
                422,
                f"Invalid blocker reason code: {payload.reason_code}. "
                "Use a code from the configured BLOCKER_REASON_CODES list.",
            )

        async with self.unit_of_work() as uow:
            task = await uow.tasks.get_for_worker(task_id, worker_id,
                                                  for_update=True)

            if task is None:
                raise HTTPException(404, "Task not found.")

            if task.status == TaskStatus.BLOCKED:
                raise HTTPException(
                    409,
                    "Task is already blocked; the open blocker must be "
                    "resolved by Dispatch or a Supervisor.",
                )

            if task.status not in BLOCKABLE_STATES:
                raise HTTPException(
                    409, "A blocker cannot be reported in this task state."
                )

            if payload.step_id is not None:
                step = next((s for s in task.checklist
                             if s.step_id == payload.step_id), None)

                if step is None:
                    raise HTTPException(404, "Checklist step not found.")

                if step.assigned_worker_id != worker_id:
                    raise HTTPException(
                        403, "Checklist step is assigned to another worker."
                    )

                await uow.tasks.update_checklist(
                    task_id, payload.step_id, ChecklistStatus.BLOCKED,
                    payload.description,
                )

            blocker = await uow.blockers.create(BlockerRecord(
                blocker_id=str(uuid4()),
                task_id=task_id,
                worker_id=worker_id,
                step_id=payload.step_id,
                reason_code=payload.reason_code,
                description=payload.description,
                previous_status=task.status,
            ))

            updated = await self.state_service.transition(
                uow.tasks, task_id, worker_id, TaskStatus.BLOCKED
            )

        return blocker, updated

    async def list_for_task(self, task_id: str, worker_id: str):
        async with self.unit_of_work() as uow:
            if await uow.tasks.get_for_worker(task_id, worker_id) is None:
                raise HTTPException(404, "Task not found.")

            return await uow.blockers.list_for_task(task_id)

    async def list_open(self):
        async with self.unit_of_work() as uow:
            return await uow.blockers.list_open()

    async def unblock(self, task_id: str, operator_id: str,
                      payload: BlockerResolution):
        async with self.unit_of_work() as uow:
            task = await uow.tasks.get(task_id, for_update=True)

            if task is None:
                raise HTTPException(404, "Task not found.")

            if task.status != TaskStatus.BLOCKED:
                raise HTTPException(409, "Task is not blocked.")

            blocker = await uow.blockers.get_open_for_task(task_id)

            if blocker is None:
                raise HTTPException(409, "Task has no open blocker.")

            resolved = await uow.blockers.resolve(
                blocker.blocker_id,
                resolved_by=operator_id,
                resolved_at=datetime.now(timezone.utc),
                resolution_note=payload.resolution_note,
            )

            # Back to the status the task had when it was blocked.
            updated = await self.state_service.transition(
                uow.tasks, task_id, task.assigned_worker_id,
                blocker.previous_status, unblock=True,
            )

        return resolved, updated
