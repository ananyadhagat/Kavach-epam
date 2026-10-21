from collections.abc import Callable

from fastapi import HTTPException

from app.db.database import UnitOfWork
from app.schemas.checklist import ChecklistStepUpdate
from app.schemas.worker_task import (
    TaskStatus,
)
from app.services.task_state_service import TaskStateService


class FieldWorkService:
    def __init__(
        self,
        unit_of_work: Callable[[], UnitOfWork],
        state_service: TaskStateService,
    ):
        self.unit_of_work = unit_of_work
        self.state_service = state_service

    async def list_tasks(self, worker_id: str):
        async with self.unit_of_work() as uow:
            return await uow.tasks.list_for_worker(worker_id)

    @staticmethod
    async def _get_task(uow: UnitOfWork, task_id: str, worker_id: str,
                        for_update: bool = False):
        task = await uow.tasks.get_for_worker(
            task_id, worker_id, for_update=for_update
        )

        if task is None:
            raise HTTPException(404, "Task not found.")

        return task

    async def get_task(self, task_id: str, worker_id: str):
        async with self.unit_of_work() as uow:
            return await self._get_task(uow, task_id, worker_id)

    async def _transition(self, task_id: str, worker_id: str,
                          new_status: TaskStatus, **options):
        async with self.unit_of_work() as uow:
            return await self.state_service.transition(
                uow.tasks, task_id, worker_id, new_status, **options
            )

    async def accept_task(self, task_id: str, worker_id: str):
        return await self._transition(task_id, worker_id, TaskStatus.ACCEPTED)

    async def reject_task(self, task_id: str, worker_id: str):
        return await self._transition(task_id, worker_id, TaskStatus.REJECTED)

    async def start_task(self, task_id: str, worker_id: str):
        # Kept for backward compatibility: starts an ACCEPTED task or
        # resumes a PAUSED one. The transition validator enforces this.
        async with self.unit_of_work() as uow:
            task = await self._get_task(uow, task_id, worker_id,
                                        for_update=True)

            if task.status not in {TaskStatus.ACCEPTED, TaskStatus.PAUSED}:
                raise HTTPException(
                    409,
                    "Task must be ACCEPTED or PAUSED before starting/resuming.",
                )

            return await self.state_service.transition(
                uow.tasks, task_id, worker_id, TaskStatus.IN_PROGRESS
            )

    async def resume_task(self, task_id: str, worker_id: str):
        return await self._transition(
            task_id,
            worker_id,
            TaskStatus.IN_PROGRESS,
            expected_status=TaskStatus.PAUSED,
        )

    async def pause_task(self, task_id: str, worker_id: str):
        return await self._transition(task_id, worker_id, TaskStatus.PAUSED)

    async def get_checklist(self, task_id: str, worker_id: str):
        async with self.unit_of_work() as uow:
            await self._get_task(uow, task_id, worker_id)
            return await uow.tasks.get_checklist_records(task_id)

    async def update_checklist(
        self,
        task_id: str,
        worker_id: str,
        step_id: str,
        payload: ChecklistStepUpdate,
    ):
        async with self.unit_of_work() as uow:
            # The row lock keeps the status check and the update consistent
            # with a concurrent pause or completion submission.
            task = await self._get_task(uow, task_id, worker_id,
                                        for_update=True)

            if task.status != TaskStatus.IN_PROGRESS:
                raise HTTPException(
                    409,
                    "Checklist updates require an IN_PROGRESS task.",
                )

            record = await uow.tasks.update_checklist(
                task_id,
                step_id,
                payload.status,
                payload.note,
            )

            if record is None:
                raise HTTPException(404, "Checklist step not found.")

        return {
            "task_id": task_id,
            "step_id": step_id,
            "status": record.status.value,
            "note": record.note,
            "updated_at": record.updated_at,
            "message": "Checklist updated successfully.",
        }
