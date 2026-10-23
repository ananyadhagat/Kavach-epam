import json
from collections import Counter

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse, Response
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from geosatya.api.deps import get_actor, get_session, load_incident, load_task, require_role, task_of
from geosatya.api.schemas import CompletionCreate, CorrectionRequest, IncidentCreate, ReviewRequest, SettingsUpdate
from geosatya.api.views import audit_view, completion_view, incident_detail, incident_summary, task_view
from geosatya.config import ACCURACY_MAX_M, ACCURACY_MIN_M, GEOFENCE_MAX_M, GEOFENCE_MIN_M
from geosatya.media.image_checks import ImageValidationError
from geosatya.models import AuditRow, CompletionRow, EvidenceRow, IncidentRow, MediaRow, TaskRow, UserRow
from geosatya.services import incidents as incident_service
from geosatya.services import tasks as task_service
from geosatya.services.common import Actor, ServiceError, audit, get_limits, set_limits
from geosatya.timeutil import iso

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
                    actor: Actor = Depends(require_role("CITIZEN")), session: Session = Depends(get_session)):
    app = _app(request)
    body = parse_payload(IncidentCreate, payload)
    files = []
    for i, upload in enumerate([p for p in photos if p.filename]):
        meta = body.photos_meta[i] if i < len(body.photos_meta) else None
        files.append((read_upload(upload, app.settings.max_image_size_bytes), dump(meta) or {"capture_source": "GALLERY"}))
    data = body.model_dump(mode="python")
    incident = incident_service.create_incident(session, app.storage, app.settings, app.categories, actor, data, files)
    session.commit()
    return incident_detail(session, app.categories, incident, task_of(session, incident.incident_id), actor)


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
def start(task_id: str, actor: Actor = Depends(worker_only), session: Session = Depends(get_session)):
    task = load_task(session, task_id, actor)
    task_service.start_task(session, task, session.get(IncidentRow, task.incident_id), actor)
    session.commit()
    return task_view(session, task)


@router.post("/tasks/{task_id}/completion", tags=["Tasks"])
def completion(task_id: str, request: Request, payload: str = Form(...), photo: UploadFile | None = File(default=None),
               actor: Actor = Depends(worker_only), session: Session = Depends(get_session)):
    app = _app(request)
    task = load_task(session, task_id, actor)
    incident = session.get(IncidentRow, task.incident_id)
    body = parse_payload(CompletionCreate, payload)
    data = read_upload(photo, app.settings.max_image_size_bytes) if photo is not None and photo.filename else None
    row = task_service.submit_completion(
        session, app.storage, app.settings, task, incident, actor, photo=data, meta=dump(body.photo_meta),
        device=dump(body.device_location), device_error=body.device_location_error, description=body.description)
    session.commit()
    return {"completion": completion_view(session, row, detail=False), "task": task_view(session, task),
            "incident_status": incident.status}


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
def review(completion_id: str, body: ReviewRequest, actor: Actor = Depends(supervisor_only),
           session: Session = Depends(get_session)):
    c = session.get(CompletionRow, completion_id)
    if c is None:
        raise HTTPException(404, "Not found")
    task = session.get(TaskRow, c.task_id)
    task_service.review(session, c, task, session.get(IncidentRow, c.incident_id), actor, body.decision, body.reason)
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
def demo_reset(request: Request, _: Actor = Depends(supervisor_only)):
    state = _app(request)
    if state.settings.auth_mode != "demo" or state.settings.app_env == "production":
        raise HTTPException(404, "Not available")
    state.reset_demo()
    return {"reset": True}


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
