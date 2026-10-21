from collections.abc import Callable
from uuid import uuid4

from fastapi import HTTPException

from app.config import settings
from app.db.database import UnitOfWork
from app.schemas.location_event import (
    LocationCaptureStatus,
    LocationEventCreate,
    LocationEventRecord,
    LocationEventType,
)
from app.schemas.worker_task import TaskStatus


class LocationCaptureService:
    def __init__(self, unit_of_work: Callable[[], UnitOfWork]):
        self.unit_of_work = unit_of_work

    async def capture(
        self,
        task_id: str,
        worker_id: str,
        payload: LocationEventCreate,
    ):
        # The event and the task reference are written in one transaction.
        async with self.unit_of_work() as uow:
            task = await uow.tasks.get_for_worker(
                task_id, worker_id, for_update=True
            )

            if task is None:
                raise HTTPException(404, "Task not found.")

            if payload.event_type == LocationEventType.ARRIVAL:
                if task.status not in {
                    TaskStatus.ACCEPTED,
                    TaskStatus.IN_PROGRESS,
                    TaskStatus.PAUSED,
                }:
                    raise HTTPException(
                        409,
                        "Arrival location cannot be recorded in this task state.",
                    )

            elif payload.event_type == LocationEventType.COMPLETION:
                if task.status not in {
                    TaskStatus.IN_PROGRESS,
                    TaskStatus.PAUSED,
                }:
                    raise HTTPException(
                        409,
                        "Completion location must be recorded during active work.",
                    )

            capture_status = payload.capture_status

            if (
                capture_status == LocationCaptureStatus.CAPTURED
                and payload.accuracy_meters is not None
                and payload.accuracy_meters > settings.max_gps_accuracy_meters
            ):
                capture_status = LocationCaptureStatus.INACCURATE

            record = LocationEventRecord(
                location_event_id=str(uuid4()),
                task_id=task_id,
                worker_id=worker_id,
                event_type=payload.event_type,
                capture_status=capture_status,
                latitude=(
                    payload.latitude
                    if capture_status == LocationCaptureStatus.CAPTURED
                    else None
                ),
                longitude=(
                    payload.longitude
                    if capture_status == LocationCaptureStatus.CAPTURED
                    else None
                ),
                accuracy_meters=payload.accuracy_meters,
                captured_at_device=payload.captured_at_device,
            )

            saved = await uow.locations.save(record)

            if payload.event_type == LocationEventType.ARRIVAL:
                await uow.tasks.set_task_references(
                    task_id,
                    arrival_location_event_id=saved.location_event_id,
                )
            else:
                await uow.tasks.set_task_references(
                    task_id,
                    completion_location_event_id=saved.location_event_id,
                )

            return saved
