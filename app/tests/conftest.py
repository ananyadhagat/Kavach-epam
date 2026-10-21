import asyncio
from collections.abc import Awaitable, Callable
from io import BytesIO
from pathlib import Path
from typing import TypeVar

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from PIL import Image
from pydantic import SecretStr
from sqlalchemy import func, select, text, update
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from app.config import BASE_DIR, settings
from app.db.database import Database, UnitOfWork, parse_database_url
from app.db.models import (
    APP_TABLES,
    ChecklistStepRow,
    IdempotencyRecordRow,
    TaskRow,
)
from app.db.seed import seed_demo_data
from app.main import app
from app.schemas.worker_task import (
    ChecklistDefinition,
    TaskLocation,
    TaskStatus,
    WorkerTask,
)

DEMO_TOKEN = "dev-worker-token"
AUTH = {"Authorization": f"Bearer {DEMO_TOKEN}"}
WORKER_ID = "worker-001"
OTHER_WORKER_ID = "worker-002"
API = "/api/v1/worker/tasks"

T = TypeVar("T")

# Captured before any test changes settings.
_CONFIGURED_TEST_URL = settings.test_database_url
_CONFIGURED_APP_URL = settings.database_url


# ---------------------------------------------------------------------------
# Test-database safety
# ---------------------------------------------------------------------------

class UnsafeTestDatabaseError(RuntimeError):
    pass


def assert_safe_test_database(test_url: URL, app_url: URL | None) -> None:
    """Refuse any database that is not clearly a disposable test database."""
    if not (test_url.database or "").endswith("_test"):
        raise UnsafeTestDatabaseError(
            "TEST_DATABASE_URL must name a database ending in '_test'; "
            f"got '{test_url.database}'. Refusing to modify it."
        )

    if app_url is not None and (
        (test_url.host, test_url.port, test_url.database)
        == (app_url.host, app_url.port, app_url.database)
    ):
        raise UnsafeTestDatabaseError(
            "TEST_DATABASE_URL points at the same database as DATABASE_URL. "
            "Refusing to modify it."
        )


def require_test_database_url() -> str:
    if _CONFIGURED_TEST_URL is None:
        pytest.fail(
            "TEST_DATABASE_URL is not set. Database-backed tests require a "
            "PostgreSQL database whose name ends in '_test'. See README.md "
            "('Running tests').",
            pytrace=False,
        )

    raw = _CONFIGURED_TEST_URL.get_secret_value()
    app_url = (
        parse_database_url(_CONFIGURED_APP_URL.get_secret_value())
        if _CONFIGURED_APP_URL is not None else None
    )

    try:
        assert_safe_test_database(parse_database_url(raw), app_url)
    except UnsafeTestDatabaseError as exc:
        pytest.fail(str(exc), pytrace=False)

    return raw


async def _reset_database(raw_url: str) -> None:
    engine = create_async_engine(parse_database_url(raw_url),
                                 poolclass=NullPool)

    try:
        async with engine.begin() as connection:
            # Second, server-side check right before the destructive step.
            name = await connection.scalar(text("SELECT current_database()"))

            if not name.endswith("_test"):
                raise UnsafeTestDatabaseError(
                    f"Connected database '{name}' is not a test database."
                )

            await connection.execute(
                text(f"TRUNCATE TABLE {', '.join(APP_TABLES)} CASCADE")
            )

        async with Database(engine).unit_of_work() as uow:
            await seed_demo_data(uow)
    finally:
        await engine.dispose()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def isolated_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    # Every test gets its own upload directory and known settings, so a
    # local .env or real uploads can never be read or modified by tests.
    upload_dir = tmp_path / "uploads"
    monkeypatch.setattr(settings, "image_storage_dir", upload_dir)
    monkeypatch.setattr(settings, "app_env", "test")
    monkeypatch.setattr(settings, "demo_worker_token", SecretStr(DEMO_TOKEN))
    monkeypatch.setattr(settings, "demo_worker_id", WORKER_ID)
    monkeypatch.setattr(settings, "require_arrival_location", False)
    monkeypatch.setattr(settings, "max_gps_accuracy_meters", 100.0)
    monkeypatch.setattr(settings, "max_image_size_bytes", 5 * 1024 * 1024)
    monkeypatch.setattr(settings, "seed_demo_data", False)
    # Never let a test reach the development database.
    monkeypatch.setattr(settings, "database_url", None)
    return upload_dir


@pytest.fixture
def upload_dir(isolated_settings: Path) -> Path:
    return isolated_settings


@pytest.fixture(scope="session")
def migrated_test_database() -> str:
    """Bring the test database schema up to date (non-destructive)."""
    from alembic import command
    from alembic.config import Config

    raw = require_test_database_url()
    config = Config(str(BASE_DIR / "alembic.ini"))
    config.attributes["database_url"] = raw
    config.attributes["configure_logger"] = False
    command.upgrade(config, "head")
    return raw


@pytest.fixture
def clean_database(migrated_test_database: str,
                   monkeypatch: pytest.MonkeyPatch) -> str:
    """Empty every table and reseed TASK-001 before the test."""
    asyncio.run(_reset_database(migrated_test_database))
    monkeypatch.setattr(settings, "database_url",
                        SecretStr(migrated_test_database))
    return migrated_test_database


@pytest.fixture
def client(clean_database: str):
    # Entering the context runs the lifespan, connecting to PostgreSQL.
    with TestClient(app) as test_client:
        yield test_client


@pytest_asyncio.fixture
async def database(clean_database: str):
    db = await Database.connect(settings)

    try:
        yield db
    finally:
        await db.dispose()


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------

def db_call(client: TestClient,
            operation: Callable[[UnitOfWork], Awaitable[T]]) -> T:
    """Run an operation in one transaction on the app's event loop."""
    async def runner() -> T:
        async with client.app.state.database.unit_of_work() as uow:
            return await operation(uow)

    return client.portal.call(runner)


async def force_status(database: Database, task_id: str,
                       status: TaskStatus) -> None:
    """Test-only shortcut to put a task into a given state."""
    async with database.unit_of_work() as uow:
        await uow.session.execute(
            update(TaskRow.__table__)
            .where(TaskRow.__table__.c.task_id == task_id)
            .values(status=status.value)
        )


async def get_status(database: Database, task_id: str) -> TaskStatus:
    async with database.unit_of_work() as uow:
        value = await uow.session.scalar(
            select(TaskRow.__table__.c.status).where(
                TaskRow.__table__.c.task_id == task_id
            )
        )
    return TaskStatus(value)


def task_status(client: TestClient, task_id: str) -> str:
    async def operation(uow: UnitOfWork) -> str:
        return await uow.session.scalar(
            select(TaskRow.__table__.c.status).where(
                TaskRow.__table__.c.task_id == task_id
            )
        )

    return db_call(client, operation)


def checklist_status(client: TestClient, task_id: str, step_id: str):
    async def operation(uow: UnitOfWork):
        steps = ChecklistStepRow.__table__
        return await uow.session.scalar(
            select(steps.c.status).where(steps.c.task_id == task_id,
                                         steps.c.step_id == step_id)
        )

    return db_call(client, operation)


def count_rows(client: TestClient, table: str, **filters) -> int:
    async def operation(uow: UnitOfWork) -> int:
        where = " AND ".join(f"{column} = :{column}" for column in filters)
        sql = f"SELECT count(*) FROM {table}"
        return await uow.session.scalar(
            text(sql + (f" WHERE {where}" if where else "")), filters
        )

    return db_call(client, operation)


def evidence_records(client: TestClient) -> dict:
    async def operation(uow: UnitOfWork):
        rows = await uow.session.execute(text("SELECT task_id FROM evidence"))
        records = {}
        for task_id in {row.task_id for row in rows}:
            for record in await uow.evidence.list_for_task(task_id):
                records[record.evidence_id] = record
        return records

    return db_call(client, operation)


def location_records(client: TestClient) -> dict:
    async def operation(uow: UnitOfWork):
        rows = await uow.session.execute(
            text("SELECT DISTINCT task_id FROM location_events")
        )
        records = {}
        for row in rows:
            for record in await uow.locations.list_for_task(row.task_id):
                records[record.location_event_id] = record
        return records

    return db_call(client, operation)


def idempotency_records(client: TestClient) -> dict:
    """Maps (task_id, worker_id, key) to the stored submission."""
    async def operation(uow: UnitOfWork):
        table = IdempotencyRecordRow.__table__
        rows = (await uow.session.execute(select(table))).all()
        return {
            (row.task_id, row.worker_id, row.idempotency_key):
                await uow.completions.get(str(row.submission_id))
            for row in rows
        }

    return db_call(client, operation)


async def table_count(database: Database, table: str) -> int:
    async with database.unit_of_work() as uow:
        return await uow.session.scalar(
            select(func.count()).select_from(text(table))
        )


# ---------------------------------------------------------------------------
# Request helpers
# ---------------------------------------------------------------------------

def make_image(fmt: str = "PNG", size: tuple[int, int] = (10, 10),
               color: str = "white") -> bytes:
    buffer = BytesIO()
    Image.new("RGB", size, color).save(buffer, format=fmt)
    return buffer.getvalue()


def make_task(
    task_id: str,
    worker_id: str = WORKER_ID,
    steps: tuple[str, ...] = ("S1",),
    optional_steps: tuple[str, ...] = (),
    status: TaskStatus = TaskStatus.ASSIGNED,
) -> WorkerTask:
    checklist = [
        ChecklistDefinition(step_id=s, title=f"Step {s}") for s in steps
    ] + [
        ChecklistDefinition(step_id=s, title=f"Step {s}", required=False)
        for s in optional_steps
    ]

    return WorkerTask(
        task_id=task_id,
        incident_id=f"INC-{task_id}",
        assigned_worker_id=worker_id,
        title=f"Task {task_id}",
        description="Test task.",
        location=TaskLocation(latitude=1.0, longitude=2.0, address="Test"),
        checklist=checklist,
        status=status,
    )


async def add_task_with_worker(uow: UnitOfWork, task: WorkerTask):
    await uow.tasks.add_worker(task.assigned_worker_id,
                               f"Worker {task.assigned_worker_id}")
    return await uow.tasks.add_task(task)


def add_task(client: TestClient, task: WorkerTask) -> WorkerTask:
    return db_call(client, lambda uow: add_task_with_worker(uow, task))


def upload(client: TestClient, task_id: str, evidence_type: str = "BEFORE",
           content: bytes | None = None, content_type: str = "image/png",
           filename: str = "photo.png", headers: dict | None = None):
    if content is None:
        content = make_image("PNG", color="white" if evidence_type == "BEFORE"
                             else "black")

    return client.post(
        f"{API}/{task_id}/evidence",
        data={"evidence_type": evidence_type},
        files={"file": (filename, content, content_type)},
        headers=AUTH if headers is None else headers,
    )


def location_payload(event_type: str = "ARRIVAL", **overrides) -> dict:
    payload = {
        "event_type": event_type,
        "capture_status": "CAPTURED",
        "latitude": 23.2599,
        "longitude": 77.4126,
        "accuracy_meters": 10.0,
    }
    payload.update(overrides)
    return payload


def post_action(client: TestClient, task_id: str, action: str):
    if action == "reject":
        return client.post(
            f"{API}/{task_id}/reject", json={"action": "REJECT"}, headers=AUTH
        )

    return client.post(f"{API}/{task_id}/{action}", headers=AUTH)


def prepare_for_completion(client: TestClient, task_id: str = "TASK-001",
                           with_completion_location: bool = True) -> dict:
    """Drive a task through the API to a state where completion is valid."""
    assert post_action(client, task_id, "accept").status_code == 200

    before = upload(client, task_id, "BEFORE")
    assert before.status_code == 200, before.text
    assert post_action(client, task_id, "start").status_code == 200

    task = client.get(f"{API}/{task_id}", headers=AUTH).json()

    for step in task["checklist"]:
        response = client.patch(
            f"{API}/{task_id}/checklist/{step['step_id']}",
            json={"status": "COMPLETED"},
            headers=AUTH,
        )
        assert response.status_code == 200, response.text

    after = upload(client, task_id, "AFTER")
    assert after.status_code == 200, after.text

    claim = {
        "checklist_step_ids": [s["step_id"] for s in task["checklist"]],
        "evidence_ids": [
            before.json()["evidence"]["evidence_id"],
            after.json()["evidence"]["evidence_id"],
        ],
    }

    if with_completion_location:
        location = client.post(
            f"{API}/{task_id}/completion-location",
            json=location_payload("COMPLETION"),
            headers=AUTH,
        )
        assert location.status_code == 200, location.text
        claim["completion_location_event_id"] = (
            location.json()["location_event"]["location_event_id"]
        )

    return claim
