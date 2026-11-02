from datetime import datetime

from sqlalchemy import Row, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import TaskBlockerRow
from app.repositories.task_repository import parse_uuid
from app.schemas.blocker import BlockerRecord, BlockerStatus

blockers_table = TaskBlockerRow.__table__


def _to_record(row: Row) -> BlockerRecord:
    return BlockerRecord(
        blocker_id=str(row.blocker_id),
        task_id=row.task_id,
        worker_id=row.worker_id,
        step_id=row.step_id,
        reason_code=row.reason_code,
        description=row.description,
        status=row.status,
        previous_status=row.previous_status,
        reported_at=row.reported_at,
        resolved_at=row.resolved_at,
        resolved_by=row.resolved_by,
        resolution_note=row.resolution_note,
    )


class BlockerRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, record: BlockerRecord) -> BlockerRecord:
        row = (
            await self.session.execute(
                blockers_table.insert()
                .values(
                    blocker_id=parse_uuid(record.blocker_id),
                    task_id=record.task_id,
                    worker_id=record.worker_id,
                    step_id=record.step_id,
                    reason_code=record.reason_code,
                    description=record.description,
                    status=record.status.value,
                    previous_status=record.previous_status.value,
                    reported_at=record.reported_at,
                )
                .returning(blockers_table)
            )
        ).first()

        return _to_record(row)

    async def get_open_for_task(self, task_id: str) -> BlockerRecord | None:
        row = (
            await self.session.execute(
                select(blockers_table).where(
                    blockers_table.c.task_id == task_id,
                    blockers_table.c.status == BlockerStatus.OPEN.value,
                )
            )
        ).first()

        return _to_record(row) if row else None

    async def list_for_task(self, task_id: str) -> list[BlockerRecord]:
        rows = await self.session.execute(
            select(blockers_table)
            .where(blockers_table.c.task_id == task_id)
            .order_by(blockers_table.c.reported_at,
                      blockers_table.c.blocker_id)
        )

        return [_to_record(row) for row in rows]

    async def list_open(self) -> list[BlockerRecord]:
        rows = await self.session.execute(
            select(blockers_table)
            .where(blockers_table.c.status == BlockerStatus.OPEN.value)
            .order_by(blockers_table.c.reported_at,
                      blockers_table.c.blocker_id)
        )

        return [_to_record(row) for row in rows]

    async def resolve(
        self,
        blocker_id: str,
        resolved_by: str,
        resolved_at: datetime,
        resolution_note: str | None,
    ) -> BlockerRecord | None:
        # Only an OPEN blocker is updated; resolved history never changes.
        row = (
            await self.session.execute(
                update(blockers_table)
                .where(
                    blockers_table.c.blocker_id == parse_uuid(blocker_id),
                    blockers_table.c.status == BlockerStatus.OPEN.value,
                )
                .values(
                    status=BlockerStatus.RESOLVED.value,
                    resolved_at=resolved_at,
                    resolved_by=resolved_by,
                    resolution_note=resolution_note,
                )
                .returning(blockers_table)
            )
        ).first()

        return _to_record(row) if row else None
