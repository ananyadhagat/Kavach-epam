from collections import defaultdict
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import Row, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ChecklistStepRow, TaskRow, WorkerRow
from app.schemas.checklist import ChecklistStatus, ChecklistStepRecord
from app.schemas.worker_task import (
    ChecklistDefinition,
    TaskLocation,
    TaskStatus,
    WorkerTask,
)

tasks_table = TaskRow.__table__
steps_table = ChecklistStepRow.__table__
workers_table = WorkerRow.__table__


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def parse_uuid(value: str | UUID | None) -> UUID | None:
    """Client-supplied IDs that are not UUIDs simply match nothing."""
    if value is None or isinstance(value, UUID):
        return value

    try:
        return UUID(str(value))
    except ValueError:
        return None


def uuid_str(value: UUID | None) -> str | None:
    return str(value) if value is not None else None


def _to_task(row: Row, steps: list[Row]) -> WorkerTask:
    return WorkerTask(
        task_id=row.task_id,
        incident_id=row.incident_id,
        assigned_worker_id=row.assigned_worker_id,
        title=row.title,
        description=row.description,
        priority=row.priority,
        status=row.status,
        location=TaskLocation(
            latitude=row.latitude,
            longitude=row.longitude,
            address=row.address,
        ),
        checklist=[
            ChecklistDefinition(
                step_id=step.step_id,
                title=step.title,
                required=step.required,
            )
            for step in steps
        ],
        created_at=row.created_at,
        updated_at=row.updated_at,
        arrival_location_event_id=uuid_str(row.arrival_location_event_id),
        completion_location_event_id=uuid_str(
            row.completion_location_event_id
        ),
        completion_submission_id=uuid_str(row.completion_submission_id),
    )


def _to_step_record(row: Row) -> ChecklistStepRecord:
    return ChecklistStepRecord(
        step_id=row.step_id,
        task_id=row.task_id,
        status=row.status,
        note=row.note,
        updated_at=row.updated_at,
    )


class TaskRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def add_worker(self, worker_id: str, display_name: str) -> None:
        await self.session.execute(
            pg_insert(workers_table)
            .values(worker_id=worker_id, display_name=display_name)
            .on_conflict_do_nothing(index_elements=["worker_id"])
        )

    async def worker_exists(self, worker_id: str) -> bool:
        found = await self.session.scalar(
            select(workers_table.c.worker_id).where(
                workers_table.c.worker_id == worker_id
            )
        )
        return found is not None

    async def task_exists(self, task_id: str) -> bool:
        found = await self.session.scalar(
            select(tasks_table.c.task_id).where(
                tasks_table.c.task_id == task_id
            )
        )
        return found is not None

    async def add_task(self, task: WorkerTask) -> WorkerTask:
        # Integration point for a future assignment engine.
        step_ids = [step.step_id for step in task.checklist]

        if len(set(step_ids)) != len(step_ids):
            raise ValueError("Checklist step IDs must be unique per task.")

        if await self.task_exists(task.task_id):
            raise ValueError(f"Task {task.task_id} already exists.")

        if not await self.worker_exists(task.assigned_worker_id):
            raise ValueError(
                f"Worker {task.assigned_worker_id} does not exist."
            )

        await self.session.execute(
            tasks_table.insert().values(
                task_id=task.task_id,
                incident_id=task.incident_id,
                assigned_worker_id=task.assigned_worker_id,
                title=task.title,
                description=task.description,
                priority=task.priority.value,
                status=task.status.value,
                latitude=task.location.latitude,
                longitude=task.location.longitude,
                address=task.location.address,
                created_at=task.created_at,
                updated_at=task.updated_at,
            )
        )

        if task.checklist:
            await self.session.execute(
                steps_table.insert(),
                [
                    {
                        "task_id": task.task_id,
                        "step_id": step.step_id,
                        "position": position,
                        "title": step.title,
                        "required": step.required,
                        "status": ChecklistStatus.PENDING.value,
                        "note": None,
                        "updated_at": task.created_at,
                    }
                    for position, step in enumerate(task.checklist)
                ],
            )

        return await self._get(task.task_id)

    async def _steps_for(self, task_ids: list[str]) -> dict[str, list[Row]]:
        grouped: dict[str, list[Row]] = defaultdict(list)

        if not task_ids:
            return grouped

        rows = await self.session.execute(
            select(steps_table)
            .where(steps_table.c.task_id.in_(task_ids))
            .order_by(steps_table.c.task_id, steps_table.c.position)
        )

        for row in rows:
            grouped[row.task_id].append(row)

        return grouped

    async def _to_tasks(self, rows: list[Row]) -> list[WorkerTask]:
        steps = await self._steps_for([row.task_id for row in rows])
        return [_to_task(row, steps[row.task_id]) for row in rows]

    async def _get(self, task_id: str) -> WorkerTask | None:
        row = (
            await self.session.execute(
                select(tasks_table).where(tasks_table.c.task_id == task_id)
            )
        ).first()

        return (await self._to_tasks([row]))[0] if row else None

    async def list_for_worker(self, worker_id: str) -> list[WorkerTask]:
        rows = (
            await self.session.execute(
                select(tasks_table)
                .where(tasks_table.c.assigned_worker_id == worker_id)
                .order_by(tasks_table.c.created_at, tasks_table.c.task_id)
            )
        ).all()

        return await self._to_tasks(rows)

    async def get_for_worker(
        self,
        task_id: str,
        worker_id: str,
        for_update: bool = False,
    ) -> WorkerTask | None:
        statement = select(tasks_table).where(
            tasks_table.c.task_id == task_id,
            tasks_table.c.assigned_worker_id == worker_id,
        )

        if for_update:
            # Row lock held until the surrounding transaction ends.
            statement = statement.with_for_update()

        row = (await self.session.execute(statement)).first()
        return (await self._to_tasks([row]))[0] if row else None

    async def update_status(
        self,
        task_id: str,
        worker_id: str,
        expected_status: TaskStatus,
        new_status: TaskStatus,
        completion_submission_id: str | None = None,
    ) -> WorkerTask | None:
        # Atomic compare-and-set. The submission reference is written in
        # the same statement so a COMPLETION_SUBMITTED task never lacks it.
        values = {"status": new_status.value, "updated_at": utc_now()}

        if completion_submission_id is not None:
            values["completion_submission_id"] = parse_uuid(
                completion_submission_id
            )

        row = (
            await self.session.execute(
                update(tasks_table)
                .where(
                    tasks_table.c.task_id == task_id,
                    tasks_table.c.assigned_worker_id == worker_id,
                    tasks_table.c.status == expected_status.value,
                )
                .values(**values)
                .returning(tasks_table)
            )
        ).first()

        return (await self._to_tasks([row]))[0] if row else None

    async def update_checklist(
        self,
        task_id: str,
        step_id: str,
        status: ChecklistStatus,
        note: str | None = None,
    ) -> ChecklistStepRecord | None:
        row = (
            await self.session.execute(
                update(steps_table)
                .where(
                    steps_table.c.task_id == task_id,
                    steps_table.c.step_id == step_id,
                )
                .values(status=status.value, note=note, updated_at=utc_now())
                .returning(steps_table)
            )
        ).first()

        return _to_step_record(row) if row else None

    async def get_checklist_records(
        self, task_id: str
    ) -> list[ChecklistStepRecord]:
        steps = await self._steps_for([task_id])
        return [_to_step_record(row) for row in steps[task_id]]

    async def get_checklist_states(self, task_id: str) -> dict[str, str]:
        return {
            record.step_id: record.status.value
            for record in await self.get_checklist_records(task_id)
        }

    async def set_task_references(
        self,
        task_id: str,
        arrival_location_event_id: str | None = None,
        completion_location_event_id: str | None = None,
    ) -> WorkerTask | None:
        values: dict = {"updated_at": utc_now()}

        if arrival_location_event_id is not None:
            values["arrival_location_event_id"] = parse_uuid(
                arrival_location_event_id
            )

        if completion_location_event_id is not None:
            values["completion_location_event_id"] = parse_uuid(
                completion_location_event_id
            )

        row = (
            await self.session.execute(
                update(tasks_table)
                .where(tasks_table.c.task_id == task_id)
                .values(**values)
                .returning(tasks_table)
            )
        ).first()

        return (await self._to_tasks([row]))[0] if row else None
