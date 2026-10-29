"""Database tables. Each location source is its own location_evidence row;
nothing collapses them into one "verified location"."""

from datetime import datetime

from sqlalchemy import JSON, Boolean, CheckConstraint, DateTime, Float, ForeignKey, Index, Integer, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


ROLES = ("CITIZEN", "WORKER", "SUPERVISOR")
INCIDENT_STATUSES = ("SUBMITTED", "ASSIGNED", "IN_PROGRESS", "AWAITING_VERIFICATION", "RESOLVED")
TASK_STATUSES = ("ASSIGNED", "IN_PROGRESS", "AWAITING_VERIFICATION", "RESOLVED")
SOURCES = ("DEVICE_GEOLOCATION", "IMAGE_EXIF", "USER_SELECTED_PIN", "ADMIN_CORRECTION")
OUTCOMES = ("PASS", "FAIL", "REVIEW_REQUIRED", "NOT_CHECKED")

Timestamp = DateTime(timezone=True)
LAT = "{c} IS NULL OR ({c} >= -90 AND {c} <= 90)"
LON = "{c} IS NULL OR ({c} >= -180 AND {c} <= 180)"


class Base(DeclarativeBase):
    pass


class UserRow(Base):
    """In demo mode these are seeded, clearly labelled demo identities."""

    __tablename__ = "users"

    user_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(120))
    role: Mapped[str] = mapped_column(String(20))
    is_demo: Mapped[bool] = mapped_column(Boolean, default=True)

    __table_args__ = (CheckConstraint(_in("role", ROLES), name="ck_user_role"),)


class SettingRow(Base):
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(60), primary_key=True)
    value: Mapped[float] = mapped_column(Float)


class IncidentRow(Base):
    """The citizen's report. Its coordinates are locked at submission: the
    worker's task copies them, and nothing a worker sends can change them."""

    __tablename__ = "incidents"

    incident_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    category: Mapped[str] = mapped_column(String(50))
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(String(2000))
    asset_identifier: Mapped[str | None] = mapped_column(String(120), nullable=True)
    status: Mapped[str] = mapped_column(String(30))
    reporter_id: Mapped[str] = mapped_column(String(64), ForeignKey("users.user_id"))
    latitude: Mapped[float] = mapped_column(Float)
    longitude: Mapped[float] = mapped_column(Float)
    # DEVICE_GEOLOCATION (primary) or USER_SELECTED_PIN (labelled fallback).
    location_source: Mapped[str] = mapped_column(String(30))
    location_accuracy_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    location_observed_at: Mapped[datetime | None] = mapped_column(Timestamp, nullable=True)
    # LIVE | SIMULATED | USER_PIN
    location_mode: Mapped[str] = mapped_column(String(12))
    location_flags: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(Timestamp)  # server receipt
    updated_at: Mapped[datetime] = mapped_column(Timestamp)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)

    __table_args__ = (
        CheckConstraint(_in("status", INCIDENT_STATUSES), name="ck_incident_status"),
        CheckConstraint(LAT.format(c="latitude"), name="ck_incident_lat"),
        CheckConstraint(LON.format(c="longitude"), name="ck_incident_lon"),
        Index("ix_incidents_reporter", "reporter_id"),
    )


class TaskRow(Base):
    __tablename__ = "tasks"

    task_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    incident_id: Mapped[str] = mapped_column(String(32), ForeignKey("incidents.incident_id"), unique=True)
    worker_id: Mapped[str] = mapped_column(String(64), ForeignKey("users.user_id"))
    target_latitude: Mapped[float] = mapped_column(Float)
    target_longitude: Mapped[float] = mapped_column(Float)
    # ORIGINAL (the citizen's location) or ADMIN_CORRECTION (audited).
    target_source: Mapped[str] = mapped_column(String(20), default="ORIGINAL")
    status: Mapped[str] = mapped_column(String(30))
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    rework_reason: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    assigned_at: Mapped[datetime] = mapped_column(Timestamp)
    updated_at: Mapped[datetime] = mapped_column(Timestamp)

    __table_args__ = (CheckConstraint(_in("status", TASK_STATUSES), name="ck_task_status"),)


class MediaRow(Base):
    __tablename__ = "media"

    media_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    incident_id: Mapped[str] = mapped_column(String(32), ForeignKey("incidents.incident_id"))
    task_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    attempt: Mapped[int | None] = mapped_column(Integer, nullable=True)
    role: Mapped[str] = mapped_column(String(12))  # REPORT | COMPLETION
    uploaded_by: Mapped[str] = mapped_column(String(64))
    storage_key: Mapped[str] = mapped_column(String(100), unique=True)
    mime_type: Mapped[str] = mapped_column(String(30))
    size_bytes: Mapped[int] = mapped_column(Integer)
    width: Mapped[int] = mapped_column(Integer)
    height: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64))
    # CAMERA_LIVE (in-app camera) | CAMERA_INPUT (phone camera app) | GALLERY (existing file).
    capture_source: Mapped[str] = mapped_column(String(14))
    # Four different times, never conflated:
    captured_at: Mapped[datetime | None] = mapped_column(Timestamp, nullable=True)   # image capture, device clock (in-app camera only)
    exif_datetime_original: Mapped[str | None] = mapped_column(String(32), nullable=True)  # claimed by the file; no timezone
    uploaded_at: Mapped[datetime | None] = mapped_column(Timestamp, nullable=True)   # device clock when sent
    received_at: Mapped[datetime] = mapped_column(Timestamp)                          # server clock
    exif_status: Mapped[str] = mapped_column(String(20))

    __table_args__ = (Index("ix_media_incident", "incident_id"), Index("ix_media_sha", "sha256"))


class EvidenceRow(Base):
    """One location source with provenance."""

    __tablename__ = "location_evidence"

    evidence_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    incident_id: Mapped[str] = mapped_column(String(32), ForeignKey("incidents.incident_id"))
    task_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    attempt: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_type: Mapped[str] = mapped_column(String(30))
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    accuracy_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    observed_at: Mapped[datetime | None] = mapped_column(Timestamp, nullable=True)  # when the source says it measured this
    received_at: Mapped[datetime] = mapped_column(Timestamp)
    media_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    mode: Mapped[str] = mapped_column(String(12))  # LIVE | SIMULATED | USER_PIN | METADATA | ADMIN
    available: Mapped[bool] = mapped_column(Boolean, default=True)
    unavailable_reason: Mapped[str | None] = mapped_column(String(40), nullable=True)
    created_by: Mapped[str] = mapped_column(String(64))

    __table_args__ = (
        CheckConstraint(_in("source_type", SOURCES), name="ck_evidence_source"),
        CheckConstraint(LAT.format(c="latitude"), name="ck_evidence_lat"),
        CheckConstraint(LON.format(c="longitude"), name="ck_evidence_lon"),
        CheckConstraint("available = (latitude IS NOT NULL AND longitude IS NOT NULL)", name="ck_evidence_available"),
        Index("ix_evidence_incident", "incident_id"),
    )


class CompletionRow(Base):
    """Every completion attempt, including rejected ones, so history is kept.
    Only accepted attempts (PASS / REVIEW_REQUIRED) reach a supervisor."""

    __tablename__ = "completions"

    completion_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    task_id: Mapped[str] = mapped_column(String(32), ForeignKey("tasks.task_id"))
    incident_id: Mapped[str] = mapped_column(String(32), ForeignKey("incidents.incident_id"))
    attempt: Mapped[int] = mapped_column(Integer)
    worker_id: Mapped[str] = mapped_column(String(64))
    media_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    device_evidence_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    description: Mapped[str] = mapped_column(String(2000))
    outcome: Mapped[str] = mapped_column(String(20))
    accepted: Mapped[bool] = mapped_column(Boolean)
    result: Mapped[dict] = mapped_column(JSON)
    submitted_at: Mapped[datetime] = mapped_column(Timestamp)
    review_decision: Mapped[str | None] = mapped_column(String(20), nullable=True)
    reviewed_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    review_reason: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(Timestamp, nullable=True)

    __table_args__ = (
        CheckConstraint(_in("outcome", OUTCOMES), name="ck_completion_outcome"),
        Index("ix_completions_task", "task_id"),
    )


# ------------------------------------------------------------------------
# Integration tables (Incident Intelligence, Dispatch, tracking, ETA/ETR).
# They are new tables only: existing tables and columns are unchanged, so an
# existing database gains them through create_all without losing data.
# ------------------------------------------------------------------------
INTELLIGENCE_STATUSES = ("NOT_CONFIGURED", "PENDING", "COMPLETED", "UNAVAILABLE", "FAILED", "CONFLICT")


class IntelligenceRow(Base):
    """Output of the Incident Intelligence agent for one incident. System
    generated, kept apart from what the citizen wrote."""

    __tablename__ = "incident_intelligence"

    incident_id: Mapped[str] = mapped_column(String(32), ForeignKey("incidents.incident_id"), primary_key=True)
    status: Mapped[str] = mapped_column(String(20))
    request_id: Mapped[str] = mapped_column(String(100))  # X-Request-ID sent to the agent (stable per incident)
    external_incident_id: Mapped[str | None] = mapped_column(String(64), nullable=True)  # the agent's INC-... id
    category: Mapped[str | None] = mapped_column(String(40), nullable=True)
    incident_type: Mapped[str | None] = mapped_column(String(40), nullable=True)
    severity: Mapped[str | None] = mapped_column(String(10), nullable=True)
    severity_reason: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    severity_rule_matches: Mapped[list] = mapped_column(JSON, default=list)
    summary: Mapped[str | None] = mapped_column(String(600), nullable=True)
    needs_clarification: Mapped[bool] = mapped_column(Boolean, default=False)
    clarification_questions: Mapped[list] = mapped_column(JSON, default=list)
    missing_information: Mapped[list] = mapped_column(JSON, default=list)
    location_check_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    model_info: Mapped[str | None] = mapped_column(String(80), nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(String(200), nullable=True)
    requested_at: Mapped[datetime | None] = mapped_column(Timestamp, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(Timestamp, nullable=True)

    __table_args__ = (CheckConstraint(_in("status", INTELLIGENCE_STATUSES), name="ck_intel_status"),)


class WorkerProfileRow(Base):
    """What Dispatch needs to know about a worker. The location is the latest
    one the worker shared (check-in or task tracking), never a guess."""

    __tablename__ = "worker_profiles"

    user_id: Mapped[str] = mapped_column(String(64), ForeignKey("users.user_id"), primary_key=True)
    skills: Mapped[list] = mapped_column(JSON, default=list)
    equipment: Mapped[list] = mapped_column(JSON, default=list)
    available: Mapped[bool] = mapped_column(Boolean, default=True)
    max_active_tasks: Mapped[int] = mapped_column(Integer, default=3)
    last_latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_accuracy_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_observed_at: Mapped[datetime | None] = mapped_column(Timestamp, nullable=True)
    last_received_at: Mapped[datetime | None] = mapped_column(Timestamp, nullable=True)
    last_mode: Mapped[str | None] = mapped_column(String(12), nullable=True)  # LIVE | SIMULATED
    last_source: Mapped[str | None] = mapped_column(String(12), nullable=True)  # CHECK_IN | TRACKING

    __table_args__ = (
        CheckConstraint(LAT.format(c="last_latitude"), name="ck_worker_lat"),
        CheckConstraint(LON.format(c="last_longitude"), name="ck_worker_lon"),
    )


class DispatchRow(Base):
    """Every dispatch decision, including ones that found nobody."""

    __tablename__ = "dispatch_records"

    dispatch_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    incident_id: Mapped[str] = mapped_column(String(32), ForeignKey("incidents.incident_id"))
    status: Mapped[str] = mapped_column(String(12))  # ASSIGNED | UNASSIGNED
    method: Mapped[str] = mapped_column(String(30))  # DISPATCH_RANKING | WORKLOAD_FALLBACK | SUPERVISOR_MANUAL | REASSIGNED
    worker_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    priority: Mapped[str] = mapped_column(String(10))
    required_skills: Mapped[list] = mapped_column(JSON, default=list)
    required_equipment: Mapped[list] = mapped_column(JSON, default=list)
    ranking: Mapped[list] = mapped_column(JSON, default=list)
    rejected: Mapped[list] = mapped_column(JSON, default=list)
    reason: Mapped[str] = mapped_column(String(300))
    created_by: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(Timestamp)

    __table_args__ = (Index("ix_dispatch_incident", "incident_id"),)


class TaskProgressRow(Base):
    """Recorded milestone times of a task, and the current resolution estimate.
    Actual durations are computed from these, never from the clock."""

    __tablename__ = "task_progress"

    task_id: Mapped[str] = mapped_column(String(32), ForeignKey("tasks.task_id"), primary_key=True)
    tracking_active: Mapped[bool] = mapped_column(Boolean, default=False)
    tracking_started_at: Mapped[datetime | None] = mapped_column(Timestamp, nullable=True)
    tracking_stopped_at: Mapped[datetime | None] = mapped_column(Timestamp, nullable=True)
    tracking_stop_reason: Mapped[str | None] = mapped_column(String(40), nullable=True)
    arrived_at: Mapped[datetime | None] = mapped_column(Timestamp, nullable=True)
    work_started_at: Mapped[datetime | None] = mapped_column(Timestamp, nullable=True)
    completion_submitted_at: Mapped[datetime | None] = mapped_column(Timestamp, nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(Timestamp, nullable=True)
    etr_due_at: Mapped[datetime | None] = mapped_column(Timestamp, nullable=True)
    etr_basis: Mapped[dict] = mapped_column(JSON, default=dict)
    etr_event: Mapped[str | None] = mapped_column(String(40), nullable=True)
    etr_updated_at: Mapped[datetime | None] = mapped_column(Timestamp, nullable=True)


class LocationPingRow(Base):
    """Worker location shared during an active task. Only the most recent few
    are kept, and they are deleted when the task leaves the field."""

    __tablename__ = "location_pings"

    ping_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    task_id: Mapped[str] = mapped_column(String(32), ForeignKey("tasks.task_id"))
    worker_id: Mapped[str] = mapped_column(String(64))
    latitude: Mapped[float] = mapped_column(Float)
    longitude: Mapped[float] = mapped_column(Float)
    accuracy_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    observed_at: Mapped[datetime | None] = mapped_column(Timestamp, nullable=True)
    received_at: Mapped[datetime] = mapped_column(Timestamp)
    mode: Mapped[str] = mapped_column(String(12))
    distance_to_target_m: Mapped[float] = mapped_column(Float)

    __table_args__ = (
        CheckConstraint(LAT.format(c="latitude"), name="ck_ping_lat"),
        CheckConstraint(LON.format(c="longitude"), name="ck_ping_lon"),
        Index("ix_ping_task", "task_id", "received_at"),
    )


class RequestKeyRow(Base):
    """Idempotency key -> incident, so a retried report is not filed twice."""

    __tablename__ = "request_keys"

    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64))
    incident_id: Mapped[str] = mapped_column(String(32), ForeignKey("incidents.incident_id"))
    created_at: Mapped[datetime] = mapped_column(Timestamp)


class AuditRow(Base):
    __tablename__ = "audit_events"

    event_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    actor_id: Mapped[str] = mapped_column(String(64))
    actor_role: Mapped[str] = mapped_column(String(20))
    action: Mapped[str] = mapped_column(String(60))
    incident_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    event_time: Mapped[datetime] = mapped_column(Timestamp)
    # Safe details only: statuses, codes, distances, reasons. Never raw EXIF.
    details: Mapped[dict] = mapped_column(JSON, default=dict)

    __table_args__ = (Index("ix_audit_incident", "incident_id"),)
