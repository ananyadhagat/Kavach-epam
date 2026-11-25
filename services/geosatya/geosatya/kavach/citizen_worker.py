"""Citizen feedback after resolution, and the worker "Available jobs" list with claiming.

Feedback: only the person who reported a complaint can rate it, and only once it is resolved.
Available jobs: open complaints in the worker's own workspace that nobody has taken. A worker sees
only jobs they have the skills for and that are within the dispatch radius of the location they
really shared; claiming applies the same rules as dispatch (availability, capacity, workspace).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from geosatya.api.deps import get_actor, get_session, load_incident
from geosatya.location.coordinates import haversine_m
from geosatya.models import IncidentRow, TaskRow, UserRow, WorkerProfileRow
from geosatya.platform_models import FeedbackRow
from geosatya.services import dispatch as dispatch_service
from geosatya.services import incidents as incident_service
from geosatya.services.common import Actor, ServiceError
from geosatya.timeutil import as_utc, iso, utcnow

router = APIRouter(prefix="/kavach", tags=["KAVACH"])


# ------------------------------------------------------------- feedback
class FeedbackIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    rating: int = Field(ge=1, le=5)
    comment: str | None = Field(default=None, max_length=500)


def _feedback_view(row: FeedbackRow | None) -> dict | None:
    return None if row is None else {"rating": row.rating, "comment": row.comment, "created_at": iso(row.created_at)}


@router.get("/incidents/{incident_id}/feedback")
def get_feedback(incident_id: str, actor: Actor = Depends(get_actor), session: Session = Depends(get_session)):
    if actor.role not in ("CITIZEN", "SUPERVISOR"):
        raise ServiceError("Incident not found", 404, "NOT_FOUND")
    inc = load_incident(session, incident_id, actor)
    row = session.get(FeedbackRow, inc.incident_id)
    return {"feedback": _feedback_view(row),
            "can_give": actor.role == "CITIZEN" and inc.reporter_id == actor.user_id and inc.status == "RESOLVED"}


@router.post("/incidents/{incident_id}/feedback", status_code=201)
def give_feedback(incident_id: str, body: FeedbackIn, actor: Actor = Depends(get_actor), session: Session = Depends(get_session)):
    if actor.role != "CITIZEN":
        raise ServiceError("Only the person who reported it can leave feedback.", 403, "FORBIDDEN")
    inc = load_incident(session, incident_id, actor)
    if inc.reporter_id != actor.user_id:
        raise ServiceError("Incident not found", 404, "NOT_FOUND")
    if inc.status != "RESOLVED":
        raise ServiceError("You can leave feedback once the complaint is resolved.", 409, "NOT_RESOLVED")
    row = session.get(FeedbackRow, inc.incident_id)
    if row is None:
        row = FeedbackRow(incident_id=inc.incident_id, user_id=actor.user_id, rating=body.rating, created_at=utcnow())
        session.add(row)
    row.rating, row.comment, row.created_at = body.rating, body.comment or None, utcnow()
    session.commit()
    return {"feedback": _feedback_view(row), "can_give": True}


# ------------------------------------------------------ available jobs
def _worker_context(session, request: Request, actor: Actor):
    if actor.role != "WORKER":
        raise ServiceError("Only field workers see available jobs.", 403, "FORBIDDEN")
    settings = request.app.state.settings
    prof = session.get(WorkerProfileRow, actor.user_id)
    if prof is None:
        raise ServiceError("No worker profile exists for this user.", 404, "NO_PROFILE")
    fresh = (prof.last_latitude is not None and prof.last_received_at is not None
             and (utcnow() - as_utc(prof.last_received_at)).total_seconds() <= settings.dispatch_location_max_age_s)
    return settings, prof, fresh


def _unassigned(session, actor: Actor) -> list[IncidentRow]:
    """Open complaints with no task, in the worker's own workspace only."""
    workspace = session.get(UserRow, actor.user_id).workspace_id or None
    q = select(IncidentRow).where(IncidentRow.status == "SUBMITTED", ~IncidentRow.incident_id.in_(select(TaskRow.incident_id)))
    return [i for i in session.scalars(q.order_by(IncidentRow.created_at)) if (i.workspace_id or None) == workspace]


def _fits(settings, categories, prof: WorkerProfileRow, inc: IncidentRow) -> tuple[bool, float | None]:
    need = set(dispatch_service.requirements(categories, inc).get("required_skills") or [])
    if not need.issubset(set(prof.skills or [])):
        return False, None
    distance = haversine_m(prof.last_latitude, prof.last_longitude, inc.latitude, inc.longitude)
    return distance <= settings.dispatch_max_radius_km * 1000, distance


@router.get("/jobs/available")
def available_jobs(request: Request, actor: Actor = Depends(get_actor), session: Session = Depends(get_session)):
    settings, prof, fresh = _worker_context(session, request, actor)
    categories = request.app.state.categories
    note = None
    if not prof.available:
        note = "You are marked unavailable. Mark yourself available to take jobs."
    elif not fresh:
        note = "Share your location to see jobs near you. Your last location is missing or too old."
    elif dispatch_service.open_task_counts(session).get(actor.user_id, 0) >= prof.max_active_tasks:
        note = "You are at your limit of open tasks."
    jobs = []
    if note is None:
        for inc in _unassigned(session, actor):
            ok, distance = _fits(settings, categories, prof, inc)
            if ok:
                cat = categories.get(inc.category) or {}
                jobs.append({"incident_id": inc.incident_id, "title": inc.title, "category": inc.category,
                             "category_label": cat.get("label", inc.category), "icon": cat.get("icon", "dots"),
                             "distance_m": round(distance), "reported_at": iso(inc.created_at),
                             "work_minutes": (cat.get("dispatch") or {}).get("work_minutes")})
        jobs.sort(key=lambda j: j["distance_m"])
    return {"jobs": jobs, "note": note, "radius_km": settings.dispatch_max_radius_km}


@router.post("/jobs/{incident_id}/claim")
def claim_job(incident_id: str, request: Request, actor: Actor = Depends(get_actor), session: Session = Depends(get_session)):
    settings, prof, fresh = _worker_context(session, request, actor)
    app = request.app.state
    if not prof.available or not fresh:
        raise ServiceError("Share your current location and mark yourself available to take jobs.", 409, "NOT_READY")
    inc = session.get(IncidentRow, incident_id)
    if inc is None or inc.incident_id not in {i.incident_id for i in _unassigned(session, actor)}:
        raise ServiceError("This job is no longer available.", 409, "JOB_TAKEN")
    ok, _ = _fits(settings, app.categories, prof, inc)
    if not ok:
        raise ServiceError("This job needs different skills or is outside your area.", 409, "NOT_ELIGIBLE")
    with dispatch_service.DISPATCH_LOCK:
        task = dispatch_service.assign_manually(session, settings, app.categories, inc, actor.user_id, actor, "Claimed by the worker")
        dispatch_service.accept(session, task, inc, actor)
        incident_service.refresh_etr(session, settings, app.categories, task, inc, "ASSIGNED")
        session.commit()
    return {"claimed": True, "task_id": task.task_id, "incident_id": inc.incident_id}
