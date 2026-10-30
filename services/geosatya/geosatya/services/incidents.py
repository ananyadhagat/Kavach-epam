"""Citizen reports. A saved report goes to Incident Intelligence and then to
Dispatch, which normally turns it into a worker task automatically."""

from __future__ import annotations

from geosatya.location.coordinates import CoordinateError, haversine_m, validate_coordinates
from geosatya.models import EvidenceRow, IncidentRow, TaskRow
from geosatya.services import estimates
from geosatya.services.common import (
    Actor, ServiceError, audit, device_evidence, get_limits, incident_id, new_id, store_photo,
)
from geosatya.services.dispatch import dispatch_incident
from geosatya.services.intelligence import run_intelligence
from geosatya.services.tracking import progress_of, recent_pings
from geosatya.timeutil import utcnow


def create_incident(session, storage, settings, categories, actor: Actor, payload: dict, photos: list[tuple[bytes, dict]],
                    *, is_demo: bool = False) -> IncidentRow:
    category = categories.get(payload["category"])
    if category is None:
        raise ServiceError("Unknown category.", 422, "UNKNOWN_CATEGORY")
    if not photos:
        raise ServiceError("Add a photograph of the issue.", 422, "PHOTO_REQUIRED")
    device, pin = payload.get("device_location"), payload.get("user_location")

    # The primary location is the device's. A map pin is only a labelled fallback.
    if device:
        try:
            lat, lon = validate_coordinates(device["latitude"], device["longitude"])
        except CoordinateError as exc:
            raise ServiceError(f"Device location: {exc}", 422, exc.code) from exc
        source, accuracy, observed, mode = "DEVICE_GEOLOCATION", device.get("accuracy_m"), device.get("observed_at"), device.get("mode", "LIVE")
    elif pin:
        try:
            lat, lon = validate_coordinates(pin["latitude"], pin["longitude"])
        except CoordinateError as exc:
            raise ServiceError(f"Selected location: {exc}", 422, exc.code) from exc
        source, accuracy, observed, mode = "USER_SELECTED_PIN", None, None, "USER_PIN"
    else:
        raise ServiceError("The report needs a location: allow device location, or choose the spot on the map.", 422, "LOCATION_REQUIRED")

    now = utcnow()
    incident = IncidentRow(
        incident_id=incident_id(), category=category["id"], title=payload["title"].strip(),
        description=payload["description"].strip(), asset_identifier=payload.get("asset_identifier"),
        status="SUBMITTED", reporter_id=actor.user_id, latitude=lat, longitude=lon, location_source=source,
        location_accuracy_m=accuracy, location_observed_at=observed, location_mode=mode, location_flags=[],
        created_at=now, updated_at=now, is_demo=is_demo)
    session.add(incident)
    session.flush()

    # Each location source is kept as its own evidence row.
    first_media = None
    exif_rows, sources = [], []
    for data, meta in photos:
        media, exif = store_photo(session, storage, settings, data=data, incident=incident.incident_id, task=None,
                                  attempt=None, role="REPORT", meta=meta, actor=actor)
        first_media = first_media or media
        exif_rows.append(exif)
        sources.append(media.capture_source)
    # The device fix, or the reason there isn't one, is always recorded.
    device_evidence(session, incident=incident.incident_id, task=None, attempt=None, actor=actor, device=device,
                    error=payload.get("device_location_error"), settings=settings, media_id=first_media.media_id)
    if pin:
        session.add(EvidenceRow(evidence_id=new_id("LOC", 5), incident_id=incident.incident_id, source_type="USER_SELECTED_PIN",
                                latitude=pin["latitude"], longitude=pin["longitude"], received_at=now, mode="USER_PIN",
                                available=True, created_by=actor.user_id))

    # Honest flags, shown to the supervisor instead of hidden.
    flags: list[str] = []  # a fresh list: JSON columns don't track in-place changes
    if source == "USER_SELECTED_PIN":
        flags.append("USER_SELECTED_LOCATION")
    if mode == "SIMULATED":
        flags.append("SIMULATED_LOCATION")
    limits = get_limits(session, settings)
    if accuracy and accuracy > limits["max_accuracy_m"]:
        flags.append("LOW_GPS_ACCURACY")
    if source == "DEVICE_GEOLOCATION" and sources and all(s == "GALLERY" for s in sources):
        flags.append("PHOTO_FROM_GALLERY")  # location is where the citizen was at upload, not where the photo was taken
    for row in exif_rows:
        if row.available:
            apart = haversine_m(lat, lon, row.latitude, row.longitude)
            if apart > max(settings.exif_tolerance_m, accuracy or 0):
                flags.append("PHOTO_GPS_CONFLICT")
    incident.location_flags = list(dict.fromkeys(flags))
    audit(session, actor, "INCIDENT_REPORTED", incident.incident_id, category=category["id"], location_source=source,
          location_mode=mode, flags=incident.location_flags)
    session.flush()
    return incident


def process_incident(session, storage, settings, categories, intelligence_client, incident: IncidentRow,
                     *, router=None) -> TaskRow | None:
    """After the report is committed: Incident Intelligence, then Dispatch.
    Intelligence failing never blocks dispatch; it only leaves the priority NORMAL."""
    run_intelligence(session, storage, intelligence_client, incident)
    task = dispatch_incident(session, settings, categories, incident, router=router)
    if task is not None:
        refresh_etr(session, settings, categories, task, incident, "ASSIGNED")
    return task


def refresh_etr(session, settings, categories, task: TaskRow, incident: IncidentRow, event: str) -> None:
    progress = progress_of(session, task)
    info = estimates.eta(task, progress, recent_pings(session, task.task_id), settings)
    estimates.recompute_etr(session, settings, categories, task, incident, progress, event, info)
    session.flush()


def correct_task_location(session, incident: IncidentRow, task: TaskRow, actor: Actor, lat: float, lon: float, reason: str) -> None:
    """Supervisor-only. The citizen's original coordinates stay as submitted;
    only the task's target changes, and the change is audited with a reason."""
    if len(reason.strip()) < 5:
        raise ServiceError("A reason is required to correct a location.", 422, "REASON_REQUIRED")
    if task.status not in ("ASSIGNED", "IN_PROGRESS"):
        raise ServiceError("The target can only be corrected before the work is submitted.", 409, "TASK_LOCKED")
    try:
        lat, lon = validate_coordinates(lat, lon)
    except CoordinateError as exc:
        raise ServiceError(str(exc), 422, exc.code) from exc
    moved = haversine_m(task.target_latitude, task.target_longitude, lat, lon)
    session.add(EvidenceRow(evidence_id=new_id("LOC", 5), incident_id=incident.incident_id, task_id=task.task_id,
                            source_type="ADMIN_CORRECTION", latitude=lat, longitude=lon, received_at=utcnow(),
                            mode="ADMIN", available=True, created_by=actor.user_id))
    audit(session, actor, "LOCATION_CORRECTED", incident.incident_id, reason=reason.strip()[:300],
          moved_m=round(moved, 1), original_kept=True)
    task.target_latitude, task.target_longitude, task.target_source = lat, lon, "ADMIN_CORRECTION"
    task.updated_at = utcnow()
