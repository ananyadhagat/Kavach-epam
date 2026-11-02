import copy
import hashlib
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import pytest
from pydantic import SecretStr

from app.config import Settings
from scripts import reset_demo_task as reset

TASK_ID = "TASK-001"
WORKER_ID = "worker-001"
SUBMISSION_ID = "00000000-0000-0000-0000-000000000101"
ARRIVAL_ID = "00000000-0000-0000-0000-000000000201"
COMPLETION_ID = "00000000-0000-0000-0000-000000000202"
BEFORE_ID = "00000000-0000-0000-0000-000000000301"
AFTER_ID = "00000000-0000-0000-0000-000000000302"
BLOCKER_ID = "00000000-0000-0000-0000-000000000401"


class FakeTransaction:
    def __init__(self, plan, *, fail_apply=False):
        self.plan = plan
        self.fail_apply = fail_apply
        self.lock_requested = None
        self.applied = False

    async def inspect(self, lock):
        self.lock_requested = lock
        return self.plan

    async def apply(self, plan):
        self.applied = True
        plan.task.update(
            status="ACCEPTED",
            arrival_location_event_id=None,
            completion_location_event_id=None,
            completion_submission_id=None,
        )
        plan.submissions.clear()
        plan.submission_evidence.clear()
        plan.submission_steps.clear()
        plan.idempotency_records.clear()
        plan.evidence.clear()
        plan.location_events.clear()
        plan.blockers.clear()
        for item in plan.checklist:
            item.update(status="PENDING", note=None, completed_at=None)
        if self.fail_apply:
            raise reset.ResetSafetyError("simulated verification failure")


class FakeDatabase:
    def __init__(self, engine, image_root, plan, *, fail_apply=False):
        self.transaction_adapter = FakeTransaction(plan, fail_apply=fail_apply)
        self.committed = False
        self.rolled_back = False

    @asynccontextmanager
    async def transaction(self, execute):
        before = copy.deepcopy(self.transaction_adapter.plan)
        try:
            yield self.transaction_adapter
        except Exception:
            self.transaction_adapter.plan = before
            self.rolled_back = True
            raise
        else:
            self.committed = execute


class FakeEngine:
    async def dispose(self):
        return None


def build_plan(tmp_path: Path):
    evidence_specs = [
        (
            BEFORE_ID,
            "BEFORE",
            "before.jpg",
            b"before-image-bytes",
        ),
        (
            AFTER_ID,
            "AFTER",
            "after.jpg",
            b"after-image-bytes",
        ),
    ]
    evidence = []
    evidence_files = []
    for evidence_id, evidence_type, storage_key, content in evidence_specs:
        path = tmp_path / storage_key
        path.write_bytes(content)
        digest = hashlib.sha256(content).hexdigest()
        evidence.append(
            {
                "evidence_id": UUID(evidence_id),
                "task_id": TASK_ID,
                "worker_id": WORKER_ID,
                "evidence_type": evidence_type,
                "storage_key": storage_key,
                "original_filename": storage_key,
                "mime_type": "image/jpeg",
                "size_bytes": len(content),
                "sha256": digest,
                "status": "STORED",
            }
        )
        evidence_files.append(
            reset.EvidenceFile(evidence_id, storage_key, path, digest)
        )

    return reset.ResetPlan(
        task={
            "task_id": TASK_ID,
            "incident_id": "INC-001",
            "assigned_worker_id": WORKER_ID,
            "title": "Demo task",
            "description": "Demo description",
            "priority": "HIGH",
            "status": "COMPLETION_SUBMITTED",
            "latitude": 23.2,
            "longitude": 77.4,
            "address": "Demo location",
            "arrival_location_event_id": UUID(ARRIVAL_ID),
            "completion_location_event_id": UUID(COMPLETION_ID),
            "completion_submission_id": UUID(SUBMISSION_ID),
        },
        submissions=[
            {
                "submission_id": UUID(SUBMISSION_ID),
                "task_id": TASK_ID,
                "worker_id": WORKER_ID,
                "completion_location_event_id": UUID(COMPLETION_ID),
                "status": "COMPLETION_SUBMITTED",
            }
        ],
        submission_evidence=[
            {
                "task_id": TASK_ID,
                "submission_id": UUID(SUBMISSION_ID),
                "evidence_id": UUID(BEFORE_ID),
                "position": 0,
            },
            {
                "task_id": TASK_ID,
                "submission_id": UUID(SUBMISSION_ID),
                "evidence_id": UUID(AFTER_ID),
                "position": 1,
            },
        ],
        submission_steps=[],
        idempotency_records=[
            {
                "task_id": TASK_ID,
                "worker_id": WORKER_ID,
                "idempotency_key": "demo-key",
                "submission_id": UUID(SUBMISSION_ID),
            }
        ],
        evidence=evidence,
        location_events=[
            {
                "location_event_id": UUID(ARRIVAL_ID),
                "task_id": TASK_ID,
                "worker_id": WORKER_ID,
                "event_type": "ARRIVAL",
                "capture_status": "CAPTURED",
            },
            {
                "location_event_id": UUID(COMPLETION_ID),
                "task_id": TASK_ID,
                "worker_id": WORKER_ID,
                "event_type": "COMPLETION",
                "capture_status": "CAPTURED",
            },
        ],
        blockers=[
            {
                "blocker_id": UUID(BLOCKER_ID),
                "task_id": TASK_ID,
                "worker_id": WORKER_ID,
                "status": "RESOLVED",
                "previous_status": "IN_PROGRESS",
            }
        ],
        checklist=[
            {
                "task_id": TASK_ID,
                "step_id": "STEP-001",
                "position": 0,
                "title": "Demo checklist step",
                "required": True,
                "assigned_worker_id": WORKER_ID,
                "status": "PENDING",
                "note": None,
                "completed_at": None,
            }
        ],
        evidence_files=evidence_files,
    )


def make_settings(tmp_path, **overrides):
    values = {
        "app_env": "development",
        "database_url": SecretStr(
            "postgresql+asyncpg://demo:secret@localhost/kavach"
        ),
        "image_storage_dir": tmp_path,
        "kavach_demo_reset_enabled": True,
        "kavach_demo_reset_local_only": True,
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def install_fakes(monkeypatch, plan, *, fail_apply=False):
    instances = []
    monkeypatch.setattr(reset, "create_async_engine", lambda *args, **kwargs: FakeEngine())

    def factory(engine, image_root):
        database = FakeDatabase(
            engine, image_root, plan, fail_apply=fail_apply
        )
        instances.append(database)
        return database

    return instances, factory


@pytest.mark.asyncio
async def test_dry_run_is_default_and_does_not_mutate_or_delete_files(
    tmp_path, monkeypatch
):
    plan = build_plan(tmp_path)
    instances, factory = install_fakes(monkeypatch, plan)

    result = await reset.run_reset(
        make_settings(tmp_path),
        database_factory=factory,
    )

    assert result["mode"] == "dry-run"
    assert instances[0].transaction_adapter.lock_requested is False
    assert instances[0].transaction_adapter.applied is False
    assert instances[0].committed is False
    assert instances[0].rolled_back is False
    assert all(item.path.is_file() for item in plan.evidence_files)
    assert plan.task["status"] == "COMPLETION_SUBMITTED"


@pytest.mark.asyncio
async def test_execution_requires_exact_typed_confirmation(tmp_path, monkeypatch):
    instances, factory = install_fakes(monkeypatch, build_plan(tmp_path))

    with pytest.raises(reset.ResetSafetyError, match="confirmation"):
        await reset.run_reset(
            make_settings(tmp_path),
            execute=True,
            confirmation="reset task-001",
            database_factory=factory,
        )

    assert instances == []


@pytest.mark.asyncio
async def test_execution_refuses_non_development_environment(tmp_path, monkeypatch):
    instances, factory = install_fakes(monkeypatch, build_plan(tmp_path))

    with pytest.raises(reset.ResetSafetyError, match="APP_ENV=development"):
        await reset.run_reset(
            make_settings(tmp_path, app_env="production"),
            execute=True,
            confirmation=reset.CONFIRMATION,
            database_factory=factory,
        )

    assert instances == []


@pytest.mark.asyncio
async def test_execution_requires_explicit_reset_flags(tmp_path, monkeypatch):
    instances, factory = install_fakes(monkeypatch, build_plan(tmp_path))

    with pytest.raises(reset.ResetSafetyError, match="KAVACH_DEMO_RESET_ENABLED"):
        await reset.run_reset(
            make_settings(tmp_path, kavach_demo_reset_enabled=False),
            execute=True,
            confirmation=reset.CONFIRMATION,
            database_factory=factory,
        )
    with pytest.raises(reset.ResetSafetyError, match="LOCAL_ONLY"):
        await reset.run_reset(
            make_settings(tmp_path, kavach_demo_reset_local_only=False),
            execute=True,
            confirmation=reset.CONFIRMATION,
            database_factory=factory,
        )

    assert instances == []


@pytest.mark.asyncio
async def test_wrong_database_is_refused_before_connecting(tmp_path, monkeypatch):
    instances, factory = install_fakes(monkeypatch, build_plan(tmp_path))
    settings = make_settings(
        tmp_path,
        database_url=SecretStr(
            "postgresql+asyncpg://demo:secret@localhost/kavach_test"
        ),
    )

    with pytest.raises(reset.ResetSafetyError, match="kavach"):
        await reset.run_reset(settings, database_factory=factory)

    assert instances == []


@pytest.mark.asyncio
async def test_unexpected_record_ownership_stops_without_applying(
    tmp_path, monkeypatch
):
    plan = build_plan(tmp_path)
    plan.evidence[0]["worker_id"] = "another-worker"
    instances, factory = install_fakes(monkeypatch, plan)

    with pytest.raises(reset.ResetSafetyError, match="another task or worker"):
        await reset.run_reset(
            make_settings(tmp_path),
            execute=True,
            confirmation=reset.CONFIRMATION,
            database_factory=factory,
        )

    assert instances[0].transaction_adapter.applied is False
    assert instances[0].rolled_back is True
    assert all(item.path.is_file() for item in plan.evidence_files)


@pytest.mark.asyncio
async def test_unexpected_reference_and_open_blocker_stop_without_mutation(
    tmp_path, monkeypatch
):
    plan = build_plan(tmp_path)
    plan.task["arrival_location_event_id"] = COMPLETION_ID
    instances, factory = install_fakes(monkeypatch, plan)

    with pytest.raises(reset.ResetSafetyError, match="expected event type"):
        await reset.run_reset(
            make_settings(tmp_path),
            execute=True,
            confirmation=reset.CONFIRMATION,
            database_factory=factory,
        )

    assert instances[0].transaction_adapter.applied is False
    assert instances[0].rolled_back is True

    plan = build_plan(tmp_path)
    plan.blockers[0]["status"] = "OPEN"
    instances, factory = install_fakes(monkeypatch, plan)
    with pytest.raises(reset.ResetSafetyError, match="open blocker"):
        await reset.run_reset(
            make_settings(tmp_path),
            execute=True,
            confirmation=reset.CONFIRMATION,
            database_factory=factory,
        )
    assert instances[0].transaction_adapter.applied is False
    assert instances[0].rolled_back is True


@pytest.mark.asyncio
async def test_successful_reset_clears_execution_and_deletes_only_verified_files(
    tmp_path, monkeypatch
):
    plan = build_plan(tmp_path)
    instances, factory = install_fakes(monkeypatch, plan)

    result = await reset.run_reset(
        make_settings(tmp_path),
        execute=True,
        confirmation=reset.CONFIRMATION,
        database_factory=factory,
    )

    assert result["mode"] == "executed"
    assert result["database_committed"] is True
    assert instances[0].committed is True
    assert instances[0].rolled_back is False
    assert plan.task["status"] == "ACCEPTED"
    assert all(
        plan.task[field] is None
        for field in (
            "arrival_location_event_id",
            "completion_location_event_id",
            "completion_submission_id",
        )
    )
    assert plan.checklist[0]["title"] == "Demo checklist step"
    assert all(not item.path.exists() for item in plan.evidence_files)
    assert len(result["deleted_files"]) == 2


@pytest.mark.asyncio
async def test_post_commit_file_change_is_reported_as_partial_completion(
    tmp_path, monkeypatch
):
    plan = build_plan(tmp_path)
    instances = []

    class ChangedFileAfterCommitDatabase(FakeDatabase):
        @asynccontextmanager
        async def transaction(self, execute):
            async with super().transaction(execute) as transaction:
                yield transaction
            if execute:
                plan.evidence_files[0].path.write_bytes(b"changed-after-commit")

    def factory(engine, image_root):
        database = ChangedFileAfterCommitDatabase(engine, image_root, plan)
        instances.append(database)
        return database

    with pytest.raises(
        reset.PostCommitCleanupError, match="Database reset committed"
    ):
        await reset.run_reset(
            make_settings(tmp_path),
            execute=True,
            confirmation=reset.CONFIRMATION,
            database_factory=factory,
        )

    assert instances[0].committed is True
    assert plan.evidence_files[0].path.is_file()
    assert plan.evidence_files[0].path.read_bytes() == b"changed-after-commit"


@pytest.mark.asyncio
async def test_verification_failure_rolls_back_and_keeps_files(
    tmp_path, monkeypatch
):
    plan = build_plan(tmp_path)
    instances, factory = install_fakes(
        monkeypatch, plan, fail_apply=True
    )

    with pytest.raises(reset.ResetSafetyError, match="verification failure"):
        await reset.run_reset(
            make_settings(tmp_path),
            execute=True,
            confirmation=reset.CONFIRMATION,
            database_factory=factory,
        )

    assert instances[0].rolled_back is True
    assert instances[0].committed is False
    rolled_back_plan = instances[0].transaction_adapter.plan
    assert rolled_back_plan.task["status"] == "COMPLETION_SUBMITTED"
    assert len(rolled_back_plan.evidence) == 2
    assert len(rolled_back_plan.location_events) == 2
    assert all(item.path.is_file() for item in plan.evidence_files)
