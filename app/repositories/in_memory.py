"""In-memory implementation of :class:`ComplaintRepository` (prototype only).

Suitable for the standalone prototype and unit tests. It uses a plain
``dict[str, Complaint]`` keyed by ``complaint_id`` and adds no caching, SQL,
vector search or other infrastructure.

Safety and determinism:

* Records are stored and returned as deep copies, so callers cannot mutate the
  repository's internal state by accident (and vice-versa).
* ``list_candidates`` returns records sorted by ``complaint_id`` for a stable,
  deterministic order in tests.
* A duplicate id raises :class:`RepositoryError` rather than overwriting.
"""

from __future__ import annotations

from collections.abc import Iterable

from app.repositories.base import ComplaintRepository, RepositoryError
from app.schemas.complaint import Complaint


class InMemoryComplaintRepository(ComplaintRepository):
    """A small, deterministic, database-free complaint store."""

    def __init__(self, incidents: Iterable[Complaint] | None = None) -> None:
        self._records: dict[str, Complaint] = {}
        if incidents is not None:
            self.add_many(incidents)

    def add(self, complaint: Complaint) -> None:
        complaint_id = complaint.complaint_id
        if complaint_id in self._records:
            raise RepositoryError(
                f"a record with complaint_id {complaint_id!r} already exists"
            )
        # Store a deep copy so later mutation of the caller's object cannot leak in.
        self._records[complaint_id] = complaint.model_copy(deep=True)

    def add_many(self, complaints: Iterable[Complaint]) -> None:
        for complaint in complaints:
            self.add(complaint)

    def get_by_id(self, complaint_id: str) -> Complaint | None:
        record = self._records.get(complaint_id)
        if record is None:
            return None
        return record.model_copy(deep=True)

    def list_candidates(self, exclude_complaint_id: str | None = None) -> list[Complaint]:
        ordered_ids = sorted(self._records)
        candidates: list[Complaint] = []
        for complaint_id in ordered_ids:
            if exclude_complaint_id is not None and complaint_id == exclude_complaint_id:
                continue
            candidates.append(self._records[complaint_id].model_copy(deep=True))
        return candidates

    def count(self) -> int:
        return len(self._records)
