import asyncio
import math
from io import BytesIO
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine
from starlette.datastructures import UploadFile

from app.config import settings
from app.db.database import (
    Database,
    DatabaseConfigurationError,
    parse_database_url,
    verify_schema,
)
from app.db.models import Base
from app.main import app
from app.repositories.location_repository import LocationRepository
from app.schemas.evidence import EvidenceType
from app.schemas.worker_task import TaskStatus
from app.services.evidence_service import EvidenceService
from app.storage.image_storage import ImageStorage
from app.tests.conftest import (
    API,
    AUTH,
    UnsafeTestDatabaseError,
    assert_safe_test_database,
    count_rows,
    force_status,
    location_payload,
    make_image,
    post_action,
    prepare_for_completion,
    table_count,
    upload,
)

# ---------------------------------------------------------------------------
# Configuration (no database server needed)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "raw",
    [
        "postgresql://u:p@localhost:5432/kavach",
        "postgres://u:p@localhost/kavach",
        "postgresql+asyncpg://u:p@localhost/kavach",
    ],
)
def test_postgres_urls_use_asyncpg(raw):
    assert parse_database_url(raw).drivername == "postgresql+asyncpg"


@pytest.mark.parametrize(
    "raw",
    [
        "sqlite:///kavach.db",
        "sqlite+aiosqlite:///:memory:",
        "mysql://u:p@localhost/kavach",
        "postgresql+psycopg2://u:p@localhost/kavach",
        "postgresql+asyncpg://u:p@localhost",
        "not a url",
    ],
)
def test_non_postgres_or_incomplete_urls_rejected(raw):
    with pytest.raises(DatabaseConfigurationError):
        parse_database_url(raw)


@pytest.mark.parametrize(
    "raw",
    [
        "postgresql+asyncpg://kavach_app:Secret@Part2@localhost:5432/kavach",
        "postgresql+asyncpg://kavach_app:<Secret@Part2>@localhost/kavach",
        "postgresql+asyncpg://kavach_app:<SecretPart2>@local host/kavach",
    ],
    ids=["unencoded-at", "placeholder-brackets", "space-in-host"],
)
def test_malformed_password_encoding_rejected_without_leaking(raw):
    with pytest.raises(DatabaseConfigurationError) as exc:
        parse_database_url(raw)

    assert "percent-encode" in str(exc.value).lower()
    assert "Part2" not in str(exc.value)
    assert "Secret" not in str(exc.value)


def test_percent_encoded_password_is_decoded():
    url = parse_database_url(
        "postgresql+asyncpg://kavach_app:Secret%40Part2@localhost:5432/kavach"
    )

    assert url.host == "localhost"
    assert url.password == "Secret@Part2"


def test_startup_fails_without_database_url():
    # isolated_settings sets database_url to None.
    with pytest.raises(DatabaseConfigurationError, match="DATABASE_URL"):
        with TestClient(app):
            pass


def test_startup_fails_clearly_when_postgres_unreachable(monkeypatch):
    monkeypatch.setattr(
        settings, "database_url",
        SecretStr("postgresql+asyncpg://kavach:s3cret-pw@127.0.0.1:1/x_test"),
    )
    monkeypatch.setattr(settings, "database_connect_timeout_seconds", 2.0)

    with pytest.raises(DatabaseConfigurationError) as exc:
        with TestClient(app):
            pass

    message = str(exc.value)
    assert "PostgreSQL is unavailable" in message
    assert "s3cret-pw" not in message
    assert "***" in message


@pytest.mark.parametrize(
    ("test_url", "app_url"),
    [
        ("postgresql://u@localhost/kavach", None),
        ("postgresql://u@localhost/kavach_testing", None),
        ("postgresql://u@localhost/test", None),
        ("postgresql://u@localhost:5432/kavach_test",
         "postgresql://u@localhost:5432/kavach_test"),
    ],
)
def test_test_database_guard_refuses_unsafe_targets(test_url, app_url):
    with pytest.raises(UnsafeTestDatabaseError):
        assert_safe_test_database(
            parse_database_url(test_url),
            parse_database_url(app_url) if app_url else None,
        )


def test_test_database_guard_accepts_test_database():
    assert_safe_test_database(
        parse_database_url("postgresql://u@localhost/kavach_test"),
        parse_database_url("postgresql://u@localhost/kavach"),
    )


# ---------------------------------------------------------------------------
# Schema and migrations
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_migrated_schema_matches_models(database):
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext

    def diff(sync_connection):
        context = MigrationContext.configure(
            sync_connection, opts={"compare_type": True}
        )
        return compare_metadata(context, Base.metadata)

    async with database.engine.connect() as connection:
        differences = await connection.run_sync(diff)

    assert differences == []


@pytest.mark.asyncio
async def test_schema_version_mismatch_is_detected(database):
    async with database.engine.connect() as connection:
        transaction = await connection.begin()
        await connection.execute(
            text("UPDATE alembic_version SET version_num = 'outdated'")
        )

        with pytest.raises(DatabaseConfigurationError, match="alembic upgrade"):
            await verify_schema(connection)

        await transaction.rollback()

    async with database.engine.connect() as connection:
        await verify_schema(connection)


@pytest.mark.asyncio
async def test_database_connection(database):
    async with database.engine.connect() as connection:
        name = await connection.scalar(text("SELECT current_database()"))
        version = await connection.scalar(text("SHOW server_version"))

    assert name.endswith("_test")
    assert version


def test_runtime_database_outage_returns_503(client):
    healthy = client.get(API, headers=AUTH)
    assert healthy.status_code == 200

    broken = Database(create_async_engine(
        "postgresql+asyncpg://u:p@127.0.0.1:1/x_test",
        connect_args={"timeout": 2},
    ))
    service = client.app.state.field_work_service
    original = service.unit_of_work
    service.unit_of_work = broken.unit_of_work

    try:
        response = client.get(API, headers=AUTH)
    finally:
        service.unit_of_work = original
        client.portal.call(broken.dispose)

    assert response.status_code == 503
    assert response.json() == {
        "detail": "Database unavailable. Please retry later."
    }
    assert "TASK-001" not in response.text


# ---------------------------------------------------------------------------
# Persistence across application restarts
# ---------------------------------------------------------------------------

def test_full_workflow_persists_across_restart(clean_database, upload_dir):
    with TestClient(app) as first:
        claim = prepare_for_completion(first)
        first.patch(f"{API}/TASK-001/checklist/STEP-001",
                    json={"status": "COMPLETED", "note": "Bagged waste."},
                    headers=AUTH)
        arrival = first.post(f"{API}/TASK-001/arrival",
                             json=location_payload("ARRIVAL"), headers=AUTH)
        submitted = first.post(
            f"{API}/TASK-001/completion", json=claim,
            headers={**AUTH, "Idempotency-Key": "restart-key"},
        ).json()["submission"]
        files_before = sorted(p.name for p in upload_dir.iterdir())

    with TestClient(app) as second:
        task = second.get(f"{API}/TASK-001", headers=AUTH).json()
        assert task["status"] == "COMPLETION_SUBMITTED"
        assert task["completion_submission_id"] == submitted["submission_id"]
        assert task["arrival_location_event_id"] == (
            arrival.json()["location_event"]["location_event_id"]
        )
        assert task["completion_location_event_id"] == (
            claim["completion_location_event_id"]
        )

        steps = second.get(f"{API}/TASK-001/checklist", headers=AUTH).json()
        step_1 = next(s for s in steps["steps"] if s["step_id"] == "STEP-001")
        assert step_1["status"] == "COMPLETED"
        assert step_1["note"] == "Bagged waste."

        assert count_rows(second, "evidence", task_id="TASK-001") == 2
        assert count_rows(second, "location_events", task_id="TASK-001") == 2
        assert sorted(p.name for p in upload_dir.iterdir()) == files_before

        # Idempotency survives the restart.
        replay = second.post(
            f"{API}/TASK-001/completion", json=claim,
            headers={**AUTH, "Idempotency-Key": "restart-key"},
        )
        assert replay.status_code == 200
        assert replay.json()["submission"] == submitted

        conflict = second.post(
            f"{API}/TASK-001/completion", json=dict(claim, notes="changed"),
            headers={**AUTH, "Idempotency-Key": "restart-key"},
        )
        assert conflict.status_code == 409
        assert count_rows(second, "completion_submissions") == 1


def test_evidence_duplicate_detected_after_restart(clean_database,
                                                   upload_dir):
    with TestClient(app) as first:
        post_action(first, "TASK-001", "accept")
        original = upload(first, "TASK-001").json()["evidence"]

    with TestClient(app) as second:
        again = upload(second, "TASK-001")

    assert again.json()["duplicate"] is True
    assert again.json()["evidence"]["evidence_id"] == original["evidence_id"]
    assert len(list(upload_dir.iterdir())) == 1


# ---------------------------------------------------------------------------
# Constraints
# ---------------------------------------------------------------------------

async def _expect_integrity_error(database, sql: str, params: dict) -> None:
    with pytest.raises(IntegrityError):
        async with database.unit_of_work() as uow:
            await uow.session.execute(text(sql), params)


INSERT_LOCATION = (
    "INSERT INTO location_events (location_event_id, task_id, worker_id, "
    "event_type, capture_status, latitude, longitude, accuracy_meters, "
    "received_at_server) VALUES (:id, :task, :worker, :event_type, "
    ":capture_status, :lat, :lon, :acc, now())"
)


def location_params(**overrides) -> dict:
    params = {"id": uuid4(), "task": "TASK-001", "worker": "worker-001",
              "event_type": "ARRIVAL", "capture_status": "CAPTURED",
              "lat": 10.0, "lon": 10.0, "acc": 5.0}
    params.update(overrides)
    return params


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "overrides",
    [
        {"lat": math.nan}, {"lat": math.inf}, {"lat": -math.inf},
        {"lat": 90.5}, {"lon": math.nan}, {"lon": 180.5},
        {"acc": math.nan}, {"acc": math.inf}, {"acc": 0.0}, {"acc": -1.0},
        {"event_type": "DEPARTURE"}, {"capture_status": "GUESSED"},
        {"lat": None},
        {"capture_status": "UNAVAILABLE"},
        {"acc": None},
        {"task": "NO-SUCH-TASK"}, {"worker": "ghost"},
    ],
    ids=["nan-lat", "inf-lat", "neg-inf-lat", "lat-range", "nan-lon",
         "lon-range", "nan-acc", "inf-acc", "zero-acc", "neg-acc",
         "event-type", "capture-status", "captured-missing-lat",
         "unavailable-with-coords", "captured-missing-accuracy",
         "fk-task", "fk-worker"],
)
async def test_location_constraints(database, overrides):
    await _expect_integrity_error(database, INSERT_LOCATION,
                                  location_params(**overrides))
    assert await table_count(database, "location_events") == 0


@pytest.mark.asyncio
async def test_valid_location_row_is_accepted(database):
    async with database.unit_of_work() as uow:
        await uow.session.execute(text(INSERT_LOCATION), location_params())

    assert await table_count(database, "location_events") == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("sql", "params"),
    [
        ("UPDATE tasks SET status = 'DONE' WHERE task_id = 'TASK-001'", {}),
        ("UPDATE tasks SET priority = 'URGENT'", {}),
        ("UPDATE tasks SET latitude = 'NaN'::float8", {}),
        ("UPDATE tasks SET longitude = 'Infinity'::float8", {}),
        ("UPDATE tasks SET assigned_worker_id = 'ghost'", {}),
        # A submitted task must reference its submission, and vice versa.
        ("UPDATE tasks SET status = 'COMPLETION_SUBMITTED'", {}),
        ("UPDATE tasks SET completion_submission_id = :id", {"id": uuid4()}),
        ("UPDATE checklist_steps SET status = 'SKIPPED'", {}),
        ("UPDATE checklist_steps SET position = 0", {}),
        ("INSERT INTO checklist_steps VALUES ('NOPE', 'S', 0, 't', true, "
         "'PENDING', NULL, now())", {}),
        ("INSERT INTO workers (worker_id, display_name) VALUES "
         "('worker-001', 'Duplicate')", {}),
        ("INSERT INTO workers (worker_id, display_name) VALUES ('', 'x')",
         {}),
    ],
    ids=["task-status", "priority", "task-nan-lat", "task-inf-lon",
         "task-worker-fk", "submitted-without-submission",
         "submission-ref-fk", "step-status", "step-position-unique",
         "step-task-fk", "worker-pk", "worker-empty-id"],
)
async def test_task_and_checklist_constraints(database, sql, params):
    await _expect_integrity_error(database, sql, params)

    assert await table_count(database, "tasks") == 1
    async with database.unit_of_work() as uow:
        task = await uow.tasks.get_for_worker("TASK-001", "worker-001")
    assert task.status == TaskStatus.ASSIGNED
    assert task.location.latitude == 23.2599


INSERT_EVIDENCE = (
    "INSERT INTO evidence VALUES (:id, :task, 'worker-001', :type, :key, "
    "'x.png', :mime, :size, :sha, 'STORED', now())"
)


def evidence_params(**overrides) -> dict:
    params = {"id": uuid4(), "task": "TASK-001", "type": "BEFORE",
              "key": f"{uuid4().hex}.png", "mime": "image/png", "size": 10,
              "sha": "a" * 64}
    params.update(overrides)
    return params


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "overrides",
    [
        {"type": "DURING"}, {"mime": "image/gif"}, {"size": 0},
        {"sha": "Z" * 64}, {"sha": "abc"}, {"task": "NO-SUCH-TASK"},
    ],
    ids=["type", "mime", "size", "sha-not-hex", "sha-length", "fk-task"],
)
async def test_evidence_constraints(database, overrides):
    await _expect_integrity_error(database, INSERT_EVIDENCE,
                                  evidence_params(**overrides))
    assert await table_count(database, "evidence") == 0


@pytest.mark.asyncio
async def test_evidence_uniqueness(database):
    first = evidence_params()

    async with database.unit_of_work() as uow:
        await uow.session.execute(text(INSERT_EVIDENCE), first)

    # Same content, type, task and worker.
    await _expect_integrity_error(database, INSERT_EVIDENCE,
                                  evidence_params())
    # Same storage key.
    await _expect_integrity_error(
        database, INSERT_EVIDENCE,
        evidence_params(key=first["key"], sha="b" * 64),
    )

    # Same content as a different evidence type is allowed.
    async with database.unit_of_work() as uow:
        await uow.session.execute(text(INSERT_EVIDENCE),
                                  evidence_params(type="AFTER"))

    assert await table_count(database, "evidence") == 2


def test_task_cannot_reference_another_tasks_location(client):
    from app.tests.conftest import add_task, db_call, make_task

    add_task(client, make_task("MINE-2", status=TaskStatus.ACCEPTED))
    event = client.post(f"{API}/MINE-2/arrival",
                        json=location_payload("ARRIVAL"), headers=AUTH)
    foreign_id = UUID(event.json()["location_event"]["location_event_id"])

    async def point_task_001_at_foreign_event(uow):
        await uow.session.execute(
            text("UPDATE tasks SET arrival_location_event_id = :id "
                 "WHERE task_id = 'TASK-001'"),
            {"id": foreign_id},
        )

    with pytest.raises(IntegrityError):
        db_call(client, point_task_001_at_foreign_event)


def test_submission_cannot_link_another_tasks_evidence(client):
    from app.tests.conftest import add_task, db_call, make_task

    add_task(client, make_task("MINE-2", status=TaskStatus.ACCEPTED))
    foreign = upload(client, "MINE-2", "AFTER").json()["evidence"]
    claim = prepare_for_completion(client)
    client.post(f"{API}/TASK-001/completion", json=claim,
                headers={**AUTH, "Idempotency-Key": "k"})

    async def link_foreign_evidence(uow):
        await uow.session.execute(
            text("INSERT INTO completion_submission_evidence "
                 "SELECT submission_id, :evidence, task_id, 99 "
                 "FROM completion_submissions WHERE task_id = 'TASK-001'"),
            {"evidence": UUID(foreign["evidence_id"])},
        )

    with pytest.raises(IntegrityError):
        db_call(client, link_foreign_evidence)


def test_one_submission_per_task(client):
    claim = prepare_for_completion(client)
    client.post(f"{API}/TASK-001/completion", json=claim,
                headers={**AUTH, "Idempotency-Key": "k"})

    async def second_submission(uow):
        await uow.session.execute(
            text("INSERT INTO completion_submissions VALUES "
                 "(:id, 'TASK-001', 'worker-001', NULL, NULL, "
                 "'SUBMITTED_FOR_VERIFICATION', now())"),
            {"id": uuid4()},
        )

    from app.tests.conftest import db_call

    with pytest.raises(IntegrityError):
        db_call(client, second_submission)

    assert count_rows(client, "completion_submissions") == 1


@pytest.mark.asyncio
async def test_blank_idempotency_key_rejected_by_database(database):
    await _expect_integrity_error(
        database,
        "INSERT INTO idempotency_records (task_id, worker_id, "
        "idempotency_key, request_hash, submission_id) VALUES "
        "('TASK-001', 'worker-001', '   ', :hash, :id)",
        {"hash": "a" * 64, "id": uuid4()},
    )


# ---------------------------------------------------------------------------
# Rollback
# ---------------------------------------------------------------------------

def test_location_reference_failure_rolls_back_event(client, monkeypatch):
    from app.repositories.task_repository import TaskRepository

    post_action(client, "TASK-001", "accept")

    async def failing_reference(self, *_args, **_kwargs):
        raise RuntimeError("simulated failure after event insert")

    monkeypatch.setattr(TaskRepository, "set_task_references",
                        failing_reference)

    with pytest.raises(RuntimeError):
        client.post(f"{API}/TASK-001/arrival",
                    json=location_payload("ARRIVAL"), headers=AUTH)

    assert count_rows(client, "location_events") == 0


def test_failed_completion_validation_leaves_no_rows(client):
    claim = prepare_for_completion(client)
    claim["evidence_ids"][0] = str(uuid4())

    response = client.post(f"{API}/TASK-001/completion", json=claim,
                           headers={**AUTH, "Idempotency-Key": "k"})

    assert response.status_code == 422
    for table in ("completion_submissions", "completion_submission_evidence",
                  "completion_submission_steps", "idempotency_records"):
        assert count_rows(client, table) == 0, table


def test_failed_location_save_leaves_task_unchanged(client, monkeypatch):
    post_action(client, "TASK-001", "accept")

    async def failing_save(self, _record):
        raise RuntimeError("simulated insert failure")

    monkeypatch.setattr(LocationRepository, "save", failing_save)

    with pytest.raises(RuntimeError):
        client.post(f"{API}/TASK-001/arrival",
                    json=location_payload("ARRIVAL"), headers=AUTH)

    task = client.get(f"{API}/TASK-001", headers=AUTH).json()
    assert task["arrival_location_event_id"] is None


# ---------------------------------------------------------------------------
# Evidence file consistency tools
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_orphan_check_reports_only_unreferenced_old_files(database,
                                                                upload_dir):
    import os
    import time

    from app.db.check_orphans import find_orphans

    await force_status(database, "TASK-001", TaskStatus.ACCEPTED)
    storage = ImageStorage()
    service = EvidenceService(database.unit_of_work, storage)
    record, _ = await service.upload(
        "TASK-001", "worker-001", EvidenceType.BEFORE,
        UploadFile(filename="a.png", file=BytesIO(make_image()),
                   headers={"content-type": "image/png"}),
    )

    old_orphan = await storage.save(b"orphan", ".png")
    new_orphan = await storage.save(b"recent", ".png")
    two_hours_ago = time.time() - 7200
    for key in (old_orphan, record.storage_key):
        os.utime(storage.resolve(key), (two_hours_ago, two_hours_ago))

    orphans = await find_orphans(database, storage, min_age_seconds=3600)

    assert orphans == [old_orphan]
    # Reporting never deletes anything.
    assert len(list(upload_dir.iterdir())) == 3
    assert new_orphan in storage.list_keys()


@pytest.mark.asyncio
async def test_orphan_delete_removes_only_old_unreferenced_files(database,
                                                                 upload_dir):
    import os
    import time

    from app.db.check_orphans import run

    await force_status(database, "TASK-001", TaskStatus.ACCEPTED)
    storage = ImageStorage()
    record, _ = await EvidenceService(database.unit_of_work, storage).upload(
        "TASK-001", "worker-001", EvidenceType.BEFORE,
        UploadFile(filename="a.png", file=BytesIO(make_image()),
                   headers={"content-type": "image/png"}),
    )
    old_orphan = await storage.save(b"orphan", ".png")
    new_orphan = await storage.save(b"recent", ".png")
    two_hours_ago = time.time() - 7200
    for key in (old_orphan, record.storage_key):
        os.utime(storage.resolve(key), (two_hours_ago, two_hours_ago))

    deleted = await run(delete=True, min_age_minutes=60)

    assert deleted == [old_orphan]
    assert sorted(storage.list_keys()) == sorted([record.storage_key,
                                                  new_orphan])


@pytest.mark.asyncio
async def test_seed_command_is_idempotent(database):
    from app.db.seed import run

    # clean_database has already seeded; the command must not duplicate.
    assert await run(settings) is False
    assert await table_count(database, "tasks") == 1
    assert await table_count(database, "workers") == 1


def test_startup_seeding_follows_configuration(clean_database, monkeypatch):
    from app.tests.conftest import db_call

    async def remove_demo_data(uow):
        await uow.session.execute(text("DELETE FROM tasks"))
        await uow.session.execute(text("DELETE FROM workers"))

    with TestClient(app) as client:
        db_call(client, remove_demo_data)

    # Seeding disabled: startup leaves the empty database alone.
    with TestClient(app) as client:
        assert client.get(API, headers=AUTH).json() == {"tasks": []}

    monkeypatch.setattr(settings, "seed_demo_data", True)

    for _ in range(2):  # Restarting must not duplicate demo data.
        with TestClient(app) as client:
            tasks = client.get(API, headers=AUTH).json()["tasks"]
            assert [t["task_id"] for t in tasks] == ["TASK-001"]
            assert count_rows(client, "checklist_steps") == 3

    # Never seeds in production, even when enabled.
    with TestClient(app) as client:
        db_call(client, remove_demo_data)
    monkeypatch.setattr(settings, "app_env", "production")
    with TestClient(app) as client:
        assert count_rows(client, "tasks") == 0


@pytest.mark.asyncio
async def test_concurrent_seeding_inserts_demo_task_once(database,
                                                         monkeypatch):
    from app.db.seed import seed_demo_data
    from app.repositories.task_repository import TaskRepository

    # Worker present, task missing: concurrent seeders (e.g. several
    # uvicorn workers starting together) must not collide on TASK-001.
    async with database.unit_of_work() as uow:
        await uow.session.execute(text("DELETE FROM tasks"))

    # Force the worst interleaving: every seeder finishes its "does the
    # task exist?" check before any of them inserts. The timeout lets a
    # correctly serialised implementation proceed instead of deadlocking.
    barrier = asyncio.Barrier(4)
    original_exists = TaskRepository.task_exists

    async def exists_then_wait(self, task_id):
        found = await original_exists(self, task_id)
        try:
            await asyncio.wait_for(barrier.wait(), timeout=0.5)
        except (TimeoutError, asyncio.BrokenBarrierError):
            pass
        return found

    monkeypatch.setattr(TaskRepository, "task_exists", exists_then_wait)

    async def seed():
        async with database.unit_of_work() as uow:
            return await seed_demo_data(uow)

    results = await asyncio.gather(*(seed() for _ in range(4)))

    assert sorted(results) == [False, False, False, True]
    assert await table_count(database, "tasks") == 1
    assert await table_count(database, "checklist_steps") == 3


def test_seed_refuses_production(monkeypatch):
    from app.db.seed import run

    monkeypatch.setattr(settings, "app_env", "production")

    with pytest.raises(SystemExit, match="production"):
        asyncio.run(run(settings))


# ---------------------------------------------------------------------------
# Concurrency
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_concurrent_identical_uploads_store_one_record(database,
                                                             upload_dir):
    await force_status(database, "TASK-001", TaskStatus.ACCEPTED)
    service = EvidenceService(database.unit_of_work, ImageStorage())
    content = make_image()

    def new_upload():
        return UploadFile(filename="a.png", file=BytesIO(content),
                          headers={"content-type": "image/png"})

    results = await asyncio.gather(*(
        service.upload("TASK-001", "worker-001", EvidenceType.BEFORE,
                       new_upload())
        for _ in range(4)
    ))

    assert len({record.evidence_id for record, _ in results}) == 1
    assert sum(1 for _, duplicate in results if not duplicate) == 1
    assert await table_count(database, "evidence") == 1
    assert len(list(upload_dir.iterdir())) == 1


@pytest.mark.asyncio
async def test_concurrent_checklist_updates_are_serialised(database):
    from app.schemas.checklist import ChecklistStatus, ChecklistStepUpdate
    from app.services.field_work_service import FieldWorkService
    from app.services.task_state_service import TaskStateService

    await force_status(database, "TASK-001", TaskStatus.IN_PROGRESS)
    service = FieldWorkService(database.unit_of_work, TaskStateService())

    await asyncio.gather(*(
        service.update_checklist(
            "TASK-001", "worker-001", step,
            ChecklistStepUpdate(status=ChecklistStatus.COMPLETED,
                                note=f"note {step}"),
        )
        for step in ("STEP-001", "STEP-002", "STEP-003")
    ))

    async with database.unit_of_work() as uow:
        records = await uow.tasks.get_checklist_records("TASK-001")

    assert [r.status for r in records] == [ChecklistStatus.COMPLETED] * 3
    assert [r.note for r in records] == [
        "note STEP-001", "note STEP-002", "note STEP-003",
    ]
