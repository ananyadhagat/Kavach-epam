"""Dispatch: choose a field worker for an incident.

The ranking rules are the Dispatch Agent's (geosatya/dispatch/ranking.py).
GeoSatya supplies the inputs from its own records: worker profiles, the
locations workers actually shared, and their open task counts. One task per
incident (tasks.incident_id is unique), so a retried dispatch never creates a
second assignment.
"""

from __future__ import annotations

import threading

from sqlalchemy import func, select

from geosatya.dispatch.ranking import LOCATION_STALE, LOCATION_UNAVAILABLE, dispatch_task
from geosatya.models import DispatchRow, IncidentRow, IntelligenceRow, TaskProgressRow, TaskRow, UserRow, WorkerProfileRow
from geosatya.services.common import Actor, ServiceError, audit, move_incident, new_id
from geosatya.services.intelligence import priority_of
from geosatya.timeutil import as_utc, utcnow

OPEN_TASK_STATUSES = ("ASSIGNED", "IN_PROGRESS", "AWAITING_VERIFICATION")
# Serialises assignment decisions in this process, so two incidents dispatched
# at the same moment can't both take a worker's last free slot. Routes hold it
# across the decision *and* the commit. Several server processes would need a
# database lock instead (e.g. SELECT ... FOR UPDATE on PostgreSQL).
DISPATCH_LOCK = threading.RLock()
SYSTEM = Actor("dispatch", "SYSTEM", "Dispatch")
LOCATION_ONLY = {LOCATION_STALE, LOCATION_UNAVAILABLE}


def open_task_counts(session) -> dict[str, int]:
    return dict(session.execute(select(TaskRow.worker_id, func.count()).where(TaskRow.status.in_(OPEN_TASK_STATUSES))
                                .group_by(TaskRow.worker_id)).all())


def worker_pool(session, settings=None) -> list[dict]:
    """Workers in the shape the Dispatch Agent's ranking expects. A location
    less accurate than DISPATCH_MAX_LOCATION_ACCURACY_M is withheld from the
    ranking (it can't support a distance comparison) and labelled as such."""
    load = open_task_counts(session)
    pool = []
    max_acc = settings.dispatch_max_location_accuracy_m if settings is not None else None
    for user, prof in session.execute(select(UserRow, WorkerProfileRow)
                                      .join(WorkerProfileRow, WorkerProfileRow.user_id == UserRow.user_id)
                                      .where(UserRow.role == "WORKER").order_by(UserRow.user_id)):
        inaccurate = max_acc is not None and prof.last_accuracy_m is not None and prof.last_accuracy_m > max_acc
        pool.append({"worker_id": user.user_id, "name": user.display_name,
                     "latitude": None if inaccurate else prof.last_latitude,
                     "longitude": None if inaccurate else prof.last_longitude, "skills": list(prof.skills or []),
                     "equipment": list(prof.equipment or []), "available": prof.available,
                     "active_tasks": load.get(user.user_id, 0), "max_active_tasks": prof.max_active_tasks,
                     "location_updated_at": None if inaccurate else as_utc(prof.last_received_at),
                     "location_note": f"Location too inaccurate (±{prof.last_accuracy_m:.0f} m)" if inaccurate else None})
    return pool


def _route_rank(router, settings, incident: IncidentRow, ranking: list[dict], pool: list[dict]) -> dict | None:
    """Among the top-ranked eligible workers, prefer the lowest road travel
    time. Annotates the ranking entries; None if no route could be computed."""
    if router is None or not ranking:
        return None
    where = {w["worker_id"]: (w["latitude"], w["longitude"]) for w in pool}
    routed = []
    for cand in ranking[:settings.dispatch_route_candidates]:
        r = router.route(where[cand["worker_id"]], (incident.latitude, incident.longitude))
        if r is not None:
            cand["route_eta_min"], cand["road_distance_km"] = round(r.duration_s / 60, 1), round(r.distance_m / 1000, 2)
            cand["route_provider"] = r.provider
            routed.append(cand)
    if not routed:
        return None
    return min(routed, key=lambda c: (c["route_eta_min"], c["score"], c["worker_id"]))


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


def released_workers(session, incident_id: str) -> set[str]:
    """Workers who declined, timed out on, or were cancelled from this incident: not offered it again automatically."""
    return set(session.scalars(select(DispatchRow.worker_id).where(
        DispatchRow.incident_id == incident_id, DispatchRow.status == "RELEASED", DispatchRow.worker_id.is_not(None))))


def dispatch_incident(session, settings, categories, incident: IncidentRow, *, actor: Actor = SYSTEM,
                      router=None) -> TaskRow | None:
    """Callers that commit afterwards should hold DISPATCH_LOCK across the call and the commit."""
    existing = session.scalar(select(TaskRow).where(TaskRow.incident_id == incident.incident_id))
    if existing is not None:
        return existing  # idempotent: one assignment per incident
    req = requirements(categories, incident)
    priority = priority_of(session.get(IntelligenceRow, incident.incident_id))
    job = {"latitude": incident.latitude, "longitude": incident.longitude, "max_radius_km": settings.dispatch_max_radius_km,
           **req}
    excluded = released_workers(session, incident.incident_id)
    pool = [w for w in worker_pool(session, settings) if w["worker_id"] not in excluded]
    result = dispatch_task(job, pool, max_location_age_s=settings.dispatch_location_max_age_s)
    ranking, rejected = result["candidates"], result["rejected_workers"]
    notes = {w["worker_id"]: w["location_note"] for w in pool if w.get("location_note")}

    worker_id, method = None, None
    best_route = _route_rank(router, settings, incident, ranking, pool)
    if best_route is not None:
        worker_id, method = best_route["worker_id"], "ROUTE_ETA"
        reason = (f"Lowest road travel time among the top {min(len(ranking), settings.dispatch_route_candidates)} eligible workers "
                  f"(≈ {best_route['route_eta_min']} min, {best_route['road_distance_km']} km by road, {best_route['route_provider']})")
    elif ranking:
        worker_id, method = ranking[0]["worker_id"], "DISPATCH_RANKING"
        reason = f"Best eligible worker by distance and workload ({ranking[0]['distance_km']} km away, straight line)"
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
        if excluded:
            reason += f" ({len(excluded)} worker(s) already released this job)"
    for r in rejected:  # say why a location was withheld, instead of just "unavailable"
        if r["worker_id"] in notes:
            r["reasons"] = [notes[r["worker_id"]] if x == LOCATION_UNAVAILABLE else x for x in r["reasons"]]
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


def _check_worker(session, worker_id: str, *, override: bool = False, reason: str = "") -> UserRow:
    """A supervisor may not give work to an unavailable or full worker by
    accident; doing it deliberately needs override=true and a reason."""
    worker = session.get(UserRow, worker_id)
    if worker is None or worker.role != "WORKER":
        raise ServiceError("Choose a field worker.", 422, "NOT_A_WORKER")
    prof = session.get(WorkerProfileRow, worker_id)
    busy = []
    if prof is not None and not prof.available:
        busy.append("unavailable")
    if prof is not None and open_task_counts(session).get(worker_id, 0) >= prof.max_active_tasks:
        busy.append("at capacity")
    if busy and not override:
        raise ServiceError(f"{worker.display_name} is {' and '.join(busy)}. Choose another worker, or override with a reason.",
                           409, "WORKER_UNAVAILABLE")
    if busy and len((reason or "").strip()) < 5:
        raise ServiceError("Overriding availability needs a reason (at least 5 characters).", 422, "REASON_REQUIRED")
    return worker


def assign_manually(session, settings, categories, incident: IncidentRow, worker_id: str, actor: Actor, reason: str,
                    *, override: bool = False) -> TaskRow:
    """Supervisor assignment of an escalated (unassigned) incident."""
    if session.scalar(select(TaskRow).where(TaskRow.incident_id == incident.incident_id)) is not None:
        raise ServiceError("This incident already has a field task. Use reassign instead.", 409, "ALREADY_ASSIGNED")
    _check_worker(session, worker_id, override=override, reason=reason)
    reason = (reason or "").strip() or "Assigned by supervisor"
    if override:
        audit(session, actor, "ASSIGNMENT_OVERRIDE", incident.incident_id, worker_id=worker_id, reason=reason[:300])
    session.add(DispatchRow(dispatch_id=new_id("DSP", 4), incident_id=incident.incident_id, status="ASSIGNED",
                            method="SUPERVISOR_MANUAL", worker_id=worker_id,
                            priority=priority_of(session.get(IntelligenceRow, incident.incident_id)),
                            ranking=[], rejected=[], reason=reason[:300], created_by=actor.user_id, created_at=utcnow(),
                            **requirements(categories, incident)))
    audit(session, actor, "DISPATCHED", incident.incident_id, worker_id=worker_id, method="SUPERVISOR_MANUAL", reason=reason[:300])
    return create_task(session, incident, worker_id, actor, f"Assigned to {worker_id} by supervisor")


def accept(session, task: TaskRow, incident: IncidentRow, actor: Actor, *, how: str = "ACCEPTED") -> None:
    """The assigned worker accepts. Starting the journey or the work also counts
    as accepting, so the existing start-work flow keeps working without this step."""
    from geosatya.services.tracking import progress_of

    if actor.role != "WORKER" or task.worker_id != actor.user_id:
        raise ServiceError("Only the assigned worker can accept this task.", 403, "NOT_ASSIGNED_WORKER")
    if task.status not in ("ASSIGNED", "IN_PROGRESS"):
        raise ServiceError(f"A task that is {task.status} cannot be accepted.", 409, "INVALID_TRANSITION")
    progress = progress_of(session, task)
    if progress.accepted_at is None:
        progress.accepted_at = utcnow()
        audit(session, actor, "TASK_ACCEPTED", incident.incident_id, task_id=task.task_id, how=how)
        session.flush()


def is_accepted(progress: TaskProgressRow | None) -> bool:
    """Accepted explicitly, or implicitly by starting the journey or the work
    (also covers tasks from before the accepted_at column existed)."""
    return progress is not None and any(t is not None for t in (progress.accepted_at, progress.tracking_started_at,
                                                                progress.work_started_at))


def acceptance_overdue(settings, task: TaskRow, progress: TaskProgressRow | None, now=None) -> bool:
    if task.status != "ASSIGNED" or is_accepted(progress):
        return False
    return ((now or utcnow()) - as_utc(task.assigned_at)).total_seconds() > settings.acceptance_timeout_min * 60


RELEASE_KINDS = {"DECLINED": "declined by the worker", "ACCEPTANCE_TIMEOUT": "not accepted in time",
                 "CANCELLED": "assignment cancelled by a supervisor"}


def release(session, settings, categories, incident: IncidentRow, task: TaskRow, actor: Actor, kind: str,
            reason: str, *, router=None) -> TaskRow | None:
    """Take the job away from the current worker and run Dispatch again without
    them (or anyone who released it before). If nobody else qualifies, the
    incident goes back to SUBMITTED with an UNASSIGNED dispatch record.

    Only before any completion attempt: once evidence exists the task row holds
    it, and a supervisor uses reassign instead. The assignment history stays in
    dispatch_records and the audit trail."""
    from geosatya.models import CompletionRow, LocationPingRow, ProgressUpdateRow
    from geosatya.services.tracking import progress_of, stop_tracking

    reason = (reason or "").strip()
    if kind not in RELEASE_KINDS:
        raise ServiceError("Unknown release kind.", 422, "INVALID_KIND")
    if kind == "DECLINED":
        if actor.role != "WORKER" or task.worker_id != actor.user_id:
            raise ServiceError("Only the assigned worker can decline.", 403, "NOT_ASSIGNED_WORKER")
        progress = progress_of(session, task)
        if task.status != "ASSIGNED" or is_accepted(progress):
            raise ServiceError("A task can only be declined before it is accepted.", 409, "ALREADY_ACCEPTED")
    else:
        if actor.role != "SUPERVISOR":
            raise ServiceError("Only a supervisor can do this.", 403, "SUPERVISOR_ONLY")
        if len(reason) < 5:
            raise ServiceError("A reason is required (at least 5 characters).", 422, "REASON_REQUIRED")
        if task.status not in ("ASSIGNED", "IN_PROGRESS"):
            raise ServiceError(f"A task that is {task.status} cannot be released.", 409, "TASK_LOCKED")
        if kind == "ACCEPTANCE_TIMEOUT" and not acceptance_overdue(settings, task, session.get(TaskProgressRow, task.task_id)):
            raise ServiceError("This assignment is not overdue for acceptance.", 409, "NOT_OVERDUE")
    if session.scalar(select(func.count()).select_from(CompletionRow).where(CompletionRow.task_id == task.task_id)):
        raise ServiceError("Completion evidence already exists for this task; reassign it instead.", 409, "HAS_EVIDENCE")

    previous = task.worker_id
    stop_tracking(session, task, kind, purge=True)
    session.execute(LocationPingRow.__table__.delete().where(LocationPingRow.task_id == task.task_id))
    session.execute(ProgressUpdateRow.__table__.delete().where(ProgressUpdateRow.task_id == task.task_id))
    progress = session.get(TaskProgressRow, task.task_id)
    if progress is not None:
        session.delete(progress)
    session.flush()
    session.delete(task)
    session.flush()
    move_incident(session, incident, "SUBMITTED", actor, f"Assignment {RELEASE_KINDS[kind]}: {reason or 'no reason given'}")
    session.add(DispatchRow(dispatch_id=new_id("DSP", 4), incident_id=incident.incident_id, status="RELEASED",
                            method=kind, worker_id=previous,
                            priority=priority_of(session.get(IntelligenceRow, incident.incident_id)), ranking=[], rejected=[],
                            reason=(reason or RELEASE_KINDS[kind])[:300], created_by=actor.user_id, created_at=utcnow(),
                            **requirements(categories, incident)))
    audit(session, actor, "ASSIGNMENT_RELEASED", incident.incident_id, kind=kind, worker_id=previous, reason=reason[:300])
    session.flush()
    return dispatch_incident(session, settings, categories, incident, router=router)


def reassign(session, settings, categories, incident: IncidentRow, task: TaskRow, worker_id: str, actor: Actor,
             reason: str, *, override: bool = False) -> TaskRow:
    """Move an active task to another worker. Tracking of the old worker stops
    and their shared locations for this task are deleted."""
    from geosatya.services.tracking import stop_tracking  # local import: tracking imports dispatch helpers

    reason = (reason or "").strip()
    if len(reason) < 5:
        raise ServiceError("A reason is required to reassign (at least 5 characters).", 422, "REASON_REQUIRED")
    if task.status not in ("ASSIGNED", "IN_PROGRESS"):
        raise ServiceError(f"A task that is {task.status} cannot be reassigned.", 409, "TASK_LOCKED")
    if worker_id == task.worker_id:
        raise ServiceError("The task is already assigned to this worker.", 409, "SAME_WORKER")
    _check_worker(session, worker_id, override=override, reason=reason)
    if override:
        audit(session, actor, "ASSIGNMENT_OVERRIDE", incident.incident_id, worker_id=worker_id, reason=reason[:300])
    previous = task.worker_id
    stop_tracking(session, task, "REASSIGNED", purge=True)
    progress = session.get(TaskProgressRow, task.task_id)
    if progress is not None:
        progress.arrived_at, progress.work_started_at, progress.tracking_started_at = None, None, None
        progress.accepted_at = None  # the new worker has to accept
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
