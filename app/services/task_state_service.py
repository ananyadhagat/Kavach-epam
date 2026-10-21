from fastapi import HTTPException, status

from app.repositories.task_repository import TaskRepository
from app.schemas.worker_task import TaskStatus, WorkerTask
from app.validators.task_transition_validator import (
    InvalidTaskTransition,
    validate_transition,
)


class TaskStateService:
    """Applies the task state machine inside the caller's transaction."""

    async def transition(
        self,
        tasks: TaskRepository,
        task_id: str,
        worker_id: str,
        new_status: TaskStatus,
        expected_status: TaskStatus | None = None,
        completion_submission_id: str | None = None,
    ) -> WorkerTask:
        task = await tasks.get_for_worker(task_id, worker_id)

        if task is None:
            raise HTTPException(
                status_code=404,
                detail="Task not found.",
            )

        # Lets callers such as "resume" require one specific source state.
        if expected_status is not None and task.status != expected_status:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"Task must be {expected_status.value}; "
                    f"current status is {task.status.value}."
                ),
            )

        try:
            validate_transition(task.status, new_status)
        except InvalidTaskTransition as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=str(exc),
            ) from exc

        updated = await tasks.update_status(
            task_id=task_id,
            worker_id=worker_id,
            expected_status=task.status,
            new_status=new_status,
            completion_submission_id=completion_submission_id,
        )

        if updated is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Task changed concurrently. Refresh and retry.",
            )

        return updated
