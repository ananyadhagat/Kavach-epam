import json
from pathlib import Path
from collections import Counter

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse, Response
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from geosatya.api.deps import get_actor, get_session, load_incident, load_task, require_role, task_of
from geosatya.api.schemas import (
    ArrivalRequest, AssignRequest, CheckInRequest, CompletionCreate, CorrectionRequest, DeclineRequest, DeviceLocation,
    IncidentCreate, ProgressUpdateRequest, ReleaseRequest, ReviewRequest, SettingsUpdate,
)
from geosatya.api.views import audit_view, completion_view, incident_detail, incident_summary, intelligence_view, task_view
from geosatya.config import ACCURACY_MAX_M, ACCURACY_MIN_M, GEOFENCE_MAX_M, GEOFENCE_MIN_M
from geosatya.media.image_checks import ImageValidationError
from geosatya.models import (
    AuditRow, CompletionRow, EvidenceRow, IncidentRow, MediaRow, RequestKeyRow, TaskRow, UserRow, WorkerProfileRow,
)
from geosatya.services import board as board_service
from geosatya.services import dispatch as dispatch_service
from geosatya.services import incidents as incident_service
from geosatya.services import tasks as task_service
from geosatya.services import tracking as tracking_service
from geosatya.services.common import Actor, ServiceError, audit, get_limits, set_limits
from geosatya.services.intelligence import run_intelligence
from geosatya.timeutil import iso, utcnow

router = APIRouter()
supervisor_only = require_role("SUPERVISOR")
worker_only = require_role("WORKER")


def _app(request: Request):
    return request.app.state


def parse_payload(model, text: str):
    """Multipart requests carry their JSON in a form field."""
    try:
        return model.model_validate(json.loads(text or "{}"))
    except (json.JSONDecodeError, ValidationError) as exc:
        details = [f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()] \
            if isinstance(exc, ValidationError) else ["not valid JSON"]
        raise ServiceError("Invalid request: " + "; ".join(details), 422, "INVALID_REQUEST") from exc


def read_upload(upload: UploadFile, limit: int) -> bytes:
    data = upload.file.read(limit + 1)
    if len(data) > limit:
        raise ServiceError(f"The photo is larger than {limit // (1024 * 1024)} MB.", 413, "FILE_TOO_LARGE")
    return data


def dump(model):
    return model.model_dump(mode="python") if model is not None else None


# ---------------------------------------------------------------- app
@router.get("/config", tags=["App"])
def app_config(request: Request, session: Session = Depends(get_session)):
    s = _app(request).settings
    key = s.google_maps_browser_key
    return {
        "app_name": s.app_name, "environment": s.app_env, "auth_mode": s.auth_mode,
        "maps": {"provider": "google" if key else "leaflet", "google_browser_key": key, "google_map_id": s.google_maps_map_id},
        "limits": get_limits(session, s),
        "limit_ranges": {"geofence_radius_m": [GEOFENCE_MIN_M, GEOFENCE_MAX_M], "max_accuracy_m": [ACCURACY_MIN_M, ACCURACY_MAX_M]},
        "location_freshness_s": s.location_freshness_s, "simulation_allowed": s.simulation_allowed,
        "simulated_may_pass": s.simulated_may_pass, "max_image_size_bytes": s.max_image_size_bytes,
        "min_completion_chars": s.min_completion_chars,
        "integration": {"intelligence_configured": _app(request).intelligence is not None,
                        "dispatch_fallback": s.dispatch_fallback, "dispatch_max_radius_km": s.dispatch_max_radius_km,
                        "dispatch_location_max_age_s": s.dispatch_location_max_age_s},
        "tracking": {"min_interval_s": s.tracking_min_interval_s, "stale_s": s.tracking_stale_s,
                     "arrival_radius_m": s.arrival_radius_m, "arrival_confirm_readings": s.arrival_confirm_readings,
                     "acceptance_timeout_min": s.acceptance_timeout_min,
                     "eta_method": "ROAD_ROUTE" if _app(request).router is not None else "APPROXIMATE_STRAIGHT_LINE",
                     "routing_provider": s.routing_provider if _app(request).router is not None else None},
    }


@router.get("/categories", tags=["App"])
def categories(request: Request):
    return {"categories": _app(request).categories.items}


@router.get("/demo/users", tags=["Demo"])
def demo_users(request: Request, session: Session = Depends(get_session)):
    if _app(request).settings.auth_mode != "demo":
        raise HTTPException(404, "Demo identities are only available in demo mode.")
    users = session.scalars(select(UserRow).where(UserRow.is_demo.is_(True)).order_by(UserRow.role, UserRow.user_id)).all()
    return [{"user_id": u.user_id, "display_name": u.display_name, "role": u.role} for u in users]


@router.get("/me", tags=["App"])
def me(actor: Actor = Depends(get_actor)):
    return {"user_id": actor.user_id, "role": actor.role, "display_name": actor.display_name}


@router.get("/dashboard", tags=["App"])
def dashboard(request: Request, actor: Actor = Depends(get_actor), session: Session = Depends(get_session)):
    q = select(IncidentRow).order_by(IncidentRow.updated_at.desc())
    if actor.role == "CITIZEN":
        q = q.where(IncidentRow.reporter_id == actor.user_id)
    elif actor.role == "WORKER":
        q = q.where(IncidentRow.incident_id.in_(select(TaskRow.incident_id).where(TaskRow.worker_id == actor.user_id)))
    rows = session.scalars(q).all()
    counts = Counter(i.status for i in rows)
    cats = _app(request).categories
    return {"total": len(rows), "open": counts["ASSIGNED"] + counts["IN_PROGRESS"] + counts["SUBMITTED"],
            "awaiting": counts["AWAITING_VERIFICATION"], "resolved": counts["RESOLVED"],
            "recent": [incident_summary(session, cats, i, task_of(session, i.incident_id)) for i in rows[:5]]}


@router.get("/settings", tags=["Settings"])
def read_settings(request: Request, _: Actor = Depends(get_actor), session: Session = Depends(get_session)):
    return get_limits(session, _app(request).settings)


@router.put("/settings", tags=["Settings"])
def update_settings(body: SettingsUpdate, request: Request, actor: Actor = Depends(supervisor_only),
                    session: Session = Depends(get_session)):
    limits = set_limits(session, _app(request).settings, actor, body.geofence_radius_m, body.max_accuracy_m)
    session.commit()
    return limits


# ---------------------------------------------------------- incidents
@router.post("/incidents", tags=["Incidents"], status_code=201)
def create_incident(request: Request, payload: str = Form(...), photos: list[UploadFile] = File(default=[]),
                    idempotency_key: str | None = Header(default=None, max_length=80),
                    actor: Actor = Depends(require_role("CITIZEN")), session: Session = Depends(get_session)):
    app = _app(request)
    if not app.report_limiter.allow(actor.user_id):
        raise ServiceError("Too many reports in a minute. Please wait a moment and try again.", 429, "RATE_LIMITED")
    if idempotency_key:
        # A retried submission (e.g. after a dropped connection) returns the first report.
        seen = session.get(RequestKeyRow, f"{actor.user_id}:{idempotency_key}")
        if seen is not None:
            incident = session.get(IncidentRow, seen.incident_id)
            return JSONResponse(incident_detail(session, app.categories, incident, task_of(session, incident.incident_id), actor),
                                status_code=200)
    body = parse_payload(IncidentCreate, payload)
    files = []
    for i, upload in enumerate([p for p in photos if p.filename]):
        meta = body.photos_meta[i] if i < len(body.photos_meta) else None
        files.append((read_upload(upload, app.settings.max_image_size_bytes), dump(meta) or {"capture_source": "GALLERY"}))
    data = body.model_dump(mode="python")
    incident = incident_service.create_incident(session, app.storage, app.settings, app.categories, actor, data, files)
    if idempotency_key:
        session.add(RequestKeyRow(key=f"{actor.user_id}:{idempotency_key}", user_id=actor.user_id,
                                  incident_id=incident.incident_id, created_at=utcnow()))
    session.commit()  # the report is safe before any other agent is called
    run_intelligence(session, app.storage, app.intelligence, incident)  # outside the lock: it can be slow
    session.commit()
    with dispatch_service.DISPATCH_LOCK:
        task = dispatch_service.dispatch_incident(session, app.settings, app.categories, incident, router=app.router)
        if task is not None:
            incident_service.refresh_etr(session, app.settings, app.categories, task, incident, "ASSIGNED")
        session.commit()
    return incident_detail(session, app.categories, incident, task_of(session, incident.incident_id), actor)


@router.post("/incidents/{incident_id}/intelligence/retry", tags=["Integration"])
def retry_intelligence(incident_id: str, request: Request, actor: Actor = Depends(supervisor_only),
                       session: Session = Depends(get_session)):
    app = _app(request)
    incident = load_incident(session, incident_id, actor)
    row = run_intelligence(session, app.storage, app.intelligence, incident)
    session.commit()
    return intelligence_view(row, full=True)


@router.post("/incidents/{incident_id}/dispatch/retry", tags=["Integration"])
def retry_dispatch(incident_id: str, request: Request, actor: Actor = Depends(supervisor_only),
                   session: Session = Depends(get_session)):
    """Run Dispatch again for an escalated incident. Never creates a second task."""
    app = _app(request)
    incident = load_incident(session, incident_id, actor)
    with dispatch_service.DISPATCH_LOCK:
        task = dispatch_service.dispatch_incident(session, app.settings, app.categories, incident, actor=actor, router=app.router)
        if task is not None:
            incident_service.refresh_etr(session, app.settings, app.categories, task, incident, "ASSIGNED")
        session.commit()
    return incident_detail(session, app.categories, incident, task, actor)


@router.post("/incidents/{incident_id}/assign", tags=["Integration"])
def assign(incident_id: str, body: AssignRequest, request: Request, actor: Actor = Depends(supervisor_only),
           session: Session = Depends(get_session)):
    app = _app(request)
    incident = load_incident(session, incident_id, actor)
    with dispatch_service.DISPATCH_LOCK:
        task = dispatch_service.assign_manually(session, app.settings, app.categories, incident, body.worker_id, actor,
                                                body.reason, override=body.override)
        incident_service.refresh_etr(session, app.settings, app.categories, task, incident, "ASSIGNED")
        session.commit()
    return incident_detail(session, app.categories, incident, task, actor)


@router.get("/incidents/{incident_id}/tracking", tags=["Tracking"])
def incident_tracking(incident_id: str, request: Request, actor: Actor = Depends(get_actor),
                      session: Session = Depends(get_session)):
    incident = load_incident(session, incident_id, actor)
    task = task_of(session, incident_id)
    if task is None:
        raise ServiceError("No field task yet.", 404, "NO_TASK")
    data = tracking_service.tracking_view(session, _app(request).settings, task, incident, actor, router=_app(request).router)
    session.commit()
    return data


@router.get("/incidents", tags=["Incidents"])
def list_incidents(request: Request, actor: Actor = Depends(get_actor), session: Session = Depends(get_session)):
    q = select(IncidentRow).order_by(IncidentRow.created_at.desc())
    if actor.role == "CITIZEN":
        q = q.where(IncidentRow.reporter_id == actor.user_id)
    elif actor.role == "WORKER":
        q = q.where(IncidentRow.incident_id.in_(select(TaskRow.incident_id).where(TaskRow.worker_id == actor.user_id)))
    cats = _app(request).categories
    return [incident_summary(session, cats, i, task_of(session, i.incident_id)) for i in session.scalars(q)]


@router.get("/incidents/{incident_id}", tags=["Incidents"])
def get_incident(incident_id: str, request: Request, actor: Actor = Depends(get_actor), session: Session = Depends(get_session)):
    incident = load_incident(session, incident_id, actor)
    return incident_detail(session, _app(request).categories, incident, task_of(session, incident_id), actor)


@router.post("/incidents/{incident_id}/correct-location", tags=["Incidents"])
def correct_location(incident_id: str, body: CorrectionRequest, request: Request,
                     actor: Actor = Depends(supervisor_only), session: Session = Depends(get_session)):
    incident = load_incident(session, incident_id, actor)
    task = task_of(session, incident_id)
    if task is None:
        raise ServiceError("There is no task to correct.", 409, "NO_TASK")
    incident_service.correct_task_location(session, incident, task, actor, body.latitude, body.longitude, body.reason)
    session.commit()
    return incident_detail(session, _app(request).categories, incident, task, actor)


# -------------------------------------------------------------- tasks
@router.get("/tasks", tags=["Tasks"])
def list_tasks(request: Request, actor: Actor = Depends(require_role("WORKER", "SUPERVISOR")),
               session: Session = Depends(get_session)):
    q = select(TaskRow).order_by(TaskRow.updated_at.desc())
    if actor.role == "WORKER":
        q = q.where(TaskRow.worker_id == actor.user_id)
    cats, out = _app(request).categories, []
    for t in session.scalars(q):
        out.append({**task_view(session, t), "incident": incident_summary(session, cats, session.get(IncidentRow, t.incident_id), t)})
    return out


@router.get("/tasks/{task_id}", tags=["Tasks"])
def get_task(task_id: str, request: Request, actor: Actor = Depends(require_role("WORKER", "SUPERVISOR")),
             session: Session = Depends(get_session)):
    task = load_task(session, task_id, actor)
    incident = session.get(IncidentRow, task.incident_id)
    detail = incident_detail(session, _app(request).categories, incident, task, actor)
    limits = get_limits(session, _app(request).settings)
    return {**task_view(session, task), "incident": detail, "limits": limits}


@router.post("/tasks/{task_id}/start", tags=["Tasks"])
def start(task_id: str, request: Request, actor: Actor = Depends(worker_only), session: Session = Depends(get_session)):
    app = _app(request)
    task = load_task(session, task_id, actor)
    task_service.start_task(session, task, session.get(IncidentRow, task.incident_id), actor,
                            settings=app.settings, categories=app.categories)
    session.commit()
    return task_view(session, task)


@router.post("/tasks/{task_id}/accept", tags=["Tasks"])
def accept_task(task_id: str, actor: Actor = Depends(worker_only), session: Session = Depends(get_session)):
    task = load_task(session, task_id, actor)
    dispatch_service.accept(session, task, session.get(IncidentRow, task.incident_id), actor)
    session.commit()
    return {**task_view(session, task), "accepted": True}


@router.post("/tasks/{task_id}/decline", tags=["Tasks"])
def decline_task(task_id: str, body: DeclineRequest, request: Request, actor: Actor = Depends(worker_only),
                 session: Session = Depends(get_session)):
    """The assigned worker declines before accepting; Dispatch runs again without them."""
    app = _app(request)
    task = load_task(session, task_id, actor)
    incident = session.get(IncidentRow, task.incident_id)
    with dispatch_service.DISPATCH_LOCK:
        new_task = dispatch_service.release(session, app.settings, app.categories, incident, task, actor, "DECLINED", body.reason,
                                            router=app.router)
        if new_task is not None:
            incident_service.refresh_etr(session, app.settings, app.categories, new_task, incident, "ASSIGNED")
        session.commit()
    return {"declined": True, "incident_id": incident.incident_id}


@router.post("/tasks/{task_id}/release", tags=["Integration"])
def release_task(task_id: str, body: ReleaseRequest, request: Request, actor: Actor = Depends(supervisor_only),
                 session: Session = Depends(get_session)):
    """Supervisor: cancel the assignment, or re-dispatch one not accepted in time."""
    app = _app(request)
    task = load_task(session, task_id, actor)
    incident = session.get(IncidentRow, task.incident_id)
    with dispatch_service.DISPATCH_LOCK:
        new_task = dispatch_service.release(session, app.settings, app.categories, incident, task, actor, body.kind, body.reason,
                                            router=app.router)
        if new_task is not None:
            incident_service.refresh_etr(session, app.settings, app.categories, new_task, incident, "ASSIGNED")
        session.commit()
    return incident_detail(session, app.categories, incident, new_task, actor)


@router.get("/dispatch/board", tags=["Integration"])
def dispatch_board(request: Request, _: Actor = Depends(supervisor_only), session: Session = Depends(get_session)):
    app = _app(request)
    return board_service.board(session, app.settings, app.categories)


@router.post("/tasks/{task_id}/location", tags=["Tracking"])
def share_location(task_id: str, body: DeviceLocation, request: Request, actor: Actor = Depends(worker_only),
                   session: Session = Depends(get_session)):
    """The assigned worker shares their position while travelling or working."""
    app = _app(request)
    task = load_task(session, task_id, actor)
    result = tracking_service.record_ping(session, app.settings, app.categories, task,
                                          session.get(IncidentRow, task.incident_id), actor, dump(body), router=app.router)
    session.commit()
    return result


@router.post("/tasks/{task_id}/arrive", tags=["Tracking"])
def confirm_arrival(task_id: str, body: ArrivalRequest, request: Request, actor: Actor = Depends(worker_only),
                    session: Session = Depends(get_session)):
    """The worker confirms arrival; accepted only if the location sent with it is inside the arrival radius."""
    app = _app(request)
    task = load_task(session, task_id, actor)
    result = tracking_service.confirm_arrival(session, app.settings, app.categories, task, session.get(IncidentRow, task.incident_id),
                                              actor, dump(body.location), router=app.router)
    session.commit()
    return result


@router.post("/tasks/{task_id}/progress", tags=["Tasks"])
def progress_update(task_id: str, body: ProgressUpdateRequest, request: Request, actor: Actor = Depends(worker_only),
                    session: Session = Depends(get_session), idempotency_key: str | None = Header(default=None, max_length=80)):
    task = load_task(session, task_id, actor)
    if _replayed(session, actor, "progress", idempotency_key) is None:
        row = tracking_service.add_progress_update(session, _app(request).settings, task, session.get(IncidentRow, task.incident_id),
                                                   actor, body.note, body.estimate_minutes)
        _remember_key(session, actor, "progress", idempotency_key, task.incident_id, row.update_id)
    session.commit()
    return {"saved": True, "progress": incident_detail(session, _app(request).categories, session.get(IncidentRow, task.incident_id),
                                                       task, actor)["progress"]}


@router.get("/dashboard/live", tags=["Integration"])
def live_dashboard(request: Request, _: Actor = Depends(supervisor_only), session: Session = Depends(get_session)):
    """Supervisor live map: KPIs, open incidents and workers (positions only while recent)."""
    app = _app(request)
    return board_service.live_overview(session, app.settings, app.categories)


@router.post("/tasks/{task_id}/tracking/stop", tags=["Tracking"])
def stop_sharing(task_id: str, actor: Actor = Depends(worker_only), session: Session = Depends(get_session)):
    task = load_task(session, task_id, actor)
    tracking_service.stop_tracking(session, task, "STOPPED_BY_WORKER")
    audit(session, actor, "TRACKING_STOPPED", task.incident_id, task_id=task.task_id)
    session.commit()
    return {"stopped": True}


@router.get("/tasks/{task_id}/tracking", tags=["Tracking"])
def task_tracking(task_id: str, request: Request, actor: Actor = Depends(require_role("WORKER", "SUPERVISOR")),
                  session: Session = Depends(get_session)):
    task = load_task(session, task_id, actor)
    data = tracking_service.tracking_view(session, _app(request).settings, task, session.get(IncidentRow, task.incident_id), actor,
                                          router=_app(request).router)
    session.commit()
    return data


@router.post("/tasks/{task_id}/reassign", tags=["Integration"])
def reassign(task_id: str, body: AssignRequest, request: Request, actor: Actor = Depends(supervisor_only),
             session: Session = Depends(get_session)):
    app = _app(request)
    task = load_task(session, task_id, actor)
    incident = session.get(IncidentRow, task.incident_id)
    with dispatch_service.DISPATCH_LOCK:
        dispatch_service.reassign(session, app.settings, app.categories, incident, task, body.worker_id, actor, body.reason,
                                  override=body.override)
        incident_service.refresh_etr(session, app.settings, app.categories, task, incident, "REASSIGNED")
        session.commit()
    return incident_detail(session, app.categories, incident, task, actor)


# ------------------------------------------------------------ workers
@router.get("/workers", tags=["Workers"])
def workers(request: Request, _: Actor = Depends(supervisor_only), session: Session = Depends(get_session)):
    """Dispatch view of the workforce: skills, load, and how old their shared location is."""
    settings, now = _app(request).settings, utcnow()
    out = []
    for w in dispatch_service.worker_pool(session):
        updated = w.pop("location_updated_at")
        age = int((now - updated).total_seconds()) if updated else None
        out.append({**w, "location_age_s": age, "location_fresh": age is not None and age <= settings.dispatch_location_max_age_s})
    return out


@router.get("/workers/me", tags=["Workers"])
def my_status(request: Request, actor: Actor = Depends(worker_only), session: Session = Depends(get_session)):
    prof = session.get(WorkerProfileRow, actor.user_id)
    if prof is None:
        raise ServiceError("No worker profile exists for this user.", 404, "NO_PROFILE")
    return {"available": prof.available, "skills": prof.skills, "max_active_tasks": prof.max_active_tasks,
            "location_shared_at": iso(prof.last_received_at), "location_source": prof.last_source,
            "location_mode": prof.last_mode, "dispatch_location_max_age_s": _app(request).settings.dispatch_location_max_age_s}


@router.post("/workers/me/check-in", tags=["Workers"])
def worker_check_in(body: CheckInRequest, request: Request, actor: Actor = Depends(worker_only),
                    session: Session = Depends(get_session)):
    tracking_service.check_in(session, _app(request).settings, actor, body.available, dump(body.location))
    session.commit()
    return my_status(request, actor, session)


@router.post("/tasks/{task_id}/completion", tags=["Tasks"])
def completion(task_id: str, request: Request, payload: str = Form(...), photo: UploadFile | None = File(default=None),
               idempotency_key: str | None = Header(default=None, max_length=80),
               actor: Actor = Depends(worker_only), session: Session = Depends(get_session)):
    app = _app(request)
    task = load_task(session, task_id, actor)
    incident = session.get(IncidentRow, task.incident_id)
    seen = _replayed(session, actor, "completion", idempotency_key)
    if seen is not None:
        # The worker app re-sent a submission whose response it never received: return the first result.
        row = session.get(CompletionRow, seen.ref_id)
        return {"completion": completion_view(session, row, detail=False), "task": task_view(session, task),
                "incident_status": incident.status, "replayed": True}
    body = parse_payload(CompletionCreate, payload)
    data = read_upload(photo, app.settings.max_image_size_bytes) if photo is not None and photo.filename else None
    row = task_service.submit_completion(
        session, app.storage, app.settings, task, incident, actor, photo=data, meta=dump(body.photo_meta),
        device=dump(body.device_location), device_error=body.device_location_error, description=body.description,
        categories=app.categories)
    _remember_key(session, actor, "completion", idempotency_key, incident.incident_id, row.completion_id)
    session.commit()
    return {"completion": completion_view(session, row, detail=False), "task": task_view(session, task),
            "incident_status": incident.status}


def _replayed(session, actor: Actor, kind: str, key: str | None) -> RequestKeyRow | None:
    return session.get(RequestKeyRow, f"{actor.user_id}:{kind}:{key}") if key else None


def _remember_key(session, actor: Actor, kind: str, key: str | None, incident_id: str, ref_id: str) -> None:
    if key:
        session.add(RequestKeyRow(key=f"{actor.user_id}:{kind}:{key}", user_id=actor.user_id, incident_id=incident_id,
                                  created_at=utcnow(), kind=kind, ref_id=ref_id))


# ------------------------------------------------------- supervisor
@router.get("/verification-queue", tags=["Supervisor"])
def verification_queue(request: Request, _: Actor = Depends(supervisor_only), session: Session = Depends(get_session)):
    cats, out = _app(request).categories, []
    for c in session.scalars(select(CompletionRow).where(CompletionRow.accepted.is_(True)).order_by(CompletionRow.submitted_at.desc())):
        task = session.get(TaskRow, c.task_id)
        inc = session.get(IncidentRow, c.incident_id)
        pending = c.reviewed_at is None and c.attempt == task.attempt and task.status == "AWAITING_VERIFICATION"
        out.append({**completion_view(session, c, detail=False), "pending": pending, "title": inc.title,
                    "category_label": cats.label(inc.category), "is_demo": inc.is_demo})
    out.sort(key=lambda r: not r["pending"])
    return out


@router.get("/completions/{completion_id}", tags=["Supervisor"])
def get_completion(completion_id: str, request: Request, actor: Actor = Depends(supervisor_only),
                   session: Session = Depends(get_session)):
    c = session.get(CompletionRow, completion_id)
    if c is None:
        raise HTTPException(404, "Not found")
    task = session.get(TaskRow, c.task_id)
    incident = session.get(IncidentRow, c.incident_id)
    pending = c.reviewed_at is None and c.accepted and c.attempt == task.attempt and task.status == "AWAITING_VERIFICATION"
    return {**completion_view(session, c, detail=True), "pending": pending,
            "incident": incident_detail(session, _app(request).categories, incident, task, actor),
            "target": {"latitude": task.target_latitude, "longitude": task.target_longitude, "source": task.target_source}}


@router.post("/completions/{completion_id}/review", tags=["Supervisor"])
def review(completion_id: str, body: ReviewRequest, request: Request, actor: Actor = Depends(supervisor_only),
           session: Session = Depends(get_session)):
    app = _app(request)
    c = session.get(CompletionRow, completion_id)
    if c is None:
        raise HTTPException(404, "Not found")
    task = session.get(TaskRow, c.task_id)
    task_service.review(session, c, task, session.get(IncidentRow, c.incident_id), actor, body.decision, body.reason,
                        settings=app.settings, categories=app.categories)
    session.commit()
    return completion_view(session, c, detail=False)


@router.get("/evidence-history", tags=["Supervisor"])
def evidence_history(incident_id: str | None = None, _: Actor = Depends(supervisor_only),
                     session: Session = Depends(get_session)):
    q = select(AuditRow).order_by(AuditRow.event_time.desc()).limit(300)
    if incident_id:
        q = q.where(AuditRow.incident_id == incident_id.strip().upper())
    events = [audit_view(session, e) for e in session.scalars(q)]
    sources = Counter(e.source_type for e in session.scalars(select(EvidenceRow)))
    return {"events": events, "evidence_counts": dict(sources)}


# ----------------------------------------------------------- media
@router.get("/media/{media_id}", tags=["Evidence"])
def get_media(media_id: str, request: Request, actor: Actor = Depends(get_actor), session: Session = Depends(get_session)):
    media = session.get(MediaRow, media_id)
    if media is None:
        raise HTTPException(404, "Photo not found")
    load_incident(session, media.incident_id, actor)  # 404 unless allowed
    try:
        data = _app(request).storage.read(media.storage_key)
    except Exception:
        raise HTTPException(410, "Photo file is no longer available") from None
    return Response(data, media_type=media.mime_type,
                    headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"})


@router.post("/demo/reset", tags=["Demo"])
def demo_reset(request: Request, actor: Actor = Depends(supervisor_only)):
    state = _app(request)
    if state.settings.auth_mode != "demo" or state.settings.app_env == "production":
        raise HTTPException(404, "Not available")
    client = request.headers.get("cf-connecting-ip") or (request.client.host if request.client else "unknown")
    backup = state.reset_demo(by=f"{actor.user_id}@{client}")
    return {"reset": True, "backup": Path(backup).name if backup else None}


def register_error_handlers(app) -> None:
    from fastapi.exceptions import RequestValidationError

    @app.exception_handler(ServiceError)
    async def _service(_, exc: ServiceError):
        return JSONResponse({"detail": str(exc), "code": exc.code}, status_code=exc.status_code)

    @app.exception_handler(ImageValidationError)
    async def _image(_, exc: ImageValidationError):
        return JSONResponse({"detail": str(exc), "code": exc.code}, status_code=exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def _validation(_, exc: RequestValidationError):
        # Never echo the submitted input: it may be NaN/Infinity, which is not valid JSON.
        errors = [f"{'.'.join(str(p) for p in e['loc'] if p != 'body')}: {e['msg']}" for e in exc.errors()]
        return JSONResponse({"detail": "Invalid request: " + "; ".join(errors), "code": "INVALID_REQUEST"}, status_code=422)
