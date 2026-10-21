import pytest
from fastapi import HTTPException

from app.schemas.completion import CompletionClaim
from app.schemas.worker_task import TaskStatus
from app.services.completion_submission_service import (
    CompletionSubmissionService,
)
from app.services.task_state_service import TaskStateService
from app.tests.conftest import get_status


@pytest.mark.asyncio
async def test_completion_rejected_when_task_not_in_progress(database):
    service = CompletionSubmissionService(
        database.unit_of_work,
        TaskStateService(),
    )

    claim = CompletionClaim(
        checklist_step_ids=["STEP-001"],
        evidence_ids=["before-id", "after-id"],
    )

    with pytest.raises(HTTPException) as exc:
        await service.submit(
            "TASK-001",
            "worker-001",
            "retry-001",
            claim,
        )

    assert exc.value.status_code == 409
    assert await get_status(database, "TASK-001") == TaskStatus.ASSIGNED
