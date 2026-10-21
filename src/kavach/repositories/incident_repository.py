"""Persistence abstraction: in-memory for the prototype, PostgreSQL for durability.

`save()` returns the record that is actually stored for that request_id. If another request with the
same request_id won a race, the already-stored record is returned instead of the new one, so the
client never receives an incident_id that was not persisted.
Any storage failure is raised as RepositoryError (mapped to a controlled 503 by the API).
"""
from __future__ import annotations

import threading
from abc import ABC, abstractmethod

from kavach.errors import RepositoryError
from kavach.schemas.incident_intelligence import StructuredIncidentRecord


class IncidentRepository(ABC):
    @abstractmethod
    def save(self, record: StructuredIncidentRecord) -> StructuredIncidentRecord: ...

    @abstractmethod
    def get(self, incident_id: str) -> StructuredIncidentRecord | None: ...

    @abstractmethod
    def get_by_request_id(self, request_id: str) -> StructuredIncidentRecord | None: ...


class InMemoryIncidentRepository(IncidentRepository):
    def __init__(self) -> None:
        self._by_id: dict[str, StructuredIncidentRecord] = {}
        self._by_request: dict[str, str] = {}
        self._lock = threading.Lock()

    def save(self, record: StructuredIncidentRecord) -> StructuredIncidentRecord:
        with self._lock:
            existing_id = self._by_request.get(record.request_id)
            if existing_id is not None:
                return self._by_id[existing_id]
            if record.incident_id in self._by_id:
                raise RepositoryError("incident_id collision")
            self._by_id[record.incident_id] = record
            self._by_request[record.request_id] = record.incident_id
            return record

    def get(self, incident_id: str) -> StructuredIncidentRecord | None:
        return self._by_id.get(incident_id)

    def get_by_request_id(self, request_id: str) -> StructuredIncidentRecord | None:
        iid = self._by_request.get(request_id)
        return self._by_id.get(iid) if iid else None


class PostgresIncidentRepository(IncidentRepository):
    """Minimal JSONB-backed store (psycopg 3). One connection per call: fine for a prototype; use a pool later.

    Table schema is unchanged; new record fields live inside `payload`.
    Evidence/location tables from the geolocation guide can be normalized out of `payload` later.
    """

    DDL = """
    CREATE TABLE IF NOT EXISTS incident_records (
        incident_id TEXT PRIMARY KEY,
        request_id  TEXT UNIQUE NOT NULL,
        payload     JSONB NOT NULL,
        created_at  TIMESTAMPTZ NOT NULL
    )"""

    def __init__(self, dsn: str):
        import psycopg  # lazy: optional dependency

        self._psycopg = psycopg
        self._dsn = dsn
        try:
            with psycopg.connect(dsn) as conn:
                conn.execute(self.DDL)
        except psycopg.Error as exc:
            raise RepositoryError("could not initialise incident_records table") from exc

    def save(self, record: StructuredIncidentRecord) -> StructuredIncidentRecord:
        try:
            with self._psycopg.connect(self._dsn) as conn:
                row = conn.execute(
                    "INSERT INTO incident_records (incident_id, request_id, payload, created_at) "
                    "VALUES (%s, %s, %s::jsonb, %s) ON CONFLICT (request_id) DO NOTHING RETURNING incident_id",
                    (record.incident_id, record.request_id, record.model_dump_json(), record.created_at),
                ).fetchone()
        except self._psycopg.Error as exc:
            raise RepositoryError("could not save incident") from exc
        if row is not None:
            return record
        existing = self._fetch("request_id", record.request_id)  # lost a race: return what is stored
        if existing is None:
            raise RepositoryError("request_id conflict but no stored record found")
        return existing

    def _fetch(self, column: str, value: str) -> StructuredIncidentRecord | None:
        if column not in {"incident_id", "request_id"}:
            raise ValueError(column)
        try:
            with self._psycopg.connect(self._dsn) as conn:
                row = conn.execute(f"SELECT payload FROM incident_records WHERE {column} = %s", (value,)).fetchone()
        except self._psycopg.Error as exc:
            raise RepositoryError("could not read incident") from exc
        return StructuredIncidentRecord.model_validate(row[0]) if row else None

    def get(self, incident_id: str) -> StructuredIncidentRecord | None:
        return self._fetch("incident_id", incident_id)

    def get_by_request_id(self, request_id: str) -> StructuredIncidentRecord | None:
        return self._fetch("request_id", request_id)
