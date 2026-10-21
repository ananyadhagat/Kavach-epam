"""Insert the demo worker and TASK-001 if they are missing.

Usage:  python -m app.db.seed

Never updates or deletes existing rows, and refuses to run in production.
"""

import asyncio

from sqlalchemy import text

from app.config import Settings, get_settings
from app.db.database import Database, UnitOfWork
from app.schemas.worker_task import (
    ChecklistDefinition,
    TaskLocation,
    TaskPriority,
    WorkerTask,
)

DEMO_WORKER_ID = "worker-001"
DEMO_TASK_ID = "TASK-001"
# Arbitrary application-wide key for pg_advisory_xact_lock.
SEED_LOCK_KEY = 7_412_026_001


def demo_task() -> WorkerTask:
    return WorkerTask(
        task_id=DEMO_TASK_ID,
        incident_id="INC-001",
        assigned_worker_id=DEMO_WORKER_ID,
        title="Clean overflowing dustbin",
        description="Clean the area near the main gate.",
        priority=TaskPriority.HIGH,
        location=TaskLocation(
            latitude=23.2599,
            longitude=77.4126,
            address="Main Gate",
        ),
        checklist=[
            ChecklistDefinition(
                step_id="STEP-001",
                title="Inspect the affected area",
            ),
            ChecklistDefinition(
                step_id="STEP-002",
                title="Collect scattered waste",
            ),
            ChecklistDefinition(
                step_id="STEP-003",
                title="Clean and inspect the area",
            ),
        ],
    )


async def seed_demo_data(uow: UnitOfWork) -> bool:
    """Returns True when the demo task was inserted."""
    # Serialise concurrent seeders (e.g. several workers starting at once);
    # the lock is released automatically when the transaction ends.
    await uow.session.execute(
        text("SELECT pg_advisory_xact_lock(:key)"), {"key": SEED_LOCK_KEY}
    )
    await uow.tasks.add_worker(DEMO_WORKER_ID, "Demo Worker")

    if await uow.tasks.task_exists(DEMO_TASK_ID):
        return False

    await uow.tasks.add_task(demo_task())
    return True


async def run(settings: Settings) -> bool:
    if settings.app_env == "production":
        raise SystemExit("Refusing to seed demo data when APP_ENV=production.")

    database = await Database.connect(settings)

    try:
        async with database.unit_of_work() as uow:
            return await seed_demo_data(uow)
    finally:
        await database.dispose()


def main() -> None:
    inserted = asyncio.run(run(get_settings()))
    print("Demo data inserted." if inserted else "Demo data already present.")


if __name__ == "__main__":
    main()
