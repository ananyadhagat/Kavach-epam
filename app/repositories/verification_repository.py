import json
import sqlite3
from contextlib import closing
from pathlib import Path
from threading import Lock
from typing import Protocol

from ..contracts.v1 import CONTRACT_VERSION


class VerificationRepository(Protocol):
    def get_existing(self, task_id: str, submission_id: str, rule_version: str) -> dict | None: ...
    def get_or_create(self, task_id: str, submission_id: str, rule_version: str, create_response) -> dict: ...
    def save(self, response: dict) -> None: ...


class SQLiteVerificationRepository:
    def __init__(self, db_path: str | Path):
        self.db_path = str(db_path)

    def _connect(self):
        db = sqlite3.connect(self.db_path)
        db.row_factory = sqlite3.Row
        return db

    def initialize(self) -> None:
        with closing(self._connect()) as db:
            with db:
                db.execute("""CREATE TABLE IF NOT EXISTS verification_records (
                    verification_id TEXT PRIMARY KEY, task_id TEXT NOT NULL, submission_id TEXT NOT NULL,
                    rule_version TEXT NOT NULL, response_json TEXT NOT NULL, created_at TEXT NOT NULL,
                    UNIQUE(task_id, submission_id, rule_version))""")

    def get_existing(self, task_id: str, submission_id: str, rule_version: str) -> dict | None:
        with closing(self._connect()) as db:
            row = db.execute(
                "SELECT response_json FROM verification_records WHERE task_id=? AND submission_id=? AND rule_version=?",
                (task_id, submission_id, rule_version),
            ).fetchone()
        return json.loads(row["response_json"]) if row else None

    def get_or_create(self, task_id: str, submission_id: str, rule_version: str, create_response) -> dict:
        """Serialize lookup and creation so concurrent callers all return the persisted row."""
        with closing(self._connect()) as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT response_json FROM verification_records WHERE task_id=? AND submission_id=? AND rule_version=?",
                (task_id, submission_id, rule_version),
            ).fetchone()
            if row:
                cached = json.loads(row["response_json"])
                if (cached.get("contract_version") == CONTRACT_VERSION
                        and "reason_codes" in cached and "failed_requirement_ids" in cached):
                    db.commit()
                    return cached
                # Contract upgrades add response fields. Rebuild stale cached output once
                # under the same idempotency key so old SQLite rows do not cause HTTP 500s.
                response = create_response()
                db.execute(
                    "UPDATE verification_records SET verification_id=?, response_json=?, created_at=? "
                    "WHERE task_id=? AND submission_id=? AND rule_version=?",
                    (response["verification_id"], json.dumps(response), response["created_at"],
                     task_id, submission_id, rule_version),
                )
                db.commit()
                return response
            response = create_response()
            db.execute("INSERT INTO verification_records VALUES (?, ?, ?, ?, ?, ?)", (
                response["verification_id"], response["task_id"], response["submission_id"],
                response["rule_version"], json.dumps(response), response["created_at"],
            ))
            row = db.execute(
                "SELECT response_json FROM verification_records WHERE task_id=? AND submission_id=? AND rule_version=?",
                (task_id, submission_id, rule_version),
            ).fetchone()
            db.commit()
            return json.loads(row["response_json"])

    def save(self, response: dict) -> None:
        with closing(self._connect()) as db:
            with db:
                db.execute("INSERT OR IGNORE INTO verification_records VALUES (?, ?, ?, ?, ?, ?)", (
                    response["verification_id"], response["task_id"], response["submission_id"],
                    response["rule_version"], json.dumps(response), response["created_at"],
                ))


class MemoryVerificationRepository:
    """Simple repository useful for isolated unit tests and examples."""
    def __init__(self):
        self.records: dict[tuple[str, str, str], dict] = {}
        self._lock = Lock()

    def get_existing(self, task_id: str, submission_id: str, rule_version: str) -> dict | None:
        with self._lock:
            return self.records.get((task_id, submission_id, rule_version))

    def get_or_create(self, task_id: str, submission_id: str, rule_version: str, create_response) -> dict:
        key = (task_id, submission_id, rule_version)
        with self._lock:
            cached = self.records.get(key)
            if (cached is None or cached.get("contract_version") != CONTRACT_VERSION
                    or "reason_codes" not in cached or "failed_requirement_ids" not in cached):
                self.records[key] = create_response()
            return self.records[key]

    def save(self, response: dict) -> None:
        key = (response["task_id"], response["submission_id"], response["rule_version"])
        with self._lock:
            self.records.setdefault(key, response)
