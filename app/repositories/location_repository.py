from sqlalchemy import Row, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import LocationEventRow
from app.repositories.task_repository import parse_uuid
from app.schemas.location_event import LocationEventRecord

locations_table = LocationEventRow.__table__


def _to_record(row: Row) -> LocationEventRecord:
    return LocationEventRecord(
        location_event_id=str(row.location_event_id),
        task_id=row.task_id,
        worker_id=row.worker_id,
        event_type=row.event_type,
        capture_status=row.capture_status,
        latitude=row.latitude,
        longitude=row.longitude,
        accuracy_meters=row.accuracy_meters,
        captured_at_device=row.captured_at_device,
        received_at_server=row.received_at_server,
    )


class LocationRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def save(self, record: LocationEventRecord) -> LocationEventRecord:
        row = (
            await self.session.execute(
                locations_table.insert()
                .values(
                    location_event_id=parse_uuid(record.location_event_id),
                    task_id=record.task_id,
                    worker_id=record.worker_id,
                    event_type=record.event_type.value,
                    capture_status=record.capture_status.value,
                    latitude=record.latitude,
                    longitude=record.longitude,
                    accuracy_meters=record.accuracy_meters,
                    captured_at_device=record.captured_at_device,
                    received_at_server=record.received_at_server,
                )
                .returning(locations_table)
            )
        ).first()

        return _to_record(row)

    async def get(self, event_id: str) -> LocationEventRecord | None:
        key = parse_uuid(event_id)

        if key is None:
            return None

        row = (
            await self.session.execute(
                select(locations_table).where(
                    locations_table.c.location_event_id == key
                )
            )
        ).first()

        return _to_record(row) if row else None

    async def list_for_task(self, task_id: str) -> list[LocationEventRecord]:
        rows = await self.session.execute(
            select(locations_table)
            .where(locations_table.c.task_id == task_id)
            .order_by(locations_table.c.received_at_server)
        )

        return [_to_record(row) for row in rows]
