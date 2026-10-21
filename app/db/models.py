from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Double,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    MetaData,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import Uuid

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


def _in(column: str, values: tuple[str, ...]) -> str:
    quoted = ", ".join(f"'{value}'" for value in values)
    return f"{column} IN ({quoted})"


TASK_STATUSES = ("ASSIGNED", "ACCEPTED", "REJECTED", "IN_PROGRESS",
                 "PAUSED", "COMPLETION_SUBMITTED")
TASK_PRIORITIES = ("LOW", "MEDIUM", "HIGH")
CHECKLIST_STATUSES = ("PENDING", "COMPLETED", "BLOCKED")
EVIDENCE_TYPES = ("BEFORE", "AFTER")
EVIDENCE_STATUSES = ("STORED",)
IMAGE_MIME_TYPES = ("image/jpeg", "image/png", "image/webp")
LOCATION_EVENT_TYPES = ("ARRIVAL", "COMPLETION")
CAPTURE_STATUSES = ("CAPTURED", "UNAVAILABLE", "INACCURATE")
SUBMISSION_STATUSES = ("SUBMITTED_FOR_VERIFICATION",)

# PostgreSQL double precision accepts NaN and Infinity, and treats NaN as
# greater than every number. Range checks therefore reject both.
LATITUDE_CHECK = "latitude >= -90 AND latitude <= 90"
LONGITUDE_CHECK = "longitude >= -180 AND longitude <= 180"

Timestamp = DateTime(timezone=True)


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class WorkerRow(Base):
    __tablename__ = "workers"

    worker_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(200))
    is_active: Mapped[bool] = mapped_column(
        Boolean, server_default="true"
    )
    created_at: Mapped[datetime] = mapped_column(
        Timestamp, server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint("length(worker_id) > 0", name="worker_id_not_empty"),
    )


class TaskRow(Base):
    __tablename__ = "tasks"

    task_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    incident_id: Mapped[str] = mapped_column(String(100))
    assigned_worker_id: Mapped[str] = mapped_column(
        String(100), ForeignKey("workers.worker_id")
    )
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(String(2000))
    priority: Mapped[str] = mapped_column(String(10))
    status: Mapped[str] = mapped_column(String(30))
    latitude: Mapped[float] = mapped_column(Double)
    longitude: Mapped[float] = mapped_column(Double)
    address: Mapped[str] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(Timestamp)
    updated_at: Mapped[datetime] = mapped_column(Timestamp)
    arrival_location_event_id: Mapped[UUID | None] = mapped_column(Uuid)
    completion_location_event_id: Mapped[UUID | None] = mapped_column(Uuid)
    completion_submission_id: Mapped[UUID | None] = mapped_column(Uuid)

    __table_args__ = (
        CheckConstraint(_in("status", TASK_STATUSES), name="status_valid"),
        CheckConstraint(_in("priority", TASK_PRIORITIES),
                        name="priority_valid"),
        CheckConstraint(LATITUDE_CHECK, name="latitude_range"),
        CheckConstraint(LONGITUDE_CHECK, name="longitude_range"),
        CheckConstraint("length(task_id) > 0", name="task_id_not_empty"),
        # A submitted task always points at its submission, and only then.
        CheckConstraint(
            "(status = 'COMPLETION_SUBMITTED') = "
            "(completion_submission_id IS NOT NULL)",
            name="submission_matches_status",
        ),
        # Composite keys ensure a task only references its own records.
        ForeignKeyConstraint(
            ["task_id", "arrival_location_event_id"],
            ["location_events.task_id", "location_events.location_event_id"],
            name="fk_tasks_arrival_location_event",
            use_alter=True,
        ),
        ForeignKeyConstraint(
            ["task_id", "completion_location_event_id"],
            ["location_events.task_id", "location_events.location_event_id"],
            name="fk_tasks_completion_location_event",
            use_alter=True,
        ),
        ForeignKeyConstraint(
            ["task_id", "completion_submission_id"],
            ["completion_submissions.task_id",
             "completion_submissions.submission_id"],
            name="fk_tasks_completion_submission",
            use_alter=True,
        ),
        Index("ix_tasks_worker_status", "assigned_worker_id", "status"),
    )


class ChecklistStepRow(Base):
    __tablename__ = "checklist_steps"

    task_id: Mapped[str] = mapped_column(
        String(100),
        ForeignKey("tasks.task_id", ondelete="CASCADE"),
        primary_key=True,
    )
    step_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    position: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(250))
    required: Mapped[bool] = mapped_column(Boolean)
    status: Mapped[str] = mapped_column(String(20))
    note: Mapped[str | None] = mapped_column(String(500))
    updated_at: Mapped[datetime] = mapped_column(Timestamp)

    __table_args__ = (
        CheckConstraint(_in("status", CHECKLIST_STATUSES),
                        name="status_valid"),
        CheckConstraint("length(step_id) > 0", name="step_id_not_empty"),
        UniqueConstraint("task_id", "position"),
    )


class EvidenceRow(Base):
    __tablename__ = "evidence"

    evidence_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    task_id: Mapped[str] = mapped_column(
        String(100), ForeignKey("tasks.task_id")
    )
    worker_id: Mapped[str] = mapped_column(
        String(100), ForeignKey("workers.worker_id")
    )
    evidence_type: Mapped[str] = mapped_column(String(10))
    storage_key: Mapped[str] = mapped_column(String(100), unique=True)
    original_filename: Mapped[str] = mapped_column(String(255))
    mime_type: Mapped[str] = mapped_column(String(50))
    size_bytes: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(20))
    uploaded_at: Mapped[datetime] = mapped_column(Timestamp)

    __table_args__ = (
        CheckConstraint(_in("evidence_type", EVIDENCE_TYPES),
                        name="type_valid"),
        CheckConstraint(_in("mime_type", IMAGE_MIME_TYPES),
                        name="mime_type_valid"),
        CheckConstraint(_in("status", EVIDENCE_STATUSES),
                        name="status_valid"),
        CheckConstraint("size_bytes > 0", name="size_positive"),
        CheckConstraint("sha256 ~ '^[0-9a-f]{64}$'", name="sha256_hex"),
        # Same image, same type, same task and worker = one record.
        UniqueConstraint("task_id", "worker_id", "sha256", "evidence_type",
                         name="uq_evidence_content"),
        # Target for the completion_submission_evidence composite key.
        UniqueConstraint("task_id", "evidence_id"),
        Index("ix_evidence_task", "task_id"),
    )


class LocationEventRow(Base):
    __tablename__ = "location_events"

    location_event_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    task_id: Mapped[str] = mapped_column(
        String(100), ForeignKey("tasks.task_id")
    )
    worker_id: Mapped[str] = mapped_column(
        String(100), ForeignKey("workers.worker_id")
    )
    event_type: Mapped[str] = mapped_column(String(20))
    capture_status: Mapped[str] = mapped_column(String(20))
    latitude: Mapped[float | None] = mapped_column(Double)
    longitude: Mapped[float | None] = mapped_column(Double)
    accuracy_meters: Mapped[float | None] = mapped_column(Double)
    captured_at_device: Mapped[datetime | None] = mapped_column(Timestamp)
    received_at_server: Mapped[datetime] = mapped_column(Timestamp)

    __table_args__ = (
        CheckConstraint(_in("event_type", LOCATION_EVENT_TYPES),
                        name="event_type_valid"),
        CheckConstraint(_in("capture_status", CAPTURE_STATUSES),
                        name="capture_status_valid"),
        CheckConstraint(LATITUDE_CHECK, name="latitude_range"),
        CheckConstraint(LONGITUDE_CHECK, name="longitude_range"),
        CheckConstraint("accuracy_meters > 0 AND accuracy_meters <= 100000",
                        name="accuracy_range"),
        CheckConstraint(
            "(capture_status = 'CAPTURED') = "
            "(latitude IS NOT NULL AND longitude IS NOT NULL)",
            name="coordinates_match_status",
        ),
        CheckConstraint(
            "capture_status <> 'CAPTURED' OR accuracy_meters IS NOT NULL",
            name="captured_has_accuracy",
        ),
        UniqueConstraint("task_id", "location_event_id"),
        Index("ix_location_events_task_type", "task_id", "event_type"),
    )


class CompletionSubmissionRow(Base):
    __tablename__ = "completion_submissions"

    submission_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    # One submission per task; backs up the state machine in the database.
    task_id: Mapped[str] = mapped_column(
        String(100), ForeignKey("tasks.task_id"), unique=True
    )
    worker_id: Mapped[str] = mapped_column(
        String(100), ForeignKey("workers.worker_id")
    )
    completion_location_event_id: Mapped[UUID | None] = mapped_column(Uuid)
    notes: Mapped[str | None] = mapped_column(String(2000))
    status: Mapped[str] = mapped_column(String(40))
    submitted_at: Mapped[datetime] = mapped_column(Timestamp)

    __table_args__ = (
        CheckConstraint(_in("status", SUBMISSION_STATUSES),
                        name="status_valid"),
        UniqueConstraint("task_id", "submission_id"),
        ForeignKeyConstraint(
            ["task_id", "completion_location_event_id"],
            ["location_events.task_id", "location_events.location_event_id"],
            name="fk_completion_submissions_location_event",
        ),
    )


class CompletionEvidenceRow(Base):
    __tablename__ = "completion_submission_evidence"

    submission_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    evidence_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    task_id: Mapped[str] = mapped_column(String(100))
    position: Mapped[int] = mapped_column(Integer)

    __table_args__ = (
        ForeignKeyConstraint(
            ["task_id", "submission_id"],
            ["completion_submissions.task_id",
             "completion_submissions.submission_id"],
            name="fk_completion_evidence_submission",
            ondelete="CASCADE",
        ),
        # Evidence must belong to the same task as the submission.
        ForeignKeyConstraint(
            ["task_id", "evidence_id"],
            ["evidence.task_id", "evidence.evidence_id"],
            name="fk_completion_evidence_evidence",
        ),
        UniqueConstraint("submission_id", "position"),
    )


class CompletionStepRow(Base):
    __tablename__ = "completion_submission_steps"

    submission_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    step_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    task_id: Mapped[str] = mapped_column(String(100))
    position: Mapped[int] = mapped_column(Integer)

    __table_args__ = (
        ForeignKeyConstraint(
            ["task_id", "submission_id"],
            ["completion_submissions.task_id",
             "completion_submissions.submission_id"],
            name="fk_completion_steps_submission",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["task_id", "step_id"],
            ["checklist_steps.task_id", "checklist_steps.step_id"],
            name="fk_completion_steps_checklist_step",
        ),
        UniqueConstraint("submission_id", "position"),
    )


class IdempotencyRecordRow(Base):
    __tablename__ = "idempotency_records"

    task_id: Mapped[str] = mapped_column(
        String(100), ForeignKey("tasks.task_id"), primary_key=True
    )
    worker_id: Mapped[str] = mapped_column(
        String(100), ForeignKey("workers.worker_id"), primary_key=True
    )
    idempotency_key: Mapped[str] = mapped_column(
        String(200), primary_key=True
    )
    request_hash: Mapped[str] = mapped_column(String(64))
    submission_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("completion_submissions.submission_id")
    )
    created_at: Mapped[datetime] = mapped_column(
        Timestamp, server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint("length(trim(idempotency_key)) > 0",
                        name="key_not_blank"),
        CheckConstraint("request_hash ~ '^[0-9a-f]{64}$'",
                        name="request_hash_hex"),
    )


# Every application table, in an order safe for TRUNCATE ... CASCADE.
APP_TABLES = (
    "idempotency_records",
    "completion_submission_steps",
    "completion_submission_evidence",
    "completion_submissions",
    "location_events",
    "evidence",
    "checklist_steps",
    "tasks",
    "workers",
)
