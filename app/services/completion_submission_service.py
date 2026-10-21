import hashlib
import json
from collections.abc import Callable
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError

from app.config import settings
from app.db.database import UnitOfWork
from app.schemas.completion import (
    CompletionClaim,
    CompletionSubmission,
)
from app.schemas.worker_task import TaskStatus
from app.services.task_state_service import TaskStateService
from app.validators.completion_validator import (
    CompletionValidationError,
    validate_completion,
)


def claim_hash(claim: CompletionClaim) -> str:
    # Canonical form: dict keys sorted, list order preserved. Two requests
    # are "the same" exactly when every field and list order match.
    canonical = json.dumps(
        claim.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class CompletionSubmissionService:
    def __init__(
        self,
        unit_of_work: Callable[[], UnitOfWork],
        state_service: TaskStateService,
    ):
        self.unit_of_work = unit_of_work
        self.state_service = state_service

    async def submit(
        self,
        task_id: str,
        worker_id: str,
        idempotency_key: str,
        claim: CompletionClaim,
    ):
        if not idempotency_key.strip() or len(idempotency_key) > 200:
            raise HTTPException(422, "Invalid Idempotency-Key.")

        request_hash = claim_hash(claim)

        try:
            return await self._submit(
                task_id, worker_id, idempotency_key, claim, request_hash
            )
        except IntegrityError as exc:
            # Backstop for races the row lock does not cover; the whole
            # transaction has already been rolled back.
            raise HTTPException(
                409,
                "Completion was submitted concurrently. Refresh and retry.",
            ) from exc

    async def _submit(
        self,
        task_id: str,
        worker_id: str,
        idempotency_key: str,
        claim: CompletionClaim,
        request_hash: str,
    ):
        # Everything below is one transaction. Any exception rolls back
        # the submission, its links, the idempotency record and the status.
        async with self.unit_of_work() as uow:
            # Serialises concurrent submissions for the same task.
            task = await uow.tasks.get_for_worker(
                task_id, worker_id, for_update=True
            )

            if task is None:
                raise HTTPException(404, "Task not found.")

            existing = await uow.completions.get_idempotent(
                task_id, worker_id, idempotency_key
            )

            if existing:
                stored_hash, submission = existing

                if stored_hash != request_hash:
                    raise HTTPException(
                        409,
                        "Idempotency-Key was already used with a different request.",
                    )

                return submission

            if task.status != TaskStatus.IN_PROGRESS:
                raise HTTPException(
                    409,
                    "Task must be IN_PROGRESS before completion submission.",
                )

            checklist_states = await uow.tasks.get_checklist_states(task_id)
            evidence_records = await uow.evidence.list_for_task(task_id)

            location = None

            if claim.completion_location_event_id:
                location = await uow.locations.get(
                    claim.completion_location_event_id
                )

                if location is None:
                    raise HTTPException(
                        422,
                        "Completion location event does not exist.",
                    )

            try:
                validate_completion(
                    task=task,
                    checklist_states=checklist_states,
                    evidence_records=evidence_records,
                    completion_location=location,
                    submitted_step_ids=claim.checklist_step_ids,
                    submitted_evidence_ids=claim.evidence_ids,
                    require_arrival_location=settings.require_arrival_location,
                )
            except CompletionValidationError as exc:
                raise HTTPException(422, str(exc)) from exc

            submission = CompletionSubmission(
                submission_id=str(uuid4()),
                task_id=task_id,
                worker_id=worker_id,
                checklist_step_ids=claim.checklist_step_ids,
                evidence_ids=claim.evidence_ids,
                completion_location_event_id=(
                    location.location_event_id if location else None
                ),
                notes=claim.notes,
            )

            await uow.completions.create(
                submission, idempotency_key, request_hash
            )

            # Status and submission reference change in one statement.
            await self.state_service.transition(
                uow.tasks,
                task_id,
                worker_id,
                TaskStatus.COMPLETION_SUBMITTED,
                completion_submission_id=submission.submission_id,
            )

            return submission
