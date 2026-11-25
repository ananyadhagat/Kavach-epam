"""KAVACH platform tables: tenants (organization and event workspaces), their
structure (departments, zones), worker invitations, commercial plans and
public-authority jurisdictions.

GeoSatya's own tables are unchanged apart from nullable tenancy columns on
users and incidents (see models.py). These tables only add to the schema."""

from datetime import datetime

from sqlalchemy import JSON, Boolean, CheckConstraint, Float, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from geosatya.models import LAT, LON, Base, Timestamp, _in

WORKSPACE_KINDS = ("ORGANIZATION", "EVENT")
# Verification of an organization's identity on Kavach. It never means the
# organization is affiliated with, or endorsed by, a government body.
VERIFICATION = ("UNVERIFIED", "PENDING", "VERIFIED", "REJECTED", "DEMO")
SUBSCRIPTION = ("TRIAL", "ACTIVE", "PAST_DUE", "CANCELLED", "DEMO")
AUTHORITY_KINDS = ("MUNICIPAL", "STATE_HIGHWAY", "NATIONAL_HIGHWAY", "UTILITY", "OTHER")


class PlanRow(Base):
    """A commercial plan: limits and features only. Prices are not set in code;
    they are commercial decisions and stay empty until confirmed."""

    __tablename__ = "kavach_plans"

    plan_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(80))
    audience: Mapped[str] = mapped_column(String(20))  # EVENT | ORGANIZATION | ANY
    billing_basis: Mapped[str] = mapped_column(String(30))  # PER_EVENT | DURATION | WORKER_COUNT | SUBSCRIPTION | CUSTOM
    max_workers: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_events: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_supervisors: Mapped[int | None] = mapped_column(Integer, nullable=True)
    features: Mapped[list] = mapped_column(JSON, default=list)
    price_note: Mapped[str | None] = mapped_column(String(120), nullable=True)


class WorkspaceRow(Base):
    """A tenant. Every incident, worker and supervisor inside it is isolated
    from other workspaces on the server."""

    __tablename__ = "kavach_workspaces"

    workspace_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    kind: Mapped[str] = mapped_column(String(14))
    name: Mapped[str] = mapped_column(String(120))
    category: Mapped[str] = mapped_column(String(40))
    description: Mapped[str] = mapped_column(String(1000), default="")
    owner_id: Mapped[str] = mapped_column(String(64), ForeignKey("users.user_id"))
    # For events: the organizer's company. For organizations: the legal name.
    organization_name: Mapped[str | None] = mapped_column(String(160), nullable=True)
    contact_email: Mapped[str | None] = mapped_column(String(160), nullable=True)
    verification_status: Mapped[str] = mapped_column(String(12), default="UNVERIFIED")
    verification_note: Mapped[str | None] = mapped_column(String(300), nullable=True)
    # Venue or service area: a centre and radius (a simple geofence).
    venue: Mapped[str | None] = mapped_column(String(200), nullable=True)
    center_latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    center_longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    radius_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    starts_at: Mapped[datetime | None] = mapped_column(Timestamp, nullable=True)
    ends_at: Mapped[datetime | None] = mapped_column(Timestamp, nullable=True)
    # Configuration edited from the UI: enabled categories, priority levels,
    # worker roles, notification and dashboard preferences.
    settings: Mapped[dict] = mapped_column(JSON, default=dict)
    plan_id: Mapped[str | None] = mapped_column(String(32), ForeignKey("kavach_plans.plan_id"), nullable=True)
    subscription_status: Mapped[str] = mapped_column(String(12), default="TRIAL")
    renews_at: Mapped[datetime | None] = mapped_column(Timestamp, nullable=True)
    status: Mapped[str] = mapped_column(String(12), default="ACTIVE")  # ACTIVE | ARCHIVED
    created_at: Mapped[datetime] = mapped_column(Timestamp)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)

    __table_args__ = (
        CheckConstraint(_in("kind", WORKSPACE_KINDS), name="ck_ws_kind"),
        CheckConstraint(_in("verification_status", VERIFICATION), name="ck_ws_verification"),
        CheckConstraint(_in("subscription_status", SUBSCRIPTION), name="ck_ws_subscription"),
        CheckConstraint(LAT.format(c="center_latitude"), name="ck_ws_lat"),
        CheckConstraint(LON.format(c="center_longitude"), name="ck_ws_lon"),
        Index("ix_ws_owner", "owner_id"),
    )


class DepartmentRow(Base):
    __tablename__ = "kavach_departments"

    department_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String(32), ForeignKey("kavach_workspaces.workspace_id"))
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(String(500), default="")
    # Incident categories this department handles (used for display and filters).
    categories: Mapped[list] = mapped_column(JSON, default=list)
    supervisor_id: Mapped[str | None] = mapped_column(String(64), ForeignKey("users.user_id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(Timestamp)


class ZoneRow(Base):
    """An operational area inside a workspace (event zone or service ward)."""

    __tablename__ = "kavach_zones"

    zone_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String(32), ForeignKey("kavach_workspaces.workspace_id"))
    name: Mapped[str] = mapped_column(String(120))
    kind: Mapped[str] = mapped_column(String(30), default="AREA")
    latitude: Mapped[float] = mapped_column(Float)
    longitude: Mapped[float] = mapped_column(Float)
    radius_m: Mapped[float] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(Timestamp)

    __table_args__ = (
        CheckConstraint(LAT.format(c="latitude"), name="ck_zone_lat"),
        CheckConstraint(LON.format(c="longitude"), name="ck_zone_lon"),
    )


class InviteRow(Base):
    """A one-time code a worker or supervisor uses to join a workspace."""

    __tablename__ = "kavach_invites"

    code: Mapped[str] = mapped_column(String(16), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String(32), ForeignKey("kavach_workspaces.workspace_id"))
    role: Mapped[str] = mapped_column(String(12))  # WORKER | SUPERVISOR
    skills: Mapped[list] = mapped_column(JSON, default=list)
    department_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    label: Mapped[str | None] = mapped_column(String(120), nullable=True)
    created_by: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(Timestamp)
    used_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    used_at: Mapped[datetime | None] = mapped_column(Timestamp, nullable=True)


class AuthorityRow(Base):
    """A public authority and the area and categories it is responsible for.

    This is configuration, not an integration: Kavach suggests the authority
    and, if that authority runs a workspace here, routes the report to it.
    Nothing is submitted to an external government system."""

    __tablename__ = "kavach_authorities"

    authority_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(160))
    kind: Mapped[str] = mapped_column(String(20))
    # Simple circular jurisdiction; replace with official boundary data when available.
    center_latitude: Mapped[float] = mapped_column(Float)
    center_longitude: Mapped[float] = mapped_column(Float)
    radius_km: Mapped[float] = mapped_column(Float)
    categories: Mapped[list] = mapped_column(JSON, default=list)  # empty = all
    road_types: Mapped[list] = mapped_column(JSON, default=list)  # e.g. ["NATIONAL_HIGHWAY"]; empty = any
    workspace_id: Mapped[str | None] = mapped_column(String(32), ForeignKey("kavach_workspaces.workspace_id"), nullable=True)
    contact: Mapped[str | None] = mapped_column(String(200), nullable=True)
    integration: Mapped[str] = mapped_column(String(20), default="NONE")  # NONE = manual forwarding only
    data_note: Mapped[str | None] = mapped_column(String(200), nullable=True)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)

    __table_args__ = (CheckConstraint(_in("kind", AUTHORITY_KINDS), name="ck_authority_kind"),)


class AgentRunRow(Base):
    """One team agent's latest result for one incident (Duplicate Detection,
    Supervisor, Sanitation Planning). Advisory: kept beside GeoSatya's own
    records and never used to change them."""

    __tablename__ = "kavach_agent_runs"

    incident_id: Mapped[str] = mapped_column(String(32), ForeignKey("incidents.incident_id"), primary_key=True)
    agent: Mapped[str] = mapped_column(String(30), primary_key=True)  # DUPLICATE_DETECTION | SUPERVISOR | SANITATION
    status: Mapped[str] = mapped_column(String(20))  # COMPLETED | UNAVAILABLE | FAILED | REJECTED | NOT_APPLICABLE | NOT_CONFIGURED
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    request: Mapped[dict] = mapped_column(JSON, default=dict)  # what was sent (no personal data beyond the report)
    error: Mapped[str | None] = mapped_column(String(200), nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(Timestamp)


class TaskChecklistRow(Base):
    """Steps the worker ticked for one attempt of a task. A step not ticked
    is unknown, never 'not done' (the Verification agent's own rule)."""

    __tablename__ = "kavach_task_checklists"

    task_id: Mapped[str] = mapped_column(String(32), ForeignKey("tasks.task_id"), primary_key=True)
    attempt: Mapped[int] = mapped_column(Integer, primary_key=True)
    completed: Mapped[list] = mapped_column(JSON, default=list)
    updated_by: Mapped[str] = mapped_column(String(64))
    updated_at: Mapped[datetime] = mapped_column(Timestamp)


# ------------------------------------------------------------------ women's safety
# Private to the signed-in user. Kept apart from the shared audit log (which supervisors
# can read) so allies, SOS history and locations can never leak through it.
class TrustedAllyRow(Base):
    __tablename__ = "kavach_trusted_allies"

    ally_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), ForeignKey("users.user_id"))
    name: Mapped[str] = mapped_column(String(80))
    phone: Mapped[str] = mapped_column(String(20))
    relationship: Mapped[str] = mapped_column(String(20))
    consent_at: Mapped[datetime] = mapped_column(Timestamp)  # when the user agreed to share with this person
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(Timestamp)
    updated_at: Mapped[datetime] = mapped_column(Timestamp)

    __table_args__ = (Index("ix_ally_user", "user_id"),)


class SosRow(Base):
    __tablename__ = "kavach_sos"

    sos_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), ForeignKey("users.user_id"))
    status: Mapped[str] = mapped_column(String(12))  # ACTIVE | CANCELLED | RESOLVED | EXPIRED
    method: Mapped[str] = mapped_column(String(14))  # BUTTON | LONG_PRESS
    triggered_at: Mapped[datetime] = mapped_column(Timestamp)  # server time of the trigger
    # SHARING (live phone GPS received) | MANUAL (a hand-placed point, not GPS) | WAITING_FOR_GPS (nothing usable yet)
    location_status: Mapped[str] = mapped_column(String(16), default="WAITING_FOR_GPS")
    location_error: Mapped[str | None] = mapped_column(String(30), nullable=True)
    last_latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_accuracy_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_observed_at: Mapped[datetime | None] = mapped_column(Timestamp, nullable=True)
    last_received_at: Mapped[datetime | None] = mapped_column(Timestamp, nullable=True)
    last_mode: Mapped[str | None] = mapped_column(String(8), nullable=True)  # LIVE | MANUAL
    updates: Mapped[int] = mapped_column(Integer, default=0)
    ended_at: Mapped[datetime | None] = mapped_column(Timestamp, nullable=True)
    ended_reason: Mapped[str | None] = mapped_column(String(30), nullable=True)

    __table_args__ = (
        CheckConstraint(_in("status", ("ACTIVE", "CANCELLED", "RESOLVED", "EXPIRED")), name="ck_sos_status"),
        CheckConstraint(LAT.format(c="last_latitude"), name="ck_sos_lat"),
        CheckConstraint(LON.format(c="last_longitude"), name="ck_sos_lon"),
        Index("ix_sos_user", "user_id"),
    )


class SosEventRow(Base):
    __tablename__ = "kavach_sos_events"

    event_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    sos_id: Mapped[str] = mapped_column(String(32), ForeignKey("kavach_sos.sos_id"))
    event: Mapped[str] = mapped_column(String(24))
    at: Mapped[datetime] = mapped_column(Timestamp)
    details: Mapped[dict] = mapped_column(JSON, default=dict)


class SosNotificationRow(Base):
    """What was (or was not) sent to each trusted ally. status is never SENT unless a
    delivery provider really confirmed it; today none is connected, so it stays
    PENDING_INTEGRATION and the user sends the link from their own phone."""

    __tablename__ = "kavach_sos_notifications"

    notification_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    sos_id: Mapped[str] = mapped_column(String(32), ForeignKey("kavach_sos.sos_id"))
    ally_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    ally_name: Mapped[str] = mapped_column(String(80))      # snapshot, so history survives a removed ally
    ally_phone: Mapped[str] = mapped_column(String(20))
    relationship: Mapped[str] = mapped_column(String(20))
    kind: Mapped[str] = mapped_column(String(12))            # ALERT | CANCELLED | RESOLVED
    channel: Mapped[str] = mapped_column(String(12))         # SMS_WHATSAPP | PUSH
    status: Mapped[str] = mapped_column(String(22))          # PENDING_INTEGRATION | SENT | FAILED
    token: Mapped[str | None] = mapped_column(String(48), nullable=True, unique=True)  # the ally's private link
    created_at: Mapped[datetime] = mapped_column(Timestamp)
    last_opened_at: Mapped[datetime | None] = mapped_column(Timestamp, nullable=True)

    __table_args__ = (Index("ix_sosnote_sos", "sos_id"),)


class FeedbackRow(Base):
    """A citizen's rating of how their resolved complaint was handled."""

    __tablename__ = "kavach_feedback"

    incident_id: Mapped[str] = mapped_column(String(32), ForeignKey("incidents.incident_id"), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), ForeignKey("users.user_id"))
    rating: Mapped[int] = mapped_column(Integer)
    comment: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(Timestamp)

    __table_args__ = (CheckConstraint("rating >= 1 AND rating <= 5", name="ck_feedback_rating"),)


class AudioNoteRow(Base):
    """An optional voice note: a citizen explaining an SOS, or a field worker
    adding information when completing a task. The audio file lives in private
    storage (never a public folder) and is served only through authorized routes.
    Recording is never required; the note does not change any GeoSatya decision."""

    __tablename__ = "kavach_audio_notes"

    note_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    kind: Mapped[str] = mapped_column(String(12))                     # SOS | COMPLETION
    sos_id: Mapped[str | None] = mapped_column(String(32), ForeignKey("kavach_sos.sos_id"), nullable=True)
    task_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    incident_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    completion_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    attempt: Mapped[int | None] = mapped_column(Integer, nullable=True)
    uploaded_by: Mapped[str] = mapped_column(String(64), ForeignKey("users.user_id"))
    storage_key: Mapped[str] = mapped_column(String(100), unique=True)
    mime_type: Mapped[str] = mapped_column(String(30))
    size_bytes: Mapped[int] = mapped_column(Integer)
    duration_s: Mapped[float | None] = mapped_column(Float, nullable=True)   # as reported by the recorder
    sha256: Mapped[str] = mapped_column(String(64))
    received_at: Mapped[datetime] = mapped_column(Timestamp)

    __table_args__ = (
        CheckConstraint(_in("kind", ("SOS", "COMPLETION")), name="ck_audio_kind"),
        Index("ix_audio_sos", "sos_id"),
        Index("ix_audio_task", "task_id"),
    )
