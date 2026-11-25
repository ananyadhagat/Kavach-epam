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

from sqlalchemy import delete, func, select

from geosatya.location.coordinates import CoordinateError, haversine_m, validate_accuracy, validate_coordinates
from datetime import timedelta

from geosatya.models import IncidentRow, LocationPingRow, ProgressUpdateRow, TaskProgressRow, TaskRow, UserRow, WorkerProfileRow
from geosatya.services import estimates
from geosatya.services.common import Actor, ServiceError, audit, new_id
from geosatya.timeutil import as_utc, iso, seen_time, utcnow

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
    prof.last_observed_at, prof.last_mode, prof.last_source = as_utc(observed), mode, source
    prof.last_received_at = seen_time(utcnow(), observed)  # a position sent late keeps its real age


def record_ping(session, settings, categories, task: TaskRow, incident: IncidentRow, actor: Actor, loc: dict,
                *, router=None, force: bool = False) -> dict:
    if actor.role != "WORKER" or task.worker_id != actor.user_id:
        raise ServiceError("Only the assigned worker can share a location for this task.", 403, "NOT_ASSIGNED_WORKER")
    if task.status not in ACTIVE:
        raise ServiceError(f"Location sharing is only for an active task (this one is {task.status}).", 409, "TASK_NOT_ACTIVE")
    lat, lon, acc, mode = _validated(settings, loc)
    now = utcnow()
    progress = progress_of(session, task)
    pings = recent_pings(session, task.task_id)
    observed = as_utc(loc.get("observed_at"))
    if pings and observed is not None and pings[-1].observed_at is not None:
        last = as_utc(pings[-1].observed_at)
        # Retries and reordered network requests must not move the worker backwards.
        if observed == last:
            return {"stored": False, "reason": "DUPLICATE"}
        if observed < last:
            return {"stored": False, "reason": "OUT_OF_ORDER"}
    if not force and pings and (now - as_utc(pings[-1].received_at)).total_seconds() < settings.tracking_min_interval_s:
        return {"stored": False, "reason": "TOO_FREQUENT", "min_interval_s": settings.tracking_min_interval_s}

    distance = haversine_m(task.target_latitude, task.target_longitude, lat, lon)
    ping = LocationPingRow(ping_id=new_id("PNG", 5), task_id=task.task_id, worker_id=actor.user_id, latitude=lat,
                           longitude=lon, accuracy_m=acc, observed_at=as_utc(loc.get("observed_at")), received_at=now,
                           mode=mode, distance_to_target_m=distance)
    session.add(ping)
    _remember(session, actor.user_id, lat, lon, acc, loc.get("observed_at"), mode, "TRACKING")
    if progress.accepted_at is None:
        progress.accepted_at = now  # starting the journey is accepting the task
        audit(session, actor, "TASK_ACCEPTED", incident.incident_id, task_id=task.task_id, how="STARTED_JOURNEY")
    if not progress.tracking_active:
        progress.tracking_active, progress.tracking_stopped_at, progress.tracking_stop_reason = True, None, None
        progress.tracking_started_at = progress.tracking_started_at or now
        audit(session, actor, "TRACKING_STARTED", incident.incident_id, task_id=task.task_id)
    session.flush()

    arrived_now = False
    # Arrival needs N consecutive good readings (inside the radius, usable
    # accuracy, not an old fix), so a single stray reading can't claim it.
    if progress.arrived_at is None:
        recent = recent_pings(session, task.task_id)[-settings.arrival_confirm_readings:]
        if (len(recent) == settings.arrival_confirm_readings
                and all(_good_arrival_reading(settings, p) for p in recent)):
            progress.arrived_at, arrived_now = now, True
            audit(session, actor, "ARRIVAL_DETECTED", incident.incident_id, distance_m=round(distance, 1),
                  accuracy_m=acc, readings=len(recent), simulated=mode == "SIMULATED",
                  note="Estimated from shared location; not the geofence check")
    session.flush()

    # Keep only the most recent points.
    pings = recent_pings(session, task.task_id)
    for old in pings[:-settings.tracking_history_keep]:
        session.delete(old)
    pings = pings[-settings.tracking_history_keep:]
    if arrived_now or progress.etr_event in (None, "ASSIGNED", "REASSIGNED") and len(pings) == 1:
        # Meaningful events only: first location (travel becomes known) and arrival.
        route = route_for(router, pings[-1], task) if not arrived_now else None
        info = estimates.eta(task, progress, pings, settings, now, route=route)
        estimates.recompute_etr(session, settings, categories, task, incident, progress,
                                "ARRIVED" if arrived_now else "FIRST_LOCATION", info, now)
    session.flush()
    return {"stored": True, "distance_m": round(distance, 1), "arrived": progress.arrived_at is not None}


def route_for(router, ping: LocationPingRow | None, task: TaskRow):
    """Road route from the worker's latest position to the task target, or None (no router / failure)."""
    if router is None or ping is None:
        return None
    return router.route((ping.latitude, ping.longitude), (task.target_latitude, task.target_longitude))


def confirm_arrival(session, settings, categories, task: TaskRow, incident: IncidentRow, actor: Actor, loc: dict | None,
                    *, router=None) -> dict:
    """The worker says "I'm here". It is accepted only if the location sent
    with it is within the arrival radius with usable accuracy; the server
    decides, not the button. This is still not the completion geofence check."""
    if loc is None:
        raise ServiceError("Arrival needs your current location. Allow location access and try again.", 422, "LOCATION_REQUIRED")
    if task.status != "ASSIGNED":
        raise ServiceError(f"Arrival can only be confirmed before work starts (task is {task.status}).", 409, "INVALID_TRANSITION")
    result = record_ping(session, settings, categories, task, incident, actor, loc, router=router, force=True)
    progress = progress_of(session, task)
    if progress.arrived_at is not None:
        return {"arrived": True, "arrived_at": iso(progress.arrived_at), "distance_m": result.get("distance_m")}
    latest = recent_pings(session, task.task_id)[-1]
    if not _good_arrival_reading(settings, latest):
        raise ServiceError(f"You appear to be {latest.distance_to_target_m:.0f} m from the incident (±{latest.accuracy_m or 0:.0f} m). "
                           f"Arrival needs you within {settings.arrival_radius_m:g} m with accuracy of ±50 m or better.",
                           409, "ARRIVAL_NOT_CONFIRMED")
    progress.arrived_at = utcnow()
    audit(session, actor, "ARRIVAL_CONFIRMED", incident.incident_id, distance_m=round(latest.distance_to_target_m, 1),
          accuracy_m=latest.accuracy_m, simulated=latest.mode == "SIMULATED", note="Worker confirmed with a location inside the arrival radius")
    estimates.recompute_etr(session, settings, categories, task, incident, progress, "ARRIVED")
    session.flush()
    return {"arrived": True, "arrived_at": iso(progress.arrived_at), "distance_m": round(latest.distance_to_target_m, 1)}


def add_progress_update(session, settings, task: TaskRow, incident: IncidentRow, actor: Actor, note: str,
                        estimate_minutes: int | None) -> ProgressUpdateRow:
    """A worker's progress note, optionally with their own estimate of the time
    left. The estimate replaces the ETR (labelled as the worker's estimate)."""
    if actor.role != "WORKER" or task.worker_id != actor.user_id:
        raise ServiceError("Only the assigned worker can post progress.", 403, "NOT_ASSIGNED_WORKER")
    if task.status != "IN_PROGRESS":
        raise ServiceError("Progress updates are for work in progress. Start work first.", 409, "TASK_NOT_IN_PROGRESS")
    note = (note or "").strip()
    if len(note) < 3:
        raise ServiceError("Write a short progress note.", 422, "NOTE_REQUIRED")
    now = utcnow()
    row = ProgressUpdateRow(update_id=new_id("UPD", 4), task_id=task.task_id, attempt=task.attempt, worker_id=actor.user_id,
                            note=note[:500], estimate_minutes=estimate_minutes, created_at=now)
    session.add(row)
    if estimate_minutes is not None:
        progress = progress_of(session, task)
        progress.etr_due_at = now + timedelta(minutes=estimate_minutes + settings.etr_review_buffer_min)
        progress.etr_basis = {"approximate": True, "travel_min": 0, "travel_source": None, "work_min": estimate_minutes,
                              "work_source": "WORKER_ESTIMATE", "history_samples": None, "review_min": settings.etr_review_buffer_min,
                              "notes": ["Time left estimated by the worker on site."]}
        progress.etr_event, progress.etr_updated_at = "WORKER_ESTIMATE", now
    audit(session, actor, "PROGRESS_UPDATE", incident.incident_id, estimate_minutes=estimate_minutes)
    session.flush()
    return row


def _good_arrival_reading(settings, p: LocationPingRow) -> bool:
    if p.distance_to_target_m > settings.arrival_radius_m:
        return False
    if p.accuracy_m is not None and p.accuracy_m > max(settings.arrival_radius_m, 50):
        return False
    # A fix the device says it took long before sending is not evidence of being here now.
    if p.observed_at is not None and (as_utc(p.received_at) - as_utc(p.observed_at)).total_seconds() > settings.tracking_stale_s:
        return False
    return True


PHASE_TEXT = {
    "UNASSIGNED": "Finding a field worker", "AWAITING_ACCEPTANCE": "Worker assigned, waiting for them to accept",
    "ACCEPTED": "Worker accepted, not travelling yet", "EN_ROUTE": "Worker on the way", "ARRIVED": "Worker has arrived",
    "IN_PROGRESS": "Work in progress", "AWAITING_REVIEW": "Work submitted, being verified", "RESOLVED": "Resolved",
}


def phase_of(task: TaskRow | None, progress: TaskProgressRow | None) -> str:
    """Conceptual journey state, derived from the existing task status plus
    recorded milestones (no new status enum)."""
    if task is None:
        return "UNASSIGNED"
    if task.status == "RESOLVED":
        return "RESOLVED"
    if task.status == "AWAITING_VERIFICATION":
        return "AWAITING_REVIEW"
    if task.status == "IN_PROGRESS":
        return "IN_PROGRESS"
    p = progress
    if p is not None and p.arrived_at is not None:
        return "ARRIVED"
    if p is not None and p.tracking_started_at is not None:
        return "EN_ROUTE"
    if p is not None and p.accepted_at is not None:
        return "ACCEPTED"
    return "AWAITING_ACCEPTANCE"


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


def worker_card(session, worker_id: str, *, full: bool) -> dict:
    """Who is coming. Citizens get a first name and a real track record only;
    staff get the full name and id."""
    user = session.get(UserRow, worker_id)
    name = user.display_name if user else worker_id
    resolved = session.scalar(select(func.count()).select_from(TaskRow)
                              .where(TaskRow.worker_id == worker_id, TaskRow.status == "RESOLVED")) or 0
    first = name.split("(")[0].strip().split(" ")[0] or "Field worker"
    card = {"first_name": first, "resolved_jobs": resolved, "role": "Field worker"}
    if full:
        card.update(name=name, worker_id=worker_id)
    return card


def tracking_view(session, settings, task: TaskRow, incident: IncidentRow, actor: Actor, *, router=None) -> dict:
    progress = progress_of(session, task)
    pings = recent_pings(session, task.task_id)
    now = utcnow()
    latest = pings[-1] if pings else None
    age = (now - seen_time(latest.received_at, latest.observed_at)).total_seconds() if latest else None
    if task.status not in ACTIVE:
        state = "ENDED"
    elif not progress.tracking_active:
        state = "STOPPED" if progress.tracking_stopped_at else "NOT_STARTED"
    else:
        state = "STALE" if age is None or age > settings.tracking_stale_s else "LIVE"
    show_location = latest is not None and (actor.role != "CITIZEN" or (progress.tracking_active and task.status in ACTIVE))
    phase = phase_of(task, progress)
    # A road route only from a live position, only while travelling, and only to someone allowed to see the position.
    route = (route_for(router, latest, task)
             if show_location and state == "LIVE" and task.status == "ASSIGNED" and progress.arrived_at is None else None)
    data = {
        "task_id": task.task_id, "task_status": task.status, "state": state, "phase": phase,
        "phase_text": PHASE_TEXT[phase], "accepted_at": iso(progress.accepted_at),
        "tracking_started_at": iso(progress.tracking_started_at), "tracking_stopped_at": iso(progress.tracking_stopped_at),
        "stop_reason": progress.tracking_stop_reason, "arrived_at": iso(progress.arrived_at),
        "arrival_note": "Estimated from shared location; the work is still checked against the incident location on completion.",
        "work_started_at": iso(progress.work_started_at), "stale_after_s": settings.tracking_stale_s,
        "target": {"latitude": task.target_latitude, "longitude": task.target_longitude},
        "latest": None, "eta": estimates.eta(task, progress, pings, settings, now, route=route),
        "etr": estimates.etr_view(task, progress, incident, now),
        "route": ({"provider": route.provider, "distance_m": round(route.distance_m), "duration_s": round(route.duration_s),
                   "geometry": route.geometry} if route else None),
        "routing": "ON" if router is not None else "OFF",
        "worker": worker_card(session, task.worker_id, full=actor.role != "CITIZEN"),
        "progress_updates": [{"note": u.note, "estimate_minutes": u.estimate_minutes, "time": iso(u.created_at)}
                             for u in session.scalars(select(ProgressUpdateRow).where(ProgressUpdateRow.task_id == task.task_id)
                                                      .order_by(ProgressUpdateRow.created_at))],
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
