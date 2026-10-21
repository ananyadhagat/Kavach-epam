"""Repository abstraction for candidate complaint retrieval.

Design notes (Phase 1, ``docs/duplicate_detection/architecture.md`` section 4):

* The repository only **stores and returns** complaint records. It must never
  calculate similarity scores, decide duplicates, or mutate/delete/merge.
* Methods are **synchronous**. The first prototype is an in-memory store with no
  I/O, so synchronous methods are the simplest and most testable choice. If a
  future adapter talks to a remote KAVACH service over the network, an async
  variant can be introduced behind the same conceptual contract (see
  ``README.md`` for the migration path).
* The interface depends only on the domain ``Complaint`` schema. It has no
  dependency on FastAPI, HTTP, request handling or the database.
* Implementations must distinguish a *legitimate empty result* (return an empty
  list) from a *failure* (raise :class:`RepositoryError`). An empty list is never
  an error, and a failure is never reported as an empty result.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable

from app.schemas.complaint import Complaint


class RepositoryError(RuntimeError):
    """Raised when a repository operation cannot be completed.

    Distinguishes an infrastructure/usage failure from a legitimate empty
    result. Callers must not translate this into a ``NEW`` decision.
    """


class ComplaintRepository(ABC):
    """Read-oriented storage contract used to retrieve candidate incidents."""

    @abstractmethod
    def add(self, complaint: Complaint) -> None:
        """Store a single complaint record.

        Raises:
            RepositoryError: if a record with the same ``complaint_id`` already
                exists (records are never silently overwritten).
        """

    @abstractmethod
    def add_many(self, complaints: Iterable[Complaint]) -> None:
        """Store several complaint records (e.g. seeding synthetic fixtures)."""

    @abstractmethod
    def get_by_id(self, complaint_id: str) -> Complaint | None:
        """Return the stored record for ``complaint_id``, or ``None`` if absent."""

    @abstractmethod
    def list_candidates(self, exclude_complaint_id: str | None = None) -> list[Complaint]:
        """Return eligible incidents for comparison.

        Args:
            exclude_complaint_id: If given, the record with this id is excluded
                (self-comparison guard). The incoming complaint is never inserted
                by this method.

        Returns:
            A list of stored records in a deterministic order. An empty list is
            a legitimate "no eligible candidates" result, not an error.
        """

    @abstractmethod
    def count(self) -> int:
        """Return the number of stored records."""
