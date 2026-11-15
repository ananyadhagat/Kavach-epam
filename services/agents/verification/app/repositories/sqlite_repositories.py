"""SQLite implementations of task and evidence repository interfaces."""

import json
import sqlite3
from contextlib import closing
from pathlib import Path

from ..adapters.agent_contracts import adapt_sanitation_plan
from .evidence_repository import EvidenceRepository


class SQLiteTaskRepository:
    def __init__(self, db_path: str | Path):
        self.db_path = str(db_path)

    def _connect(self):
        return sqlite3.connect(self.db_path)

    def initialize(self) -> None:
        with closing(self._connect()) as db, db:
            db.execute("CREATE TABLE IF NOT EXISTS task_records (task_id TEXT PRIMARY KEY, task_json TEXT NOT NULL)")

    def get(self, task_id: str) -> dict | None:
        with closing(self._connect()) as db:
            row = db.execute("SELECT task_json FROM task_records WHERE task_id=?", (task_id,)).fetchone()
        if not row:
            return None
        record = json.loads(row[0])
        if "sanitation_plan" in record:
            return adapt_sanitation_plan(
                record["sanitation_plan"], task_id=task_id, authoritative_site=record.get("authoritative_site"),
            )
        return record

    def save(self, task_id: str, task: dict) -> None:
        with closing(self._connect()) as db, db:
            db.execute(
                "INSERT INTO task_records(task_id,task_json) VALUES (?,?) "
                "ON CONFLICT(task_id) DO UPDATE SET task_json=excluded.task_json",
                (task_id, json.dumps(task)),
            )

    def save_sanitation_plan(self, task_id: str, plan: dict, authoritative_site: dict | None = None) -> None:
        self.save(task_id, {"sanitation_plan": plan, "authoritative_site": authoritative_site})


class SQLiteEvidenceRepository(EvidenceRepository):
    """SQLite-backed submission metadata with the same trusted image loader as memory storage."""

    def __init__(self, db_path: str | Path, storage_root: str | Path = "stored_evidence"):
        super().__init__(submissions={}, storage_root=storage_root)
        self.db_path = str(db_path)

    def _connect(self):
        db = sqlite3.connect(self.db_path)
        db.row_factory = sqlite3.Row
        return db

    def initialize(self) -> None:
        with closing(self._connect()) as db, db:
            db.execute("""CREATE TABLE IF NOT EXISTS submission_records (
                submission_id TEXT PRIMARY KEY, task_id TEXT NOT NULL, submission_json TEXT NOT NULL)""")
            db.execute("CREATE TABLE IF NOT EXISTS evidence_records (evidence_id TEXT PRIMARY KEY, record_json TEXT NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS location_events (location_event_id TEXT PRIMARY KEY, event_json TEXT NOT NULL)")

    def get(self, submission_id: str) -> dict | None:
        with closing(self._connect()) as db:
            row = db.execute(
                "SELECT submission_json FROM submission_records WHERE submission_id=?", (submission_id,)
            ).fetchone()
        return json.loads(row["submission_json"]) if row else None

    def save(self, submission_id: str, submission: dict) -> None:
        with closing(self._connect()) as db, db:
            db.execute(
                "INSERT INTO submission_records(submission_id,task_id,submission_json) VALUES (?,?,?) "
                "ON CONFLICT(submission_id) DO UPDATE SET task_id=excluded.task_id,submission_json=excluded.submission_json",
                (submission_id, submission["task_id"], json.dumps(submission)),
            )

    def get_evidence_records(self, evidence_ids: list[str]) -> list[dict]:
        with closing(self._connect()) as db:
            rows = [db.execute("SELECT record_json FROM evidence_records WHERE evidence_id=?", (item,)).fetchone()
                    for item in evidence_ids]
        return [json.loads(row["record_json"]) for row in rows if row]

    def get_location_events(self, event_ids: list[str]) -> list[dict]:
        with closing(self._connect()) as db:
            rows = [db.execute("SELECT event_json FROM location_events WHERE location_event_id=?", (item,)).fetchone()
                    for item in event_ids]
        return [json.loads(row["event_json"]) for row in rows if row]

    def save_evidence_record(self, evidence_record: dict) -> None:
        with closing(self._connect()) as db, db:
            db.execute("INSERT INTO evidence_records VALUES (?,?) ON CONFLICT(evidence_id) DO UPDATE SET record_json=excluded.record_json",
                       (evidence_record["evidence_id"], json.dumps(evidence_record)))

    def save_location_event(self, location_event: dict) -> None:
        with closing(self._connect()) as db, db:
            db.execute("INSERT INTO location_events VALUES (?,?) ON CONFLICT(location_event_id) DO UPDATE SET event_json=excluded.event_json",
                       (location_event["location_event_id"], json.dumps(location_event)))
