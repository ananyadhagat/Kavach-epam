"""Dispatch: choose a field worker for an incident.

The ranking rules are the Dispatch Agent's (geosatya/dispatch/ranking.py).
GeoSatya supplies the inputs from its own records: worker profiles, the
locations workers actually shared, and their open task counts. One task per
incident (tasks.incident_id is unique), so a retried dispatch never creates a
second assignment.
"""

from __future__ import annotations

from sqlalchemy import func, select

from geosatya.dispatch.ranking import LOCATION_STALE, LOCATION_UNAVAILABLE, dispatch_task
from geosatya.models import DispatchRow, IncidentRow, IntelligenceRow, TaskProgressRow, TaskRow, UserRow, WorkerProfileRow
from geosatya.services.common import Actor, ServiceError, audit, move_incident, new_id
from geosatya.services.intelligence import priority_of
from geosatya.timeutil import as_utc, utcnow

OPEN_TASK_STATUSES = ("ASSIGNED", "IN_PROGRESS", "AWAITING_VERIFICATION")
SYSTEM = Actor("dispatch", "SYSTEM", "Dispatch")
LOCATION_ONLY = {LOCATION_STALE, LOCATION_UNAVAILABLE}


def open_task_counts(session) -> dict[str, int]:
    return dict(session.execute(select(TaskRow.worker_id, func.count()).where(TaskRow.status.in_(OPEN_TASK_STATUSES))
                                .group_by(TaskRow.worker_id)).all())


def worker_pool(session) -> list[dict]:
    """Workers in the shape the Dispatch Agent's ranking expects."""
    load = open_task_counts(session)
    pool = []
    for user, prof in session.execute(select(UserRow, WorkerProfileRow)
                                      .join(WorkerProfileRow, WorkerProfileRow.user_id == UserRow.user_id)
                                      .where(UserRow.role == "WORKER").order_by(UserRow.user_id)):
        pool.append({"worker_id": user.user_id, "name": user.display_name, "latitude": prof.last_latitude,
                     "longitude": prof.last_longitude, "skills": list(prof.skills or []),
                     "equipment": list(prof.equipment or []), "available": prof.available,
                     "active_tasks": load.get(user.user_id, 0), "max_active_tasks": prof.max_active_tasks,
                     "location_updated_at": as_utc(prof.last_received_at)})
    return pool


def requirements(categories, incident: IncidentRow) -> dict:
    spec = (categories.get(incident.category) or {}).get("dispatch") or {}
    return {"required_skills": list(spec.get("required_skills") or []),
            "required_equipment": list(spec.get("required_equipment") or [])}


def create_task(session, incident: IncidentRow, worker_id: str, actor: Actor, reason: str) -> TaskRow:
    now = utcnow()
    task = TaskRow(task_id=new_id("TSK", 3), incident_id=incident.incident_id, worker_id=worker_id,
                   target_latitude=incident.latitude, target_longitude=incident.longitude, target_source="ORIGINAL",
                   status="ASSIGNED", attempt=1, assigned_at=now, updated_at=now)
    session.add(task)
    session.flush()
    session.add(TaskProgressRow(task_id=task.task_id, tracking_active=False, etr_basis={}))
    move_incident(session, incident, "ASSIGNED", actor, reason)
    session.flush()
    return task


def dispatch_incident(session, settings, categories, incident: IncidentRow, *, actor: Actor = SYSTEM) -> TaskRow | None:
    existing = session.scalar(select(TaskRow).where(TaskRow.incident_id == incident.incident_id))
    if existing is not None:
        return existing  # idempotent: one assignment per incident
    req = requirements(categories, incident)
    priority = priority_of(session.get(IntelligenceRow, incident.incident_id))
    job = {"latitude": incident.latitude, "longitude": incident.longitude, "max_radius_km": settings.dispatch_max_radius_km,
           **req}
    pool = worker_pool(session)
    result = dispatch_task(job, pool, max_location_age_s=settings.dispatch_location_max_age_s)
    ranking, rejected = result["candidates"], result["rejected_workers"]

    worker_id, method = None, None
    if ranking:
        worker_id, method = ranking[0]["worker_id"], "DISPATCH_RANKING"
        reason = f"Best eligible worker by distance and workload ({ranking[0]['distance_km']} km away)"
    elif settings.dispatch_fallback == "workload":
        # Only workers who fail nothing but the location rule; nearest is not claimed.
        ok = {r["worker_id"] for r in rejected if set(r["reasons"]) <= LOCATION_ONLY}
        qualified = [w for w in pool if w["worker_id"] in ok]
        if qualified:
            best = min(qualified, key=lambda w: (w["active_tasks"] / w["max_active_tasks"], w["active_tasks"], w["worker_id"]))
            worker_id, method = best["worker_id"], "WORKLOAD_FALLBACK"
            reason = "No qualified worker has shared a recent location; assigned by workload (distance not considered)"
    if worker_id is None:
        reason = "No eligible worker: escalated to a supervisor"
    session.add(DispatchRow(dispatch_id=new_id("DSP", 4), incident_id=incident.incident_id,
                            status="ASSIGNED" if worker_id else "UNASSIGNED", method=method or "DISPATCH_RANKING",
                            worker_id=worker_id, priority=priority, required_skills=req["required_skills"],
                            required_equipment=req["required_equipment"], ranking=ranking, rejected=rejected,
                            reason=reason, created_by=actor.user_id, created_at=utcnow()))
    if worker_id is None:
        audit(session, actor, "DISPATCH_ESCALATED", incident.incident_id, priority=priority, rejected=rejected)
        session.flush()
        return None
    audit(session, actor, "DISPATCHED", incident.incident_id, worker_id=worker_id, method=method, priority=priority)
    return create_task(session, incident, worker_id, actor, f"Assigned to {worker_id}: {reason}")


def _check_worker(session, worker_id: str) -> UserRow:
    worker = session.get(UserRow, worker_id)
    if worker is None or worker.role != "WORKER":
        raise ServiceError("Choose a field worker.", 422, "NOT_A_WORKER")
    return worker


def assign_manually(session, settings, categories, incident: IncidentRow, worker_id: str, actor: Actor, reason: str) -> TaskRow:
    """Supervisor assignment of an escalated (unassigned) incident."""
    if session.scalar(select(TaskRow).where(TaskRow.incident_id == incident.incident_id)) is not None:
        raise ServiceError("This incident already has a field task. Use reassign instead.", 409, "ALREADY_ASSIGNED")
    _check_worker(session, worker_id)
    reason = (reason or "").strip() or "Assigned by supervisor"
    session.add(DispatchRow(dispatch_id=new_id("DSP", 4), incident_id=incident.incident_id, status="ASSIGNED",
                            method="SUPERVISOR_MANUAL", worker_id=worker_id,
                            priority=priority_of(session.get(IntelligenceRow, incident.incident_id)),
                            ranking=[], rejected=[], reason=reason[:300], created_by=actor.user_id, created_at=utcnow(),
                            **requirements(categories, incident)))
    audit(session, actor, "DISPATCHED", incident.incident_id, worker_id=worker_id, method="SUPERVISOR_MANUAL", reason=reason[:300])
    return create_task(session, incident, worker_id, actor, f"Assigned to {worker_id} by supervisor")


def reassign(session, settings, categories, incident: IncidentRow, task: TaskRow, worker_id: str, actor: Actor,
             reason: str) -> TaskRow:
    """Move an active task to another worker. Tracking of the old worker stops
    and their shared locations for this task are deleted."""
    from geosatya.services.tracking import stop_tracking  # local import: tracking imports dispatch helpers

    reason = (reason or "").strip()
    if len(reason) < 5:
        raise ServiceError("A reason is required to reassign (at least 5 characters).", 422, "REASON_REQUIRED")
    if task.status not in ("ASSIGNED", "IN_PROGRESS"):
        raise ServiceError(f"A task that is {task.status} cannot be reassigned.", 409, "TASK_LOCKED")
    _check_worker(session, worker_id)
    if worker_id == task.worker_id:
        raise ServiceError("The task is already assigned to this worker.", 409, "SAME_WORKER")
    previous = task.worker_id
    stop_tracking(session, task, "REASSIGNED", purge=True)
    progress = session.get(TaskProgressRow, task.task_id)
    if progress is not None:
        progress.arrived_at, progress.work_started_at, progress.tracking_started_at = None, None, None
    now = utcnow()
    task.worker_id, task.status, task.assigned_at, task.updated_at = worker_id, "ASSIGNED", now, now
    if incident.status == "IN_PROGRESS":
        move_incident(session, incident, "ASSIGNED", actor, f"Reassigned from {previous} to {worker_id}: {reason}")
    session.add(DispatchRow(dispatch_id=new_id("DSP", 4), incident_id=incident.incident_id, status="ASSIGNED",
                            method="REASSIGNED", worker_id=worker_id,
                            priority=priority_of(session.get(IntelligenceRow, incident.incident_id)),
                            ranking=[], rejected=[], reason=reason[:300], created_by=actor.user_id, created_at=now,
                            **requirements(categories, incident)))
    audit(session, actor, "REASSIGNED", incident.incident_id, from_worker=previous, to_worker=worker_id, reason=reason[:300])
    session.flush()
    return task
