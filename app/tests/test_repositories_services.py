import asyncio
from io import BytesIO
from uuid import uuid4

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError
from starlette.datastructures import UploadFile

from app.db.seed import seed_demo_data
from app.main import app
from app.repositories.evidence_repository import EvidenceRepository
from app.repositories.task_repository import TaskRepository
from app.schemas.checklist import ChecklistStatus
from app.schemas.completion import CompletionClaim
from app.schemas.evidence import EvidenceRecord, EvidenceType
from app.schemas.location_event import (
    LocationCaptureStatus,
    LocationEventRecord,
    LocationEventType,
)
from app.schemas.worker_task import TaskStatus
from app.services.completion_submission_service import (
    CompletionSubmissionService,
)
from app.services.evidence_service import EvidenceService
from app.services.task_state_service import TaskStateService
from app.storage.image_storage import ImageStorage
from app.tests.conftest import (
    AUTH,
    OTHER_WORKER_ID,
    WORKER_ID,
    add_task_with_worker,
    count_rows,
    force_status,
    get_status,
    idempotency_records,
    make_image,
    make_task,
    post_action,
    prepare_for_completion,
    table_count,
)


# ---------- TaskRepository ----------

@pytest.mark.asyncio
async def test_seed_is_idempotent(database):
    async with database.unit_of_work() as uow:
        assert await seed_demo_data(uow) is False

    assert await table_count(database, "tasks") == 1
    assert await table_count(database, "checklist_steps") == 3
    assert await table_count(database, "workers") == 1


@pytest.mark.asyncio
async def test_add_task_initialises_checklist(database):
    async with database.unit_of_work() as uow:
        await add_task_with_worker(uow, make_task("T1", steps=("A", "B")))

    async with database.unit_of_work() as uow:
        records = await uow.tasks.get_checklist_records("T1")

    assert [(r.task_id, r.step_id) for r in records] == [("T1", "A"),
                                                         ("T1", "B")]
    assert all(r.status == ChecklistStatus.PENDING for r in records)


@pytest.mark.asyncio
async def test_add_task_rejects_duplicate_id(database):
    with pytest.raises(ValueError):
        async with database.unit_of_work() as uow:
            await add_task_with_worker(uow, make_task("TASK-001"))


@pytest.mark.asyncio
async def test_add_task_rejects_duplicate_step_ids(database):
    with pytest.raises(ValueError):
        async with database.unit_of_work() as uow:
            await add_task_with_worker(uow, make_task("T1", steps=("A", "A")))

    async with database.unit_of_work() as uow:
        assert await uow.tasks.task_exists("T1") is False


@pytest.mark.asyncio
async def test_add_task_rejects_unknown_worker(database):
    with pytest.raises(ValueError, match="does not exist"):
        async with database.unit_of_work() as uow:
            await uow.tasks.add_task(make_task("T1", worker_id="ghost"))


@pytest.mark.asyncio
async def test_worker_filtering(database):
    async with database.unit_of_work() as uow:
        await add_task_with_worker(
            uow, make_task("OTHER-1", worker_id=OTHER_WORKER_ID)
        )

    async with database.unit_of_work() as uow:
        mine = await uow.tasks.list_for_worker(WORKER_ID)
        theirs = await uow.tasks.list_for_worker(OTHER_WORKER_ID)
        nobody = await uow.tasks.list_for_worker("nobody")

    assert [t.task_id for t in mine] == ["TASK-001"]
    assert [t.task_id for t in theirs] == ["OTHER-1"]
    assert nobody == []


@pytest.mark.asyncio
async def test_get_for_worker_missing_and_foreign(database):
    async with database.unit_of_work() as uow:
        assert await uow.tasks.get_for_worker("NOPE", WORKER_ID) is None
        assert await uow.tasks.get_for_worker("TASK-001",
                                              OTHER_WORKER_ID) is None
        found = await uow.tasks.get_for_worker("TASK-001", WORKER_ID)

    assert found.task_id == "TASK-001"


@pytest.mark.asyncio
async def test_returned_tasks_are_copies(database):
    async with database.unit_of_work() as uow:
        task = await uow.tasks.get_for_worker("TASK-001", WORKER_ID)

    task.status = TaskStatus.REJECTED
    task.checklist.clear()

    async with database.unit_of_work() as uow:
        stored = await uow.tasks.get_for_worker("TASK-001", WORKER_ID)

    assert stored.status == TaskStatus.ASSIGNED
    assert len(stored.checklist) == 3


@pytest.mark.asyncio
async def test_update_status_compare_and_set(database):
    async with database.unit_of_work() as uow:
        assert await uow.tasks.update_status(
            "TASK-001", WORKER_ID, TaskStatus.ACCEPTED, TaskStatus.IN_PROGRESS
        ) is None
        assert await uow.tasks.update_status(
            "TASK-001", OTHER_WORKER_ID, TaskStatus.ASSIGNED,
            TaskStatus.ACCEPTED,
        ) is None

    assert await get_status(database, "TASK-001") == TaskStatus.ASSIGNED

    async with database.unit_of_work() as uow:
        updated = await uow.tasks.update_status(
            "TASK-001", WORKER_ID, TaskStatus.ASSIGNED, TaskStatus.ACCEPTED
        )

    assert updated.status == TaskStatus.ACCEPTED
    assert await get_status(database, "TASK-001") == TaskStatus.ACCEPTED


@pytest.mark.asyncio
async def test_update_status_rejects_unknown_submission_reference(database):
    await force_status(database, "TASK-001", TaskStatus.IN_PROGRESS)

    with pytest.raises(IntegrityError):
        async with database.unit_of_work() as uow:
            await uow.tasks.update_status(
                "TASK-001", WORKER_ID, TaskStatus.IN_PROGRESS,
                TaskStatus.COMPLETION_SUBMITTED,
                completion_submission_id=str(uuid4()),
            )

    assert await get_status(database, "TASK-001") == TaskStatus.IN_PROGRESS


@pytest.mark.asyncio
async def test_update_checklist(database):
    async with database.unit_of_work() as uow:
        record = await uow.tasks.update_checklist(
            "TASK-001", "STEP-002", ChecklistStatus.COMPLETED, "ok"
        )

    assert record.status == ChecklistStatus.COMPLETED
    assert record.note == "ok"

    async with database.unit_of_work() as uow:
        assert (await uow.tasks.get_checklist_states("TASK-001")) == {
            "STEP-001": "PENDING", "STEP-002": "COMPLETED",
            "STEP-003": "PENDING",
        }
        assert await uow.tasks.update_checklist(
            "TASK-001", "NOPE", ChecklistStatus.COMPLETED
        ) is None
        assert await uow.tasks.update_checklist(
            "NOPE", "STEP-001", ChecklistStatus.COMPLETED
        ) is None
        assert await uow.tasks.get_checklist_records("NOPE") == []


# ---------- Evidence & location repositories ----------

def evidence_record(evidence_id: str, sha: str = "a" * 64,
                    evidence_type: EvidenceType = EvidenceType.BEFORE,
                    task_id: str = "TASK-001"):
    return EvidenceRecord(
        evidence_id=evidence_id, task_id=task_id, worker_id=WORKER_ID,
        evidence_type=evidence_type, storage_key=f"{uuid4().hex}.png",
        original_filename="x.png", mime_type="image/png", size_bytes=10,
        sha256=sha,
    )


@pytest.mark.asyncio
async def test_evidence_repository_duplicate_detection(database):
    e1, e2, e3 = (str(uuid4()) for _ in range(3))

    async with database.unit_of_work() as uow:
        _, dup1 = await uow.evidence.save_or_get_duplicate(evidence_record(e1))
        second, dup2 = await uow.evidence.save_or_get_duplicate(
            evidence_record(e2)
        )
        other_type, dup3 = await uow.evidence.save_or_get_duplicate(
            evidence_record(e3, evidence_type=EvidenceType.AFTER)
        )

    assert (dup1, dup2, dup3) == (False, True, False)
    assert second.evidence_id == e1
    assert other_type.evidence_id == e3

    async with database.unit_of_work() as uow:
        listed = await uow.evidence.list_for_task("TASK-001")
        assert {r.evidence_id for r in listed} == {e1, e3}
        assert await uow.evidence.get("missing") is None
        assert await uow.evidence.get(str(uuid4())) is None
        assert await uow.evidence.list_for_task("NOPE") == []


@pytest.mark.asyncio
async def test_location_repository(database):
    event_id = str(uuid4())
    record = LocationEventRecord(
        location_event_id=event_id, task_id="TASK-001", worker_id=WORKER_ID,
        event_type=LocationEventType.ARRIVAL,
        capture_status=LocationCaptureStatus.UNAVAILABLE,
    )

    async with database.unit_of_work() as uow:
        await uow.locations.save(record)

    async with database.unit_of_work() as uow:
        assert (await uow.locations.get(event_id)).task_id == "TASK-001"
        assert await uow.locations.get("missing") is None
        assert await uow.locations.get(str(uuid4())) is None
        assert len(await uow.locations.list_for_task("TASK-001")) == 1


# ---------- Services ----------

@pytest.mark.asyncio
async def test_state_service_errors(database):
    service = TaskStateService()

    async with database.unit_of_work() as uow:
        with pytest.raises(HTTPException) as missing:
            await service.transition(uow.tasks, "NOPE", WORKER_ID,
                                     TaskStatus.ACCEPTED)
        with pytest.raises(HTTPException) as invalid:
            await service.transition(uow.tasks, "TASK-001", WORKER_ID,
                                     TaskStatus.PAUSED)

    assert missing.value.status_code == 404
    assert invalid.value.status_code == 409


@pytest.mark.asyncio
async def test_state_service_detects_concurrent_change(database,
                                                       monkeypatch):
    async def lost_race(self, **_kwargs):
        return None

    monkeypatch.setattr(TaskRepository, "update_status", lost_race)

    async with database.unit_of_work() as uow:
        with pytest.raises(HTTPException) as exc:
            await TaskStateService().transition(
                uow.tasks, "TASK-001", WORKER_ID, TaskStatus.ACCEPTED
            )

    assert exc.value.status_code == 409
    assert "concurrently" in exc.value.detail


@pytest.mark.asyncio
async def test_concurrent_transitions_only_one_wins(database):
    # Two real transactions on separate connections race for one row.
    async def attempt(new_status: TaskStatus):
        async with database.unit_of_work() as uow:
            return await TaskStateService().transition(
                uow.tasks, "TASK-001", WORKER_ID, new_status
            )

    results = await asyncio.gather(
        attempt(TaskStatus.ACCEPTED),
        attempt(TaskStatus.REJECTED),
        return_exceptions=True,
    )

    successes = [r for r in results if not isinstance(r, Exception)]
    failures = [r for r in results if isinstance(r, HTTPException)]
    assert len(successes) == 1
    assert len(failures) == 1 and failures[0].status_code == 409
    assert await get_status(database, "TASK-001") == successes[0].status


@pytest.mark.asyncio
async def test_evidence_record_failure_removes_stored_file(database,
                                                           upload_dir,
                                                           monkeypatch):
    await force_status(database, "TASK-001", TaskStatus.ACCEPTED)
    service = EvidenceService(database.unit_of_work, ImageStorage())

    async def failing_save(self, _record):
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(EvidenceRepository, "save_or_get_duplicate",
                        failing_save)

    upload = UploadFile(filename="a.png", file=BytesIO(make_image()),
                        headers={"content-type": "image/png"})

    with pytest.raises(RuntimeError):
        await service.upload("TASK-001", WORKER_ID, EvidenceType.BEFORE,
                             upload)

    assert list(upload_dir.iterdir()) == []
    assert await table_count(database, "evidence") == 0


def test_completion_transition_failure_leaves_no_record(client, monkeypatch):
    claim = prepare_for_completion(client)
    service = client.app.state.completion_service

    # Fails after the submission, its links and the idempotency record have
    # been inserted, so this exercises a real database rollback.
    async def failing_transition(*_args, **_kwargs):
        raise HTTPException(409, "Task changed concurrently. Refresh and retry.")

    monkeypatch.setattr(service.state_service, "transition",
                        failing_transition)

    response = client.post(
        "/api/v1/worker/tasks/TASK-001/completion", json=claim,
        headers={**AUTH, "Idempotency-Key": "k1"},
    )

    assert response.status_code == 409
    assert idempotency_records(client) == {}
    for table in ("completion_submissions", "completion_submission_evidence",
                  "completion_submission_steps", "idempotency_records"):
        assert count_rows(client, table) == 0, table
    task = client.get("/api/v1/worker/tasks/TASK-001", headers=AUTH).json()
    assert task["status"] == "IN_PROGRESS"
    assert task["completion_submission_id"] is None


async def _ready_for_completion(database) -> CompletionClaim:
    """TASK-001 in progress with all steps done and BEFORE/AFTER evidence."""
    await force_status(database, "TASK-001", TaskStatus.IN_PROGRESS)
    before, after = str(uuid4()), str(uuid4())

    async with database.unit_of_work() as uow:
        for step_id in ("STEP-001", "STEP-002", "STEP-003"):
            await uow.tasks.update_checklist("TASK-001", step_id,
                                             ChecklistStatus.COMPLETED)
        await uow.evidence.save_or_get_duplicate(
            evidence_record(before, "b" * 64, EvidenceType.BEFORE))
        await uow.evidence.save_or_get_duplicate(
            evidence_record(after, "c" * 64, EvidenceType.AFTER))

    return CompletionClaim(
        checklist_step_ids=["STEP-001", "STEP-002", "STEP-003"],
        evidence_ids=[before, after],
    )


@pytest.mark.asyncio
async def test_concurrent_completion_with_different_keys(database):
    claim = await _ready_for_completion(database)
    service = CompletionSubmissionService(database.unit_of_work,
                                          TaskStateService())

    results = await asyncio.gather(
        service.submit("TASK-001", WORKER_ID, "key-A", claim),
        service.submit("TASK-001", WORKER_ID, "key-B", claim),
        return_exceptions=True,
    )

    successes = [r for r in results if not isinstance(r, Exception)]
    failures = [r for r in results if isinstance(r, HTTPException)]
    assert len(successes) == 1
    assert len(failures) == 1 and failures[0].status_code == 409
    assert await table_count(database, "idempotency_records") == 1
    assert await table_count(database, "completion_submissions") == 1

    async with database.unit_of_work() as uow:
        task = await uow.tasks.get_for_worker("TASK-001", WORKER_ID)
    assert task.completion_submission_id == successes[0].submission_id


@pytest.mark.asyncio
async def test_concurrent_completion_with_same_key_replays(database):
    claim = await _ready_for_completion(database)
    service = CompletionSubmissionService(database.unit_of_work,
                                          TaskStateService())

    first, second = await asyncio.gather(
        service.submit("TASK-001", WORKER_ID, "same-key", claim),
        service.submit("TASK-001", WORKER_ID, "same-key", claim),
    )

    assert first.submission_id == second.submission_id
    assert await table_count(database, "completion_submissions") == 1


# ---------- Storage mechanism ----------

def test_data_persists_across_restarts(clean_database):
    # Reversed from the in-memory era: a new application start now reads
    # the same PostgreSQL data instead of starting empty.
    with TestClient(app) as first:
        post_action(first, "TASK-001", "accept")
        assert first.get("/api/v1/worker/tasks/TASK-001",
                         headers=AUTH).json()["status"] == "ACCEPTED"

    with TestClient(app) as second:
        assert second.get("/api/v1/worker/tasks/TASK-001",
                          headers=AUTH).json()["status"] == "ACCEPTED"
