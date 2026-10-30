from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from geosatya.config import ACCURACY_MAX_M, ACCURACY_MIN_M, GEOFENCE_MAX_M, GEOFENCE_MIN_M, Settings
from geosatya.location.coordinates import CoordinateError, validate_accuracy, validate_coordinates
from geosatya.location.exif_gps import read_exif_gps
from geosatya.location.geofence import Policy
from geosatya.media.image_checks import validate_image
from geosatya.media.storage import LocalImageStorage
from geosatya.models import AuditRow, EvidenceRow, IncidentRow, MediaRow, SettingRow, TaskRow
from geosatya.timeutil import as_utc, utcnow

DEVICE_ERRORS = ("PERMISSION_DENIED", "TIMEOUT", "POSITION_UNAVAILABLE", "UNSUPPORTED", "NOT_REQUESTED")
CAPTURE_SOURCES = ("CAMERA_LIVE", "CAMERA_INPUT", "GALLERY")


class ServiceError(Exception):
    def __init__(self, message: str, status_code: int = 409, code: str = "CONFLICT") -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code


@dataclass(frozen=True)
class Actor:
    user_id: str
    role: str
    display_name: str = ""


def new_id(prefix: str, nbytes: int = 4) -> str:
    return f"{prefix}-{secrets.token_hex(nbytes).upper()}"


def incident_id() -> str:
    """The one ID people see: short, no look-alike characters."""
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return "GS-" + "".join(secrets.choice(alphabet) for _ in range(6))


def audit(session: Session, actor: Actor, action: str, incident: str | None, **details) -> None:
    session.add(AuditRow(event_id=new_id("EVT", 6), actor_id=actor.user_id, actor_role=actor.role,
                         action=action, incident_id=incident, event_time=utcnow(), details=details))


# ----------------------------------------------------------- settings
def get_limits(session: Session, settings: Settings) -> dict:
    """Geofence radius and accuracy limit: the stored value, else the env default."""
    stored = {r.key: r.value for r in session.scalars(select(SettingRow))}
    return {"geofence_radius_m": stored.get("geofence_radius_m", settings.geofence_radius_m),
            "max_accuracy_m": stored.get("max_accuracy_m", settings.max_accuracy_m)}


def set_limits(session: Session, settings: Settings, actor: Actor, radius: float, accuracy: float) -> dict:
    if not GEOFENCE_MIN_M <= radius <= GEOFENCE_MAX_M:
        raise ServiceError(f"Geofence radius must be {GEOFENCE_MIN_M:g}–{GEOFENCE_MAX_M:g} m.", 422, "INVALID_RADIUS")
    if not ACCURACY_MIN_M <= accuracy <= ACCURACY_MAX_M:
        raise ServiceError(f"Accuracy limit must be {ACCURACY_MIN_M:g}–{ACCURACY_MAX_M:g} m.", 422, "INVALID_ACCURACY")
    old = get_limits(session, settings)
    for key, value in (("geofence_radius_m", radius), ("max_accuracy_m", accuracy)):
        row = session.get(SettingRow, key)
        if row is None:
            session.add(SettingRow(key=key, value=value))
        else:
            row.value = value
    audit(session, actor, "SETTINGS_CHANGED", None, old=old, new={"geofence_radius_m": radius, "max_accuracy_m": accuracy})
    session.flush()
    return get_limits(session, settings)


def make_policy(session: Session, settings: Settings) -> Policy:
    limits = get_limits(session, settings)
    return Policy(radius_m=limits["geofence_radius_m"], max_accuracy_m=limits["max_accuracy_m"],
                  exif_tolerance_m=settings.exif_tolerance_m, simulated_can_pass=settings.simulated_may_pass)


# ---------------------------------------------------------- lifecycle
INCIDENT_NEXT = {
    "SUBMITTED": {"ASSIGNED"},
    # SUBMITTED = assignment released (declined, acceptance timed out, cancelled) and no one else was found
    "ASSIGNED": {"IN_PROGRESS", "SUBMITTED"},
    "IN_PROGRESS": {"AWAITING_VERIFICATION", "ASSIGNED", "SUBMITTED"},  # ASSIGNED = reassigned by a supervisor
    "AWAITING_VERIFICATION": {"RESOLVED", "ASSIGNED"},  # ASSIGNED = sent back for rework
    "RESOLVED": set(),
}


def move_incident(session: Session, incident: IncidentRow, to: str, actor: Actor, reason: str = "") -> None:
    if to not in INCIDENT_NEXT.get(incident.status, set()):
        raise ServiceError(f"An incident cannot move from {incident.status} to {to}.", 409, "INVALID_TRANSITION")
    audit(session, actor, "STATUS_CHANGED", incident.incident_id, from_status=incident.status, to_status=to, reason=reason[:500])
    incident.status = to
    incident.updated_at = utcnow()


def set_task_status(task: TaskRow, status: str) -> None:
    task.status = status
    task.updated_at = utcnow()


# ------------------------------------------------------ device location
def device_evidence(session: Session, *, incident: str, task: str | None, attempt: int | None, actor: Actor,
                    device: dict | None, error: str | None, settings: Settings, media_id: str | None = None) -> EvidenceRow:
    """Store the browser fix, or the reason there isn't one, as its own row."""
    now = utcnow()
    if device:
        try:
            lat, lon = validate_coordinates(device.get("latitude"), device.get("longitude"))
            accuracy = validate_accuracy(device.get("accuracy_m"))
        except CoordinateError as exc:
            raise ServiceError(str(exc), 422, exc.code) from exc
        mode = device.get("mode", "LIVE")
        if mode == "SIMULATED" and not settings.simulation_allowed:
            raise ServiceError("Simulated locations are not accepted in production.", 422, "SIMULATION_REFUSED")
        row = EvidenceRow(evidence_id=new_id("LOC", 5), incident_id=incident, task_id=task, attempt=attempt,
                          source_type="DEVICE_GEOLOCATION", latitude=lat, longitude=lon, accuracy_m=accuracy,
                          observed_at=as_utc(device.get("observed_at")), received_at=now, media_id=media_id,
                          mode=mode, available=True, created_by=actor.user_id)
    else:
        reason = error or "NOT_REQUESTED"
        if reason not in DEVICE_ERRORS:
            raise ServiceError(f"location error must be one of {DEVICE_ERRORS}", 422, "INVALID_REASON")
        row = EvidenceRow(evidence_id=new_id("LOC", 5), incident_id=incident, task_id=task, attempt=attempt,
                          source_type="DEVICE_GEOLOCATION", received_at=now, media_id=media_id, mode="LIVE",
                          available=False, unavailable_reason=reason, created_by=actor.user_id)
    session.add(row)
    return row


def store_photo(session: Session, storage: LocalImageStorage, settings: Settings, *, data: bytes, incident: str,
                task: str | None, attempt: int | None, role: str, meta: dict, actor: Actor) -> tuple[MediaRow, EvidenceRow]:
    """Validate and store a photo, with its EXIF GPS (or why it has none) as
    a separate IMAGE_EXIF location source. The four times stay separate."""
    source = meta.get("capture_source", "GALLERY")
    if source not in CAPTURE_SOURCES:
        raise ServiceError(f"capture_source must be one of {CAPTURE_SOURCES}", 422, "INVALID_CAPTURE_SOURCE")
    info = validate_image(data, max_bytes=settings.max_image_size_bytes, max_pixels=settings.max_image_pixels)
    exif = read_exif_gps(data)
    now = utcnow()
    media = MediaRow(
        media_id=new_id("MED", 5), incident_id=incident, task_id=task, attempt=attempt, role=role,
        uploaded_by=actor.user_id, storage_key="pending", mime_type=info.mime_type, size_bytes=info.size_bytes,
        width=info.width, height=info.height, sha256=info.sha256, capture_source=source,
        # Only the in-app camera knows the capture moment; a file's modified time is not it.
        captured_at=as_utc(meta.get("captured_at")) if source == "CAMERA_LIVE" else None,
        exif_datetime_original=exif.datetime_original, uploaded_at=as_utc(meta.get("uploaded_at")),
        received_at=now, exif_status=exif.status)
    evidence = EvidenceRow(
        evidence_id=new_id("LOC", 5), incident_id=incident, task_id=task, attempt=attempt, source_type="IMAGE_EXIF",
        latitude=exif.latitude, longitude=exif.longitude, observed_at=None, received_at=now,
        media_id=media.media_id, mode="METADATA", available=exif.has_gps,
        unavailable_reason=None if exif.has_gps else exif.status, created_by=actor.user_id)
    media.storage_key = storage.save(data, info.mime_type)
    try:
        session.add(media)
        session.flush()
        session.add(evidence)
        session.flush()
    except Exception:
        storage.delete(media.storage_key)
        raise
    return media, evidence
