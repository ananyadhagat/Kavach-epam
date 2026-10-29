"""Live worker tracking for an assigned task.

Scope and privacy:
- Only the assigned worker can share a location, only for their own task,
  and only while it is ASSIGNED or IN_PROGRESS.
- The citizen who reported the incident sees the latest position only while
  tracking is active; the supervisor also sees the last known position and
  the short recent history. Nobody else sees it.
- At most TRACKING_HISTORY_KEEP recent points are kept per task, and they are
  deleted when the task leaves the field (completion submitted, reassigned).
- Arrival is an estimate from shared locations. It never replaces the
  server-side geofence check made when the completion is submitted.
- A web page cannot track in the background: sharing stops if permission is
  denied, the device is offline or the page is closed or suspended. Stale
  locations are shown as stale.
"""

from __future__ import annotations

from sqlalchemy import delete, select

from geosatya.location.coordinates import CoordinateError, haversine_m, validate_accuracy, validate_coordinates
from geosatya.models import IncidentRow, LocationPingRow, TaskProgressRow, TaskRow, WorkerProfileRow
from geosatya.services import estimates
from geosatya.services.common import Actor, ServiceError, audit, new_id
from geosatya.timeutil import as_utc, iso, utcnow

ACTIVE = ("ASSIGNED", "IN_PROGRESS")


def progress_of(session, task: TaskRow) -> TaskProgressRow:
    """Tasks created before this feature have no progress row yet; make one."""
    row = session.get(TaskProgressRow, task.task_id)
    if row is None:
        row = TaskProgressRow(task_id=task.task_id, tracking_active=False, etr_basis={})
        session.add(row)
        session.flush()
    return row


def recent_pings(session, task_id: str) -> list[LocationPingRow]:
    return list(session.scalars(select(LocationPingRow).where(LocationPingRow.task_id == task_id)
                                .order_by(LocationPingRow.received_at)))


def _validated(settings, loc: dict) -> tuple[float, float, float | None, str]:
    try:
        lat, lon = validate_coordinates(loc.get("latitude"), loc.get("longitude"))
        acc = validate_accuracy(loc.get("accuracy_m"))
    except CoordinateError as exc:
        raise ServiceError(str(exc), 422, exc.code) from exc
    mode = loc.get("mode", "LIVE")
    if mode == "SIMULATED" and not settings.simulation_allowed:
        raise ServiceError("Simulated locations are not accepted in production.", 422, "SIMULATION_REFUSED")
    return lat, lon, acc, mode


def _remember(session, worker_id: str, lat, lon, acc, observed, mode, source) -> None:
    prof = session.get(WorkerProfileRow, worker_id)
    if prof is None:
        return
    prof.last_latitude, prof.last_longitude, prof.last_accuracy_m = lat, lon, acc
    prof.last_observed_at, prof.last_received_at, prof.last_mode, prof.last_source = as_utc(observed), utcnow(), mode, source


def record_ping(session, settings, categories, task: TaskRow, incident: IncidentRow, actor: Actor, loc: dict) -> dict:
    if actor.role != "WORKER" or task.worker_id != actor.user_id:
        raise ServiceError("Only the assigned worker can share a location for this task.", 403, "NOT_ASSIGNED_WORKER")
    if task.status not in ACTIVE:
        raise ServiceError(f"Location sharing is only for an active task (this one is {task.status}).", 409, "TASK_NOT_ACTIVE")
    lat, lon, acc, mode = _validated(settings, loc)
    now = utcnow()
    progress = progress_of(session, task)
    pings = recent_pings(session, task.task_id)
    if pings and (now - as_utc(pings[-1].received_at)).total_seconds() < settings.tracking_min_interval_s:
        return {"stored": False, "reason": "TOO_FREQUENT", "min_interval_s": settings.tracking_min_interval_s}

    distance = haversine_m(task.target_latitude, task.target_longitude, lat, lon)
    ping = LocationPingRow(ping_id=new_id("PNG", 5), task_id=task.task_id, worker_id=actor.user_id, latitude=lat,
                           longitude=lon, accuracy_m=acc, observed_at=as_utc(loc.get("observed_at")), received_at=now,
                           mode=mode, distance_to_target_m=distance)
    session.add(ping)
    _remember(session, actor.user_id, lat, lon, acc, loc.get("observed_at"), mode, "TRACKING")
    if not progress.tracking_active:
        progress.tracking_active, progress.tracking_stopped_at, progress.tracking_stop_reason = True, None, None
        progress.tracking_started_at = progress.tracking_started_at or now
        audit(session, actor, "TRACKING_STARTED", incident.incident_id, task_id=task.task_id)

    arrived_now = False
    # Arrival: within the arrival radius, with accuracy good enough to say so.
    if (progress.arrived_at is None and distance <= settings.arrival_radius_m
            and (acc is None or acc <= max(settings.arrival_radius_m, 50))):
        progress.arrived_at, arrived_now = now, True
        audit(session, actor, "ARRIVAL_DETECTED", incident.incident_id, distance_m=round(distance, 1),
              accuracy_m=acc, simulated=mode == "SIMULATED", note="Estimated from shared location; not the geofence check")
    session.flush()

    # Keep only the most recent points.
    pings = recent_pings(session, task.task_id)
    for old in pings[:-settings.tracking_history_keep]:
        session.delete(old)
    pings = pings[-settings.tracking_history_keep:]
    if arrived_now or progress.etr_event in (None, "ASSIGNED", "REASSIGNED") and len(pings) == 1:
        # Meaningful events only: first location (travel becomes known) and arrival.
        info = estimates.eta(task, progress, pings, settings, now)
        estimates.recompute_etr(session, settings, categories, task, incident, progress,
                                "ARRIVED" if arrived_now else "FIRST_LOCATION", info, now)
    session.flush()
    return {"stored": True, "distance_m": round(distance, 1), "arrived": progress.arrived_at is not None}


def stop_tracking(session, task: TaskRow, reason: str, *, purge: bool = False) -> None:
    progress = session.get(TaskProgressRow, task.task_id)
    if progress is not None and progress.tracking_active:
        progress.tracking_active, progress.tracking_stopped_at, progress.tracking_stop_reason = False, utcnow(), reason
    if purge:
        session.execute(delete(LocationPingRow).where(LocationPingRow.task_id == task.task_id))
    session.flush()


def check_in(session, settings, actor: Actor, available: bool, loc: dict | None) -> WorkerProfileRow:
    """A worker marks themselves available (or not), optionally with one
    location reading so Dispatch can consider distance. Not continuous tracking."""
    prof = session.get(WorkerProfileRow, actor.user_id)
    if prof is None:
        raise ServiceError("No worker profile exists for this user.", 404, "NO_PROFILE")
    prof.available = available
    if loc:
        lat, lon, acc, mode = _validated(settings, loc)
        _remember(session, actor.user_id, lat, lon, acc, loc.get("observed_at"), mode, "CHECK_IN")
    audit(session, actor, "WORKER_CHECK_IN", None, available=available, location_shared=bool(loc))
    session.flush()
    return prof


def can_view(actor: Actor, task: TaskRow, incident: IncidentRow) -> bool:
    return (actor.role == "SUPERVISOR" or (actor.role == "WORKER" and task.worker_id == actor.user_id)
            or (actor.role == "CITIZEN" and incident.reporter_id == actor.user_id))


def tracking_view(session, settings, task: TaskRow, incident: IncidentRow, actor: Actor) -> dict:
    progress = progress_of(session, task)
    pings = recent_pings(session, task.task_id)
    now = utcnow()
    latest = pings[-1] if pings else None
    age = (now - as_utc(latest.received_at)).total_seconds() if latest else None
    if task.status not in ACTIVE:
        state = "ENDED"
    elif not progress.tracking_active:
        state = "STOPPED" if progress.tracking_stopped_at else "NOT_STARTED"
    else:
        state = "STALE" if age is None or age > settings.tracking_stale_s else "LIVE"
    show_location = latest is not None and (actor.role != "CITIZEN" or (progress.tracking_active and task.status in ACTIVE))
    data = {
        "task_id": task.task_id, "task_status": task.status, "state": state,
        "tracking_started_at": iso(progress.tracking_started_at), "tracking_stopped_at": iso(progress.tracking_stopped_at),
        "stop_reason": progress.tracking_stop_reason, "arrived_at": iso(progress.arrived_at),
        "arrival_note": "Estimated from shared location; the work is still checked against the incident location on completion.",
        "work_started_at": iso(progress.work_started_at), "stale_after_s": settings.tracking_stale_s,
        "target": {"latitude": task.target_latitude, "longitude": task.target_longitude},
        "latest": None, "eta": estimates.eta(task, progress, pings, settings, now),
        "etr": estimates.etr_view(task, progress, incident, now),
    }
    if show_location:
        data["latest"] = {"latitude": latest.latitude, "longitude": latest.longitude, "accuracy_m": latest.accuracy_m,
                          "received_at": iso(latest.received_at), "observed_at": iso(latest.observed_at),
                          "age_s": int(age), "mode": latest.mode, "distance_m": round(latest.distance_to_target_m),
                          "kind": "CURRENT" if state == "LIVE" else "LAST_KNOWN"}
    if actor.role == "SUPERVISOR":
        data["history"] = [{"latitude": p.latitude, "longitude": p.longitude, "received_at": iso(p.received_at),
                            "distance_m": round(p.distance_to_target_m)} for p in pings]
    return data
