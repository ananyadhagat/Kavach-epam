from sqlalchemy import Row, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import EvidenceRow
from app.repositories.task_repository import parse_uuid
from app.schemas.evidence import EvidenceRecord, EvidenceType

evidence_table = EvidenceRow.__table__

# Matches the uq_evidence_content unique constraint.
CONTENT_KEY = ["task_id", "worker_id", "sha256", "evidence_type"]


def _to_record(row: Row) -> EvidenceRecord:
    return EvidenceRecord(
        evidence_id=str(row.evidence_id),
        task_id=row.task_id,
        worker_id=row.worker_id,
        evidence_type=row.evidence_type,
        storage_key=row.storage_key,
        original_filename=row.original_filename,
        mime_type=row.mime_type,
        size_bytes=row.size_bytes,
        sha256=row.sha256,
        status=row.status,
        uploaded_at=row.uploaded_at,
    )


class EvidenceRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def find_duplicate(
        self,
        task_id: str,
        worker_id: str,
        sha256: str,
        evidence_type: EvidenceType,
    ) -> EvidenceRecord | None:
        row = (
            await self.session.execute(
                select(evidence_table).where(
                    evidence_table.c.task_id == task_id,
                    evidence_table.c.worker_id == worker_id,
                    evidence_table.c.sha256 == sha256,
                    evidence_table.c.evidence_type == evidence_type.value,
                )
            )
        ).first()

        return _to_record(row) if row else None

    async def save_or_get_duplicate(
        self,
        record: EvidenceRecord,
    ) -> tuple[EvidenceRecord, bool]:
        # ON CONFLICT absorbs a concurrent identical upload; any other
        # constraint violation (e.g. storage_key) still raises.
        row = (
            await self.session.execute(
                pg_insert(evidence_table)
                .values(
                    evidence_id=parse_uuid(record.evidence_id),
                    task_id=record.task_id,
                    worker_id=record.worker_id,
                    evidence_type=record.evidence_type.value,
                    storage_key=record.storage_key,
                    original_filename=record.original_filename,
                    mime_type=record.mime_type,
                    size_bytes=record.size_bytes,
                    sha256=record.sha256,
                    status=record.status.value,
                    uploaded_at=record.uploaded_at,
                )
                .on_conflict_do_nothing(index_elements=CONTENT_KEY)
                .returning(evidence_table)
            )
        ).first()

        if row is not None:
            return _to_record(row), False

        existing = await self.find_duplicate(
            record.task_id,
            record.worker_id,
            record.sha256,
            record.evidence_type,
        )
        return existing, True

    async def get(self, evidence_id: str) -> EvidenceRecord | None:
        key = parse_uuid(evidence_id)

        if key is None:
            return None

        row = (
            await self.session.execute(
                select(evidence_table).where(
                    evidence_table.c.evidence_id == key
                )
            )
        ).first()

        return _to_record(row) if row else None

    async def list_for_task(self, task_id: str) -> list[EvidenceRecord]:
        rows = await self.session.execute(
            select(evidence_table)
            .where(evidence_table.c.task_id == task_id)
            .order_by(evidence_table.c.uploaded_at,
                      evidence_table.c.evidence_id)
        )

        return [_to_record(row) for row in rows]

    async def list_storage_keys(self) -> set[str]:
        rows = await self.session.scalars(select(evidence_table.c.storage_key))
        return set(rows)
