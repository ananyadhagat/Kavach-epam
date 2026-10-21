from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    CompletionEvidenceRow,
    CompletionStepRow,
    CompletionSubmissionRow,
    IdempotencyRecordRow,
)
from app.repositories.task_repository import parse_uuid, uuid_str
from app.schemas.completion import CompletionSubmission

submissions_table = CompletionSubmissionRow.__table__
submission_evidence_table = CompletionEvidenceRow.__table__
submission_steps_table = CompletionStepRow.__table__
idempotency_table = IdempotencyRecordRow.__table__


class CompletionRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(
        self,
        submission: CompletionSubmission,
        idempotency_key: str,
        request_hash: str,
    ) -> None:
        submission_id = parse_uuid(submission.submission_id)

        await self.session.execute(
            submissions_table.insert().values(
                submission_id=submission_id,
                task_id=submission.task_id,
                worker_id=submission.worker_id,
                completion_location_event_id=parse_uuid(
                    submission.completion_location_event_id
                ),
                notes=submission.notes,
                status=submission.status,
                submitted_at=submission.submitted_at,
            )
        )

        await self.session.execute(
            submission_evidence_table.insert(),
            [
                {
                    "submission_id": submission_id,
                    "evidence_id": parse_uuid(evidence_id),
                    "task_id": submission.task_id,
                    "position": position,
                }
                for position, evidence_id in enumerate(
                    submission.evidence_ids
                )
            ],
        )

        await self.session.execute(
            submission_steps_table.insert(),
            [
                {
                    "submission_id": submission_id,
                    "step_id": step_id,
                    "task_id": submission.task_id,
                    "position": position,
                }
                for position, step_id in enumerate(
                    submission.checklist_step_ids
                )
            ],
        )

        await self.session.execute(
            idempotency_table.insert().values(
                task_id=submission.task_id,
                worker_id=submission.worker_id,
                idempotency_key=idempotency_key,
                request_hash=request_hash,
                submission_id=submission_id,
            )
        )

    async def get(self, submission_id: str) -> CompletionSubmission | None:
        key = parse_uuid(submission_id)

        if key is None:
            return None

        row = (
            await self.session.execute(
                select(submissions_table).where(
                    submissions_table.c.submission_id == key
                )
            )
        ).first()

        if row is None:
            return None

        evidence_ids = await self.session.scalars(
            select(submission_evidence_table.c.evidence_id)
            .where(submission_evidence_table.c.submission_id == key)
            .order_by(submission_evidence_table.c.position)
        )
        step_ids = await self.session.scalars(
            select(submission_steps_table.c.step_id)
            .where(submission_steps_table.c.submission_id == key)
            .order_by(submission_steps_table.c.position)
        )

        return CompletionSubmission(
            submission_id=str(row.submission_id),
            task_id=row.task_id,
            worker_id=row.worker_id,
            checklist_step_ids=list(step_ids),
            evidence_ids=[str(item) for item in evidence_ids],
            completion_location_event_id=uuid_str(
                row.completion_location_event_id
            ),
            notes=row.notes,
            submitted_at=row.submitted_at,
            status=row.status,
        )

    async def get_idempotent(
        self,
        task_id: str,
        worker_id: str,
        idempotency_key: str,
    ) -> tuple[str, CompletionSubmission] | None:
        row = (
            await self.session.execute(
                select(idempotency_table).where(
                    idempotency_table.c.task_id == task_id,
                    idempotency_table.c.worker_id == worker_id,
                    idempotency_table.c.idempotency_key == idempotency_key,
                )
            )
        ).first()

        if row is None:
            return None

        return row.request_hash, await self.get(str(row.submission_id))
