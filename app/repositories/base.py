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
* A successful list is not automatically an *exhaustive* search. The
  :meth:`ComplaintRepository.retrieve_candidates` extension reports completeness
  explicitly. Its default implementation deliberately returns ``PARTIAL`` so a
  repository that has not made a completeness guarantee can never cause an
  unqualified ``NEW`` decision.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from collections.abc import Iterable
from dataclasses import dataclass
from enum import Enum

from app.schemas.complaint import Complaint

#: Default error code used when a repository failure does not supply one.
RETRIEVAL_FAILED = "RETRIEVAL_FAILED"

#: Error code used when a repository cannot attest to exhaustive retrieval.
RETRIEVAL_COMPLETENESS_UNKNOWN = "RETRIEVAL_COMPLETENESS_UNKNOWN"

#: Error code used when a repository returns a malformed retrieval result.
INVALID_RETRIEVAL_RESULT = "INVALID_RETRIEVAL_RESULT"

_CODE_PATTERN = re.compile(r"^[A-Z0-9_]+$")


def _validate_code(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not _CODE_PATTERN.fullmatch(value):
        raise ValueError(f"{field_name} must match ^[A-Z0-9_]+$")
    return value


class RepositoryError(RuntimeError):
    """Raised when a repository operation cannot be completed.

    Distinguishes an infrastructure/usage failure from a legitimate empty
    result. Callers must not translate this into a ``NEW`` decision.

    ``code`` is a machine-readable UPPER_SNAKE identifier for the failure. It
    defaults to :data:`RETRIEVAL_FAILED` so existing call sites keep working.
    """

    def __init__(self, message: str, *, code: str = RETRIEVAL_FAILED) -> None:
        self.code = _validate_code(code, "repository error code")
        super().__init__(message)


class RetrievalOutcome(str, Enum):
    """Completeness of a candidate retrieval.

    This mirrors, but deliberately does not import, the decision policy's
    ``RetrievalStatus``. The repository layer must not depend on scoring.
    """

    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"


@dataclass(frozen=True, slots=True)
class RetrievalFailure:
    """A machine-readable explanation for an incomplete or failed retrieval."""

    code: str
    message: str

    def __post_init__(self) -> None:
        _validate_code(self.code, "retrieval failure code")
        if not isinstance(self.message, str):
            raise TypeError("retrieval failure message must be a string")


@dataclass(frozen=True, slots=True)
class CandidateRetrieval:
    """Candidates plus an explicit statement about retrieval completeness.

    ``COMPLETE`` means the repository guarantees that every eligible candidate
    was returned. ``PARTIAL`` means the returned candidates are valid but the
    set may be incomplete. ``FAILED`` means retrieval did not produce a
    trustworthy candidate set.

    Failures are required for ``PARTIAL``/``FAILED`` and forbidden for
    ``COMPLETE``. If a caller omits them for an incomplete outcome, a safe
    default is synthesised rather than silently claiming success.
    """

    candidates: tuple[Complaint, ...]
    outcome: RetrievalOutcome
    failures: tuple[RetrievalFailure, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "candidates", tuple(self.candidates))
        object.__setattr__(self, "failures", tuple(self.failures))

        if not isinstance(self.outcome, RetrievalOutcome):
            raise TypeError("retrieval outcome must be a RetrievalOutcome")

        for candidate in self.candidates:
            if not isinstance(candidate, Complaint):
                raise TypeError(
                    "retrieval candidates must be Complaint records; got "
                    f"{type(candidate).__name__}"
                )
        for failure in self.failures:
            if not isinstance(failure, RetrievalFailure):
                raise TypeError(
                    "retrieval failures must be RetrievalFailure records; got "
                    f"{type(failure).__name__}"
                )

        if self.outcome is RetrievalOutcome.COMPLETE:
            if self.failures:
                raise ValueError(
                    "a COMPLETE retrieval cannot carry retrieval failures"
                )
            return

        if self.failures:
            return
        if self.outcome is RetrievalOutcome.PARTIAL:
            default = RetrievalFailure(
                RETRIEVAL_COMPLETENESS_UNKNOWN,
                "The repository did not report whether candidate retrieval "
                "was complete.",
            )
        else:
            default = RetrievalFailure(
                RETRIEVAL_FAILED,
                "Candidate retrieval failed.",
            )
        object.__setattr__(self, "failures", (default,))


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

    def retrieve_candidates(
        self, exclude_complaint_id: str | None = None
    ) -> CandidateRetrieval:
        """Return candidates together with an explicit completeness guarantee.

        This is the safe retrieval entry point for the M3 HTTP integration. The
        default adapts :meth:`list_candidates` but reports ``PARTIAL`` because a
        plain list cannot prove that the search was exhaustive. Repositories
        that *can* guarantee completeness must override this method and return
        ``RetrievalOutcome.COMPLETE``.

        Raises:
            RepositoryError: if the underlying retrieval fails.
        """
        candidates = self.list_candidates(exclude_complaint_id=exclude_complaint_id)
        return CandidateRetrieval(
            candidates=tuple(candidates),
            outcome=RetrievalOutcome.PARTIAL,
            failures=(
                RetrievalFailure(
                    RETRIEVAL_COMPLETENESS_UNKNOWN,
                    "The repository does not guarantee exhaustive candidate "
                    "retrieval.",
                ),
            ),
        )

    @abstractmethod
    def count(self) -> int:
        """Return the number of stored records."""
