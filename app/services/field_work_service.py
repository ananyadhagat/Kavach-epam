from collections.abc import Callable

from fastapi import HTTPException

from app.config import settings
from app.db.database import UnitOfWork
from app.schemas.checklist import ChecklistStepUpdate
from app.schemas.worker_task import (
    TaskStatus,
    WorkerTaskDetailsResponse,
)
from app.schemas.location_event import (
    LocationCaptureStatus,
    LocationEventRecord,
    LocationEventSummary,
    LocationEventType,
)
from app.services.task_state_service import TaskStateService
from app.validators.start_validator import (
    StartPrerequisiteError,
    validate_start_prerequisites,
)


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
            task = await self._get_task(uow, task_id, worker_id)
            events = await uow.locations.latest_for_task(task_id)
            accepted_arrival = (
                await uow.locations.get(task.arrival_location_event_id)
                if task.arrival_location_event_id
                else None
            )
            accepted_completion = (
                await uow.locations.get(task.completion_location_event_id)
                if task.completion_location_event_id
                else None
            )
            latest_by_type: dict[LocationEventType, LocationEventRecord] = {}
            for event in events:
                latest_by_type[event.event_type] = event

            def summarize(
                event: LocationEventRecord | None,
                reference_id: str | None,
            ) -> LocationEventSummary | None:
                if event is None:
                    return None

                accepted_for_progress = (
                    event.capture_status == LocationCaptureStatus.CAPTURED
                    and event.location_event_id == reference_id
                )
                rejection_reason = None
                if event.capture_status == LocationCaptureStatus.INACCURATE:
                    rejection_reason = (
                        "Reported GPS accuracy exceeds the configured "
                        "acceptance threshold."
                    )
                elif event.capture_status == LocationCaptureStatus.UNAVAILABLE:
                    rejection_reason = (
                        "The device did not provide a usable GPS reading."
                    )

                return LocationEventSummary(
                    location_event_id=event.location_event_id,
                    event_type=event.event_type,
                    capture_status=event.capture_status,
                    latitude=event.latitude,
                    longitude=event.longitude,
                    accuracy_meters=event.accuracy_meters,
                    captured_at_device=event.captured_at_device,
                    received_at_server=event.received_at_server,
                    accepted_for_progress=accepted_for_progress,
                    rejection_reason=rejection_reason,
                )

            accepted_arrival_is_valid = (
                accepted_arrival is not None
                and accepted_arrival.task_id == task.task_id
                and accepted_arrival.worker_id == task.assigned_worker_id
                and accepted_arrival.event_type == LocationEventType.ARRIVAL
                and accepted_arrival.capture_status
                == LocationCaptureStatus.CAPTURED
            )
            accepted_completion_is_valid = (
                accepted_completion is not None
                and accepted_completion.task_id == task.task_id
                and accepted_completion.worker_id == task.assigned_worker_id
                and accepted_completion.event_type
                == LocationEventType.COMPLETION
                and accepted_completion.capture_status
                == LocationCaptureStatus.CAPTURED
            )

            return WorkerTaskDetailsResponse.model_validate(
                {
                    **task.model_dump(),
                    "accepted_arrival_location": (
                        summarize(
                            accepted_arrival,
                            task.arrival_location_event_id,
                        )
                        if accepted_arrival_is_valid
                        else None
                    ),
                    "latest_arrival_location": summarize(
                        latest_by_type.get(LocationEventType.ARRIVAL),
                        task.arrival_location_event_id,
                    ),
                    "latest_completion_location": summarize(
                        latest_by_type.get(LocationEventType.COMPLETION),
                        task.completion_location_event_id,
                    ),
                    "arrival_location_accepted": accepted_arrival_is_valid,
                    "completion_location_accepted":
                        accepted_completion_is_valid,
                    "gps_accuracy_threshold_meters": (
                        settings.max_gps_accuracy_meters
                    ),
                }
            )

    async def accept_task(self, task_id: str, worker_id: str):
        async with self.unit_of_work() as uow:
            await self._get_task(uow, task_id, worker_id, for_update=True)
            return await self.state_service.transition(
                uow.tasks,
                task_id,
                worker_id,
                TaskStatus.ACCEPTED,
                expected_status=TaskStatus.ASSIGNED,
            )

    async def reject_task(self, task_id: str, worker_id: str, reason: str):
        async with self.unit_of_work() as uow:
            await self._get_task(uow, task_id, worker_id, for_update=True)
            task = await self.state_service.transition(
                uow.tasks,
                task_id,
                worker_id,
                TaskStatus.REJECTED,
                expected_status=TaskStatus.ASSIGNED,
            )
            rejected_at = await uow.tasks.record_rejection(
                task_id, worker_id, reason
            )

        return task, rejected_at

    async def _transition(self, task_id: str, worker_id: str,
                          new_status: TaskStatus, **options):
        async with self.unit_of_work() as uow:
            return await self.state_service.transition(
                uow.tasks, task_id, worker_id, new_status, **options
            )

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

            # A first start needs a stored BEFORE image and a captured
            # arrival location. Resuming a PAUSED task does not repeat this.
            # The row lock serialises the check with concurrent uploads.
            if task.status == TaskStatus.ACCEPTED:
                arrival = (
                    await uow.locations.get(task.arrival_location_event_id)
                    if task.arrival_location_event_id else None
                )

                try:
                    validate_start_prerequisites(
                        task, await uow.evidence.list_for_task(task_id),
                        arrival,
                    )
                except StartPrerequisiteError as exc:
                    raise HTTPException(422, str(exc)) from exc

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

            step = next((s for s in task.checklist if s.step_id == step_id),
                        None)

            if step is None:
                raise HTTPException(404, "Checklist step not found.")

            if step.assigned_worker_id != worker_id:
                raise HTTPException(
                    403, "Checklist step is assigned to another worker."
                )

            # Reopening a step after AFTER evidence is allowed; completion
            # then requires a new AFTER image (see validate_completion).
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
            "completed_at": record.completed_at,
            "message": "Checklist updated successfully.",
        }
