"""SQL-backed implementations of the M3 candidate repository contract.

Two adapters are provided:

* :class:`SessionComplaintRepository` is bound to one session/transaction. The
  consolidation service uses it so M3 sees exactly the current transaction's
  consolidated complaints.
* :class:`DatabaseComplaintRepository` owns a session factory and opens a short
  session per call. It backs the existing read-only ``/check`` endpoint when the
  application runs against a database.

Neither adapter scores, decides, or writes consolidation links. Candidate
retrieval deliberately includes only complaints that are already members of a
consolidation group. Pending-review complaints are not offered to M3 until a
human resolves them, which keeps ingestion from blocking on an unlinkable
match.
"""

from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import ComplaintRecord, ConsolidationLink, ensure_aware
from app.repositories.base import (
    CandidateRetrieval,
    ComplaintRepository,
    RepositoryError,
    RetrievalOutcome,
)
from app.schemas.complaint import Complaint, Location


def complaint_to_record(complaint: Complaint) -> ComplaintRecord:
    """Build an ORM row from the canonical complaint model."""

    location = complaint.location
    return ComplaintRecord(
        complaint_id=complaint.complaint_id,
        description=complaint.description,
        category=complaint.category,
        facility_id=location.facility_id if location else None,
        location_id=location.location_id if location else None,
        latitude=location.latitude if location else None,
        longitude=location.longitude if location else None,
        reported_at=complaint.reported_at,
        image_hash=complaint.image_hash,
        payload=complaint.model_dump(mode="json"),
    )


def record_to_complaint(record: ComplaintRecord) -> Complaint:
    """Rebuild the canonical complaint model from an ORM row."""

    has_location = any(
        value is not None
        for value in (
            record.facility_id,
            record.location_id,
            record.latitude,
            record.longitude,
        )
    )
    location = (
        Location(
            facility_id=record.facility_id,
            location_id=record.location_id,
            latitude=record.latitude,
            longitude=record.longitude,
        )
        if has_location
        else None
    )
    return Complaint(
        complaint_id=record.complaint_id,
        description=record.description,
        category=record.category,
        location=location,
        reported_at=ensure_aware(record.reported_at),
        image_hash=record.image_hash,
    )


class SessionComplaintRepository(ComplaintRepository):
    """Candidate repository bound to an existing SQLAlchemy session."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, complaint: Complaint) -> None:
        self._session.add(complaint_to_record(complaint))
        try:
            self._session.flush()
        except IntegrityError as exc:
            raise RepositoryError(
                f"a record with complaint_id {complaint.complaint_id!r} "
                "already exists"
            ) from exc
        except SQLAlchemyError as exc:
            raise RepositoryError("complaint could not be stored") from exc

    def add_many(self, complaints: Iterable[Complaint]) -> None:
        for complaint in complaints:
            self.add(complaint)

    def get_by_id(self, complaint_id: str) -> Complaint | None:
        record = self._session.get(ComplaintRecord, complaint_id)
        return record_to_complaint(record) if record is not None else None

    def list_candidates(
        self, exclude_complaint_id: str | None = None
    ) -> list[Complaint]:
        statement = (
            select(ComplaintRecord)
            .join(
                ConsolidationLink,
                ConsolidationLink.complaint_id == ComplaintRecord.complaint_id,
            )
            .order_by(ComplaintRecord.complaint_id)
        )
        if exclude_complaint_id is not None:
            statement = statement.where(
                ComplaintRecord.complaint_id != exclude_complaint_id
            )
        records = self._session.execute(statement).scalars().all()
        return [record_to_complaint(record) for record in records]

    def retrieve_candidates(
        self, exclude_complaint_id: str | None = None
    ) -> CandidateRetrieval:
        """Return every consolidated complaint in the current transaction.

        The query reads the complete persisted set visible to this transaction,
        so a successful call is exhaustive and can be reported as ``COMPLETE``.
        """

        try:
            candidates = self.list_candidates(
                exclude_complaint_id=exclude_complaint_id
            )
        except SQLAlchemyError as exc:
            raise RepositoryError("candidate retrieval failed") from exc
        return CandidateRetrieval(
            candidates=tuple(candidates),
            outcome=RetrievalOutcome.COMPLETE,
        )

    def count(self) -> int:
        return int(
            self._session.execute(
                select(func.count()).select_from(ComplaintRecord)
            ).scalar_one()
        )


class DatabaseComplaintRepository(ComplaintRepository):
    """Candidate repository that opens one session per operation.

    Used by the unchanged ``/check`` route when a database is configured. Each
    call is a short, read-only transaction.
    """

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def _session_scope(self):
        return self._session_factory()

    def add(self, complaint: Complaint) -> None:
        with self._session_scope() as session:
            try:
                session.add(complaint_to_record(complaint))
                session.commit()
            except IntegrityError as exc:
                session.rollback()
                raise RepositoryError(
                    f"a record with complaint_id {complaint.complaint_id!r} "
                    "already exists"
                ) from exc
            except SQLAlchemyError as exc:
                session.rollback()
                raise RepositoryError("complaint could not be stored") from exc

    def add_many(self, complaints: Iterable[Complaint]) -> None:
        for complaint in complaints:
            self.add(complaint)

    def get_by_id(self, complaint_id: str) -> Complaint | None:
        with self._session_scope() as session:
            record = session.get(ComplaintRecord, complaint_id)
            return record_to_complaint(record) if record is not None else None

    def list_candidates(
        self, exclude_complaint_id: str | None = None
    ) -> list[Complaint]:
        with self._session_scope() as session:
            repository = SessionComplaintRepository(session)
            return repository.list_candidates(
                exclude_complaint_id=exclude_complaint_id
            )

    def retrieve_candidates(
        self, exclude_complaint_id: str | None = None
    ) -> CandidateRetrieval:
        with self._session_scope() as session:
            repository = SessionComplaintRepository(session)
            return repository.retrieve_candidates(
                exclude_complaint_id=exclude_complaint_id
            )

    def count(self) -> int:
        with self._session_scope() as session:
            return int(
                session.execute(
                    select(func.count()).select_from(ComplaintRecord)
                ).scalar_one()
            )


__all__ = [
    "DatabaseComplaintRepository",
    "SessionComplaintRepository",
    "complaint_to_record",
    "record_to_complaint",
]
