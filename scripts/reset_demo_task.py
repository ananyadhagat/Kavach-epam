"""Safely inspect or reset the local TASK-001 demo execution.

Dry-run is the default. Execution requires APP_ENV=development,
KAVACH_DEMO_RESET_ENABLED=true, KAVACH_DEMO_RESET_LOCAL_ONLY=true,
--execute, and typing the exact confirmation phrase when prompted.
"""

import argparse
import asyncio
import hashlib
import json
import sys
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID

# Allow direct invocation as `python scripts/reset_demo_task.py` from the
# repository root while keeping imports rooted at this checkout.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine

from app.config import Settings, get_settings
from app.db.database import parse_database_url

TASK_ID = "TASK-001"
EXPECTED_WORKER_ID = "worker-001"
CONFIRMATION = "RESET TASK-001"
RESETTABLE_STATUSES = {
    "ACCEPTED",
    "IN_PROGRESS",
    "PAUSED",
    "BLOCKED",
    "COMPLETION_SUBMITTED",
}


class ResetSafetyError(RuntimeError):
    """A reset precondition failed; no task-scoped mutation is permitted."""


class PostCommitCleanupError(ResetSafetyError):
    """The database reset committed, but verified file cleanup did not finish."""


@dataclass(frozen=True)
class EvidenceFile:
    evidence_id: str
    storage_key: str
    path: Path
    sha256: str


@dataclass
class ResetPlan:
    task: dict[str, Any]
    submissions: list[dict[str, Any]]
    submission_evidence: list[dict[str, Any]]
    submission_steps: list[dict[str, Any]]
    idempotency_records: list[dict[str, Any]]
    evidence: list[dict[str, Any]]
    location_events: list[dict[str, Any]]
    blockers: list[dict[str, Any]]
    checklist: list[dict[str, Any]]
    evidence_files: list[EvidenceFile]

    def summary(self) -> dict[str, Any]:
        return {
            "task_id": self.task["task_id"],
            "status": self.task["status"],
            "assigned_worker_id": self.task["assigned_worker_id"],
            "would_reset_status_to": "ACCEPTED",
            "would_clear_references": [
                "arrival_location_event_id",
                "completion_location_event_id",
                "completion_submission_id",
            ],
            "submission_ids": [str(row["submission_id"]) for row in self.submissions],
            "idempotency_count": len(self.idempotency_records),
            "submission_evidence_links": len(self.submission_evidence),
            "submission_checklist_links": len(self.submission_steps),
            "evidence": [
                {
                    "evidence_id": str(row["evidence_id"]),
                    "type": row["evidence_type"],
                    "storage_key": row["storage_key"],
                    "sha256": row["sha256"],
                }
                for row in self.evidence
            ],
            "location_event_ids": [
                str(row["location_event_id"]) for row in self.location_events
            ],
            "blocker_ids": [str(row["blocker_id"]) for row in self.blockers],
            "checklist_step_ids_preserved": [
                row["step_id"] for row in self.checklist
            ],
            "files": [
                {"path": str(item.path), "sha256": item.sha256}
                for item in self.evidence_files
            ],
        }


def validate_execution_guard(settings: Settings, database_name: str) -> None:
    if settings.app_env != "development":
        raise ResetSafetyError("Execution is allowed only when APP_ENV=development.")
    if not settings.kavach_demo_reset_enabled:
        raise ResetSafetyError(
            "Execution is disabled; explicitly set KAVACH_DEMO_RESET_ENABLED=true."
        )
    if not settings.kavach_demo_reset_local_only:
        raise ResetSafetyError(
            "Execution requires explicit local-demo authorization via "
            "KAVACH_DEMO_RESET_LOCAL_ONLY=true."
        )
    if database_name != "kavach":
        raise ResetSafetyError("Refusing to reset any database other than kavach.")


def _id(value: Any) -> str | None:
    return str(value) if value is not None else None


def validate_plan(plan: ResetPlan) -> None:
    task = plan.task
    if task.get("task_id") != TASK_ID:
        raise ResetSafetyError("The locked task is not TASK-001.")
    worker_id = task.get("assigned_worker_id")
    if worker_id != EXPECTED_WORKER_ID:
        raise ResetSafetyError("TASK-001 is not assigned to the expected demo worker.")
    if task.get("status") not in RESETTABLE_STATUSES:
        raise ResetSafetyError("TASK-001 has an unexpected lifecycle status.")
    if any(
        _id(task.get(field)) not in {None, *(str(x) for x in ids)}
        for field, ids in (
            ("arrival_location_event_id", [r["location_event_id"] for r in plan.location_events]),
            ("completion_location_event_id", [r["location_event_id"] for r in plan.location_events]),
            ("completion_submission_id", [r["submission_id"] for r in plan.submissions]),
        )
    ):
        raise ResetSafetyError("A task reference points outside its scoped execution rows.")

    submission_ids = {_id(row["submission_id"]) for row in plan.submissions}
    if len(plan.submissions) > 1:
        raise ResetSafetyError("Unexpected multiple completion submissions for TASK-001.")
    has_submitted_status = task.get("status") == "COMPLETION_SUBMITTED"
    if has_submitted_status != (len(plan.submissions) == 1):
        raise ResetSafetyError(
            "Task lifecycle state and completion-submission count do not match."
        )
    if plan.submissions and _id(task.get("completion_submission_id")) != _id(
        plan.submissions[0]["submission_id"]
    ):
        raise ResetSafetyError("Task completion reference does not match its submission.")
    if any(
        row.get("task_id") != TASK_ID or row.get("worker_id") != worker_id
        for row in plan.submissions
    ):
        raise ResetSafetyError("A completion submission has unexpected ownership.")
    if any(row.get("status") != "COMPLETION_SUBMITTED" for row in plan.submissions):
        raise ResetSafetyError("A completion submission has an unexpected status.")
    location_ids = {_id(row["location_event_id"]) for row in plan.location_events}
    if any(
        row.get("completion_location_event_id") is not None
        and _id(row["completion_location_event_id"]) not in location_ids
        for row in plan.submissions
    ):
        raise ResetSafetyError("A completion submission references an unexpected location event.")
    event_by_id = {
        _id(row["location_event_id"]): row for row in plan.location_events
    }
    for field, event_type in (
        ("arrival_location_event_id", "ARRIVAL"),
        ("completion_location_event_id", "COMPLETION"),
    ):
        reference = _id(task.get(field))
        if reference is not None and (
            reference not in event_by_id
            or event_by_id[reference].get("event_type") != event_type
        ):
            raise ResetSafetyError(
                f"The {field} reference does not identify its expected event type."
            )
    if any(
        row.get("completion_location_event_id") is not None
        and event_by_id[_id(row["completion_location_event_id"])].get("event_type")
        != "COMPLETION"
        for row in plan.submissions
    ):
        raise ResetSafetyError("A submission references a non-completion location event.")
    if any(
        row.get("task_id") != TASK_ID
        or _id(row.get("submission_id")) not in submission_ids
        or _id(row.get("evidence_id"))
        not in {_id(e["evidence_id"]) for e in plan.evidence}
        for row in plan.submission_evidence
    ):
        raise ResetSafetyError("Unexpected completion evidence link or ownership.")
    if any(
        row.get("task_id") != TASK_ID
        or _id(row.get("submission_id")) not in submission_ids
        or row.get("step_id") not in {item["step_id"] for item in plan.checklist}
        for row in plan.submission_steps
    ):
        raise ResetSafetyError("Unexpected completion checklist link.")
    if any(
        row.get("task_id") != TASK_ID
        or row.get("worker_id") != worker_id
        or _id(row.get("submission_id")) not in submission_ids
        for row in plan.idempotency_records
    ):
        raise ResetSafetyError("Unexpected idempotency record ownership or reference.")
    if any(
        row.get("task_id") != TASK_ID or row.get("worker_id") != worker_id
        for row in plan.evidence + plan.location_events + plan.blockers
    ):
        raise ResetSafetyError("An execution record belongs to another task or worker.")
    checklist_ids = {row["step_id"] for row in plan.checklist}
    if any(
        row.get("step_id") is not None and row["step_id"] not in checklist_ids
        for row in plan.blockers
    ):
        raise ResetSafetyError("A blocker references an unexpected checklist step.")
    if any(
        row.get("evidence_type") not in {"BEFORE", "AFTER"}
        or row.get("status") != "STORED"
        for row in plan.evidence
    ):
        raise ResetSafetyError("Unexpected evidence type or status.")
    if any(
        row.get("event_type") not in {"ARRIVAL", "COMPLETION"}
        or row.get("capture_status") not in {"CAPTURED", "INACCURATE", "UNAVAILABLE"}
        for row in plan.location_events
    ):
        raise ResetSafetyError("Unexpected location event type or status.")
    if any(
        row.get("status") not in {"OPEN", "RESOLVED"}
        for row in plan.blockers
    ):
        raise ResetSafetyError("Unexpected blocker status.")
    if any(row.get("status") == "OPEN" for row in plan.blockers):
        raise ResetSafetyError("An open blocker exists; resolve it through the authorized workflow first.")
    if any(
        row.get("assigned_worker_id") != worker_id for row in plan.checklist
    ):
        raise ResetSafetyError("A checklist step is assigned to another worker.")
    if len({file.storage_key for file in plan.evidence_files}) != len(plan.evidence_files):
        raise ResetSafetyError("Duplicate evidence storage key found.")


class PostgresResetTransaction:
    def __init__(self, connection: AsyncConnection, image_root: Path):
        self.connection = connection
        self.image_root = image_root.resolve()

    async def _rows(self, query: str, params: dict[str, Any] | None = None):
        result = await self.connection.execute(text(query), params or {})
        return [dict(row._mapping) for row in result]

    async def inspect(self, lock: bool) -> ResetPlan:
        suffix = " FOR UPDATE" if lock else ""
        tasks = await self._rows(
            """SELECT task_id, incident_id, assigned_worker_id, title, description,
                      priority, status, latitude, longitude, address,
                      arrival_location_event_id, completion_location_event_id,
                      completion_submission_id
               FROM tasks WHERE task_id = :task_id""" + suffix,
            {"task_id": TASK_ID},
        )
        if len(tasks) != 1:
            raise ResetSafetyError("Expected exactly one TASK-001 row.")
        task = tasks[0]
        worker_id = task["assigned_worker_id"]
        if worker_id != EXPECTED_WORKER_ID:
            raise ResetSafetyError("TASK-001 has an unexpected assigned worker.")
        workers = await self._rows(
            "SELECT worker_id FROM workers WHERE worker_id = :worker_id",
            {"worker_id": worker_id},
        )
        if len(workers) != 1:
            raise ResetSafetyError("Expected exactly one assigned worker record.")

        submissions = await self._rows(
            """SELECT submission_id, task_id, worker_id,
                      completion_location_event_id, notes, status, submitted_at
               FROM completion_submissions WHERE task_id = :task_id""" + suffix,
            {"task_id": TASK_ID},
        )
        evidence = await self._rows(
            """SELECT evidence_id, task_id, worker_id, evidence_type, storage_key,
                      original_filename, mime_type, size_bytes, sha256, status, uploaded_at
               FROM evidence WHERE task_id = :task_id ORDER BY evidence_id""" + suffix,
            {"task_id": TASK_ID},
        )
        submission_evidence = await self._rows(
            """SELECT task_id, submission_id, evidence_id, position
               FROM completion_submission_evidence WHERE task_id = :task_id
               ORDER BY submission_id, position""" + suffix,
            {"task_id": TASK_ID},
        )
        submission_steps = await self._rows(
            """SELECT task_id, submission_id, step_id, position
               FROM completion_submission_steps WHERE task_id = :task_id
               ORDER BY submission_id, position""" + suffix,
            {"task_id": TASK_ID},
        )
        idempotency = await self._rows(
            """SELECT task_id, worker_id, idempotency_key, request_hash,
                      submission_id, created_at
               FROM idempotency_records WHERE task_id = :task_id""" + suffix,
            {"task_id": TASK_ID},
        )
        locations = await self._rows(
            """SELECT location_event_id, task_id, worker_id, event_type,
                      capture_status, latitude, longitude, accuracy_meters,
                      captured_at_device, received_at_server
               FROM location_events WHERE task_id = :task_id""" + suffix,
            {"task_id": TASK_ID},
        )
        blockers = await self._rows(
            """SELECT blocker_id, task_id, worker_id, step_id, reason_code,
                      description, status, previous_status, reported_at,
                      resolved_at, resolved_by, resolution_note
               FROM task_blockers WHERE task_id = :task_id""" + suffix,
            {"task_id": TASK_ID},
        )
        checklist = await self._rows(
            """SELECT task_id, step_id, position, title, required,
                      assigned_worker_id, status, note, updated_at, completed_at
               FROM checklist_steps WHERE task_id = :task_id
               ORDER BY position""" + suffix,
            {"task_id": TASK_ID},
        )
        rejections = await self._rows(
            "SELECT task_id, worker_id FROM task_rejections WHERE task_id = :task_id",
            {"task_id": TASK_ID},
        )
        if rejections:
            raise ResetSafetyError("Task rejection history exists; refusing an incomplete reset.")

        submission_ids = [_id(row["submission_id"]) for row in submissions]
        if submission_ids:
            cross_idempotency = await self._rows(
                """SELECT task_id, worker_id, idempotency_key, submission_id
                   FROM idempotency_records
                   WHERE submission_id = ANY(:submission_ids)""" + suffix,
                {"submission_ids": [UUID(value) for value in submission_ids]},
            )
            if len(cross_idempotency) != len(idempotency) or any(
                row["task_id"] != TASK_ID or row["worker_id"] != worker_id
                for row in cross_idempotency
            ):
                raise ResetSafetyError("Submission is referenced by unexpected idempotency rows.")
        if evidence:
            cross_links = await self._rows(
                """SELECT task_id, submission_id, evidence_id
                   FROM completion_submission_evidence
                   WHERE evidence_id = ANY(:evidence_ids)""" + suffix,
                {"evidence_ids": [UUID(_id(row["evidence_id"])) for row in evidence]},
            )
            if len(cross_links) != len(submission_evidence) or any(
                row["task_id"] != TASK_ID
                or _id(row["submission_id"]) not in submission_ids
                for row in cross_links
            ):
                raise ResetSafetyError("Evidence has unexpected completion links.")

        evidence_files: list[EvidenceFile] = []
        for row in evidence:
            key = row["storage_key"]
            path = (self.image_root / key).resolve()
            if path.parent != self.image_root or path.name != key:
                raise ResetSafetyError("Evidence storage key escapes the configured directory.")
            if not path.is_file():
                raise ResetSafetyError(f"Expected evidence file is missing: {key}")
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            if digest != row["sha256"]:
                raise ResetSafetyError(f"Evidence file hash mismatch: {key}")
            evidence_files.append(
                EvidenceFile(_id(row["evidence_id"]), key, path, digest)
            )

        plan = ResetPlan(
            task=task,
            submissions=submissions,
            submission_evidence=submission_evidence,
            submission_steps=submission_steps,
            idempotency_records=idempotency,
            evidence=evidence,
            location_events=locations,
            blockers=blockers,
            checklist=checklist,
            evidence_files=evidence_files,
        )
        validate_plan(plan)
        return plan

    async def apply(self, plan: ResetPlan) -> None:
        worker_id = plan.task["assigned_worker_id"]
        preserved_task_fields = (
            "task_id",
            "incident_id",
            "assigned_worker_id",
            "title",
            "description",
            "priority",
            "latitude",
            "longitude",
            "address",
        )
        result = await self.connection.execute(
            text(
                """UPDATE tasks SET status = 'ACCEPTED',
                          arrival_location_event_id = NULL,
                          completion_location_event_id = NULL,
                          completion_submission_id = NULL,
                          updated_at = now()
                   WHERE task_id = :task_id AND assigned_worker_id = :worker_id"""
            ),
            {"task_id": TASK_ID, "worker_id": worker_id},
        )
        self._expect_count(result.rowcount, 1, "TASK-001 update")

        for row in plan.idempotency_records:
            result = await self.connection.execute(
                text(
                    """DELETE FROM idempotency_records
                       WHERE task_id = :task_id AND worker_id = :worker_id
                         AND idempotency_key = :key AND submission_id = :submission_id"""
                ),
                {
                    "task_id": TASK_ID,
                    "worker_id": worker_id,
                    "key": row["idempotency_key"],
                    "submission_id": row["submission_id"],
                },
            )
            self._expect_count(result.rowcount, 1, "idempotency record deletion")

        for row in plan.submission_evidence:
            result = await self.connection.execute(
                text(
                    """DELETE FROM completion_submission_evidence
                       WHERE task_id = :task_id AND submission_id = :submission_id
                         AND evidence_id = :evidence_id AND position = :position"""
                ),
                row,
            )
            self._expect_count(result.rowcount, 1, "submission evidence link deletion")
        for row in plan.submission_steps:
            result = await self.connection.execute(
                text(
                    """DELETE FROM completion_submission_steps
                       WHERE task_id = :task_id AND submission_id = :submission_id
                         AND step_id = :step_id AND position = :position"""
                ),
                row,
            )
            self._expect_count(result.rowcount, 1, "submission checklist link deletion")

        for row in plan.submissions:
            result = await self.connection.execute(
                text(
                    """DELETE FROM completion_submissions
                       WHERE task_id = :task_id AND worker_id = :worker_id
                         AND submission_id = :submission_id"""
                ),
                {
                    "task_id": TASK_ID,
                    "worker_id": worker_id,
                    "submission_id": row["submission_id"],
                },
            )
            self._expect_count(result.rowcount, 1, "completion submission deletion")

        for row in plan.evidence:
            result = await self.connection.execute(
                text(
                    """DELETE FROM evidence
                       WHERE task_id = :task_id AND worker_id = :worker_id
                         AND evidence_id = :evidence_id AND storage_key = :storage_key
                         AND sha256 = :sha256"""
                ),
                {
                    "task_id": TASK_ID,
                    "worker_id": worker_id,
                    "evidence_id": row["evidence_id"],
                    "storage_key": row["storage_key"],
                    "sha256": row["sha256"],
                },
            )
            self._expect_count(result.rowcount, 1, "evidence metadata deletion")

        for row in plan.location_events:
            result = await self.connection.execute(
                text(
                    """DELETE FROM location_events
                       WHERE task_id = :task_id AND worker_id = :worker_id
                         AND location_event_id = :event_id"""
                ),
                {
                    "task_id": TASK_ID,
                    "worker_id": worker_id,
                    "event_id": row["location_event_id"],
                },
            )
            self._expect_count(result.rowcount, 1, "location event deletion")

        for row in plan.blockers:
            result = await self.connection.execute(
                text(
                    """DELETE FROM task_blockers
                       WHERE task_id = :task_id AND worker_id = :worker_id
                         AND blocker_id = :blocker_id"""
                ),
                {
                    "task_id": TASK_ID,
                    "worker_id": worker_id,
                    "blocker_id": row["blocker_id"],
                },
            )
            self._expect_count(result.rowcount, 1, "blocker history deletion")

        # Preserve step definitions; reset only their mutable execution state.
        await self.connection.execute(
            text(
                """UPDATE checklist_steps SET status = 'PENDING', note = NULL,
                          completed_at = NULL, updated_at = now()
                   WHERE task_id = :task_id AND assigned_worker_id = :worker_id
                     AND (status <> 'PENDING' OR note IS NOT NULL
                          OR completed_at IS NOT NULL)"""
            ),
            {"task_id": TASK_ID, "worker_id": worker_id},
        )

        verified = await self.inspect(lock=True)
        original_checklist = [
            (
                row["step_id"],
                row["position"],
                row["title"],
                row["required"],
                row["assigned_worker_id"],
            )
            for row in plan.checklist
        ]
        verified_checklist = [
            (
                row["step_id"],
                row["position"],
                row["title"],
                row["required"],
                row["assigned_worker_id"],
            )
            for row in verified.checklist
        ]
        if (
            any(
                verified.task[field] != plan.task[field]
                for field in preserved_task_fields
            )
            or
            verified_checklist != original_checklist
            or
            verified.task["status"] != "ACCEPTED"
            or any(
                verified.task[field] is not None
                for field in (
                    "arrival_location_event_id",
                    "completion_location_event_id",
                    "completion_submission_id",
                )
            )
            or verified.submissions
            or verified.submission_evidence
            or verified.submission_steps
            or verified.idempotency_records
            or verified.evidence
            or verified.location_events
            or verified.blockers
            or any(
                row["status"] != "PENDING"
                or row["note"] is not None
                or row["completed_at"] is not None
                for row in verified.checklist
            )
        ):
            raise ResetSafetyError("Post-reset database verification failed.")

    @staticmethod
    def _expect_count(actual: int, expected: int, label: str) -> None:
        if actual != expected:
            raise ResetSafetyError(
                f"Expected {expected} affected row(s) for {label}, got {actual}."
            )


class PostgresResetDatabase:
    def __init__(self, engine, image_root: Path):
        self.engine = engine
        self.image_root = image_root

    @asynccontextmanager
    async def transaction(self, execute: bool):
        async with self.engine.connect() as connection:
            async with connection.begin():
                await connection.execute(
                    text(
                        "SET TRANSACTION ISOLATION LEVEL SERIALIZABLE"
                        + ("" if execute else ", READ ONLY")
                    )
                )
                database_name = await connection.scalar(
                    text("SELECT current_database()")
                )
                if database_name != "kavach":
                    raise ResetSafetyError("Refusing any database other than kavach.")
                yield PostgresResetTransaction(connection, self.image_root)


async def run_reset(
    settings: Settings,
    *,
    execute: bool = False,
    confirmation: str | None = None,
    database_factory=PostgresResetDatabase,
) -> dict[str, Any]:
    if execute:
        validate_execution_guard(settings, "kavach")
        if confirmation != CONFIRMATION:
            raise ResetSafetyError("Typed confirmation did not match exactly.")
    if settings.database_url is None:
        raise ResetSafetyError("DATABASE_URL is not configured.")

    url = parse_database_url(settings.database_url.get_secret_value())
    if url.database != "kavach":
        raise ResetSafetyError("Refusing any configured database other than kavach.")
    engine = create_async_engine(
        url,
        pool_pre_ping=True,
        connect_args={"timeout": settings.database_connect_timeout_seconds},
    )
    database = database_factory(engine, settings.image_storage_dir)
    try:
        async with database.transaction(execute=execute) as transaction:
            plan = await transaction.inspect(lock=execute)
            validate_plan(plan)
            if not execute:
                return {"mode": "dry-run", "plan": plan.summary()}
            await transaction.apply(plan)

        # Filesystem cleanup is strictly after a successful database commit.
        for item in plan.evidence_files:
            path = item.path.resolve()
            if (
                path.parent != Path(settings.image_storage_dir).resolve()
                or not path.is_file()
                or hashlib.sha256(path.read_bytes()).hexdigest() != item.sha256
            ):
                raise PostCommitCleanupError(
                    "Database reset committed; refusing unsafe file cleanup for "
                    f"{path.name}. The database transaction cannot be rolled back."
                )
        removed = []
        for item in plan.evidence_files:
            path = item.path.resolve()
            try:
                path.unlink()
            except OSError as exc:
                raise PostCommitCleanupError(
                    "Database reset committed; file cleanup failed for "
                    f"{path.name}. Cleanup may be partial and the database "
                    "transaction cannot be rolled back."
                ) from exc
            if path.exists():
                raise PostCommitCleanupError(
                    "Database reset committed; file cleanup failed for "
                    f"{path.name}. Cleanup may be partial and the database "
                    "transaction cannot be rolled back."
                )
            removed.append(str(path))
        return {
            "mode": "executed",
            "plan": plan.summary(),
            "deleted_files": removed,
            "database_committed": True,
        }
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Perform the reset; otherwise perform a read-only dry-run.",
    )
    args = parser.parse_args()
    settings = get_settings()

    confirmation = None
    if args.execute:
        if settings.app_env != "development":
            raise SystemExit("Reset refused: APP_ENV must be exactly development.")
        if not settings.kavach_demo_reset_enabled:
            raise SystemExit("Reset refused: KAVACH_DEMO_RESET_ENABLED must be true.")
        if not settings.kavach_demo_reset_local_only:
            raise SystemExit(
                "Reset refused: KAVACH_DEMO_RESET_LOCAL_ONLY must be true."
            )
        confirmation = input('Type "RESET TASK-001" to continue: ')

    try:
        result = asyncio.run(
            run_reset(settings, execute=args.execute, confirmation=confirmation)
        )
    except PostCommitCleanupError as exc:
        raise SystemExit(f"Reset partially completed: {exc}") from exc
    except ResetSafetyError as exc:
        raise SystemExit(f"Reset refused: {exc}") from exc
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
