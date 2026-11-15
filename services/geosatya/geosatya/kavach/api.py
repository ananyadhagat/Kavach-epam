"""KAVACH platform API (/api/v1/kavach). GeoSatya's own API is unchanged and
keeps serving the incident, task, tracking and review screens; these routes
add registration, workspaces, public reporting and platform administration."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, Header, Request, UploadFile
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from geosatya.api.deps import get_actor, get_session, optional_actor, task_of
from geosatya.api.schemas import DeviceError, DeviceLocation, PhotoMeta, UserLocation
from geosatya.api.views import incident_detail, incident_summary
from geosatya.kavach import catalog
from geosatya.kavach.agents import OWNERS, agents_view, run_team_agents, run_verification
from geosatya.kavach import service as svc
from geosatya.location.coordinates import haversine_m
from geosatya.models import IncidentRow, RequestKeyRow, UserRow
from geosatya.platform_models import AuthorityRow, DepartmentRow, InviteRow, WorkspaceRow, ZoneRow
from geosatya.ratelimit import SlidingWindowLimiter
from geosatya.services import dispatch as dispatch_service
from geosatya.services import incidents as incident_service
from geosatya.services.common import Actor, ServiceError, audit, new_id
from geosatya.services.intelligence import run_intelligence
from geosatya.timeutil import iso, utcnow

router = APIRouter(prefix="/kavach", tags=["KAVACH"])
_public_limiter = SlidingWindowLimiter(60)

Strict = ConfigDict(extra="forbid", str_strip_whitespace=True)


def _app(request: Request):
    return request.app.state


def _client(request: Request) -> str:
    return request.headers.get("cf-connecting-ip") or (request.client.host if request.client else "unknown")


def _require(actor: Actor, *platform_roles: str) -> None:
    if actor.platform_role not in platform_roles:
        raise ServiceError("You don't have access to this.", 403, "FORBIDDEN")


def _demo_only(request: Request) -> None:
    s = _app(request).settings
    if s.auth_mode != "demo" or s.app_env == "production":
        raise ServiceError("Self-registration without sign-in is only available in development.", 404, "NOT_AVAILABLE")


# ------------------------------------------------------------ schemas
class Area(BaseModel):
    model_config = Strict
    center_latitude: float | None = Field(default=None, ge=-90, le=90, allow_inf_nan=False)
    center_longitude: float | None = Field(default=None, ge=-180, le=180, allow_inf_nan=False)
    radius_m: float | None = Field(default=None, ge=50, le=100_000, allow_inf_nan=False)


class OrgRegistration(Area):
    name: str = Field(min_length=3, max_length=120)
    legal_name: str | None = Field(default=None, max_length=160)
    category: str
    description: str = Field(default="", max_length=1000)
    admin_name: str = Field(min_length=2, max_length=80)
    contact_email: str | None = Field(default=None, max_length=160)
    phone: str | None = Field(default=None, max_length=20)
    address: str | None = Field(default=None, max_length=200)
    verification_details: str | None = Field(default=None, max_length=300)


class OrganizerRegistration(BaseModel):
    model_config = Strict
    name: str = Field(min_length=2, max_length=80)
    company: str = Field(min_length=2, max_length=120)
    contact_email: str | None = Field(default=None, max_length=160)
    phone: str | None = Field(default=None, max_length=20)


class EventCreate(Area):
    name: str = Field(min_length=3, max_length=120)
    category: str
    description: str = Field(default="", max_length=1000)
    venue: str | None = Field(default=None, max_length=200)
    company: str | None = Field(default=None, max_length=120)
    contact_email: str | None = Field(default=None, max_length=160)
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    categories: list[str] | None = None


class WorkspaceUpdate(Area):
    name: str | None = Field(default=None, min_length=3, max_length=120)
    description: str | None = Field(default=None, max_length=1000)
    venue: str | None = Field(default=None, max_length=200)
    organization_name: str | None = Field(default=None, max_length=160)
    contact_email: str | None = Field(default=None, max_length=160)
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    settings: dict | None = None


class DepartmentCreate(BaseModel):
    model_config = Strict
    name: str = Field(min_length=2, max_length=120)
    description: str = Field(default="", max_length=500)
    categories: list[str] = Field(default_factory=list)
    supervisor_id: str | None = None


class ZoneCreate(BaseModel):
    model_config = Strict
    name: str = Field(min_length=2, max_length=120)
    kind: str = Field(default="AREA", max_length=30)
    latitude: float = Field(ge=-90, le=90, allow_inf_nan=False)
    longitude: float = Field(ge=-180, le=180, allow_inf_nan=False)
    radius_m: float = Field(default=100, ge=10, le=20_000, allow_inf_nan=False)


class MemberCreate(BaseModel):
    model_config = Strict
    name: str = Field(min_length=2, max_length=80)
    role: Literal["WORKER", "SUPERVISOR"] = "WORKER"
    skills: list[str] = Field(default_factory=list, max_length=20)
    department_id: str | None = None
    phone: str | None = Field(default=None, max_length=20)
    job_role: str | None = Field(default=None, max_length=60)


class MemberUpdate(BaseModel):
    model_config = Strict
    active: bool | None = None
    available: bool | None = None
    skills: list[str] | None = Field(default=None, max_length=20)
    department_id: str | None = None


class InviteCreate(BaseModel):
    model_config = Strict
    role: Literal["WORKER", "SUPERVISOR"] = "WORKER"
    skills: list[str] = Field(default_factory=list, max_length=20)
    department_id: str | None = None
    label: str | None = Field(default=None, max_length=120)


class InviteRedeem(BaseModel):
    model_config = Strict
    code: str = Field(min_length=6, max_length=16)
    name: str = Field(min_length=2, max_length=80)
    phone: str | None = Field(default=None, max_length=20)


class ReportCreate(BaseModel):
    """A report without photographs: category, words and location."""
    model_config = Strict
    category: str = Field(min_length=1, max_length=50)
    title: str = Field(min_length=3, max_length=120)
    description: str = Field(min_length=10, max_length=2000)
    landmark: str | None = Field(default=None, max_length=200)
    road_type: Literal["LOCAL", "STATE_HIGHWAY", "NATIONAL_HIGHWAY", "UNKNOWN"] | None = None
    zone_id: str | None = None
    device_location: DeviceLocation | None = None
    device_location_error: DeviceError | None = None
    user_location: UserLocation | None = None


class VerificationDecision(BaseModel):
    model_config = Strict
    status: Literal["VERIFIED", "REJECTED", "PENDING", "UNVERIFIED"]
    note: str = Field(default="", max_length=300)


class AuthorityCreate(BaseModel):
    model_config = Strict
    name: str = Field(min_length=3, max_length=160)
    kind: Literal["MUNICIPAL", "STATE_HIGHWAY", "NATIONAL_HIGHWAY", "UTILITY", "OTHER"]
    center_latitude: float = Field(ge=-90, le=90, allow_inf_nan=False)
    center_longitude: float = Field(ge=-180, le=180, allow_inf_nan=False)
    radius_km: float = Field(gt=0, le=2000, allow_inf_nan=False)
    categories: list[str] = Field(default_factory=list)
    road_types: list[str] = Field(default_factory=list)
    workspace_id: str | None = None
    contact: str | None = Field(default=None, max_length=200)
    data_note: str | None = Field(default=None, max_length=200)


# ------------------------------------------------------------- public
@router.get("/catalog")
def kavach_catalog(request: Request):
    cats = _app(request).categories.items
    skills = sorted({s for c in cats for s in (c.get("dispatch") or {}).get("required_skills", [])})
    return {
        "categories": [{"id": c["id"], "label": c["label"], "icon": c.get("icon"), "scope": c.get("scope", "civic"),
                        "title_placeholder": c.get("title_placeholder"), "description_placeholder": c.get("description_placeholder"),
                        "target_hours": catalog.DEFAULT_TARGET_HOURS.get(c["id"])} for c in cats],
        "skills": skills, "org_categories": [{"id": k, "label": v} for k, v in catalog.ORG_CATEGORIES],
        "event_categories": [{"id": k, "label": v} for k, v in catalog.EVENT_CATEGORIES],
        "road_types": [{"id": k, "label": v} for k, v in catalog.ROAD_TYPES],
        "priority_levels": catalog.PRIORITY_LEVELS, "worker_roles": catalog.DEFAULT_WORKER_ROLES,
        "target_note": "Kavach default resolution targets. Each workspace can change them; they are not official SLAs.",
    }


@router.get("/public/stats")
def public_stats(request: Request, session: Session = Depends(get_session)):
    if not _public_limiter.allow(f"stats:{_client(request)}"):
        raise ServiceError("Too many requests. Try again in a minute.", 429, "RATE_LIMITED")
    return svc.public_stats(session, _app(request).categories)


@router.get("/public/track/{reference}")
def public_track(reference: str, request: Request, session: Session = Depends(get_session)):
    if not _public_limiter.allow(f"track:{_client(request)}"):
        raise ServiceError("Too many lookups. Try again in a minute.", 429, "RATE_LIMITED")
    return svc.public_track(session, _app(request).categories, reference[:40])


@router.get("/authorities/suggest")
def suggest(latitude: float, longitude: float, category: str, request: Request, road_type: str | None = None,
            session: Session = Depends(get_session)):
    if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
        raise ServiceError("Invalid coordinates.", 422, "INVALID_COORDINATES")
    if _app(request).categories.get(category) is None:
        raise ServiceError("Unknown category.", 422, "UNKNOWN_CATEGORY")
    return svc.suggest_authority(session, latitude, longitude, category, road_type)


def _submit(request: Request, session: Session, actor: Actor, body: ReportCreate, *, workspace_id: str | None, channel: str,
            idempotency_key: str | None, extra_flags: list[str] | None = None, authority: dict | None = None):
    """Store the report, then run Incident Intelligence and Dispatch exactly as
    GeoSatya's own report endpoint does."""
    app = _app(request)
    if not app.report_limiter.allow(actor.user_id):
        raise ServiceError("Too many reports in a minute. Please wait a moment and try again.", 429, "RATE_LIMITED")
    key = f"{actor.user_id}:kavach:{idempotency_key}" if idempotency_key else None
    if key and (seen := session.get(RequestKeyRow, key)) is not None:
        inc = session.get(IncidentRow, seen.incident_id)
        return inc
    data = body.model_dump(mode="python")
    incident = incident_service.create_incident(session, app.storage, app.settings, app.categories, actor, data, [],
                                                require_photo=False, workspace_id=workspace_id, channel=channel)
    if extra_flags:
        incident.location_flags = list(dict.fromkeys([*incident.location_flags, *extra_flags]))
    if authority is not None:
        a = authority.get("authority")
        incident.authority_id = a["authority_id"] if a else None
        incident.authority_reason = authority["reason"][:300]
        incident.forwarding_status = "ROUTED_IN_KAVACH" if a and a["on_kavach"] else "NOT_FORWARDED"
        audit(session, actor, "AUTHORITY_SUGGESTED", incident.incident_id, authority_id=incident.authority_id,
              routed_to_workspace=workspace_id, reason=incident.authority_reason)
    if key:
        session.add(RequestKeyRow(key=key, user_id=actor.user_id, incident_id=incident.incident_id, created_at=utcnow(),
                                  kind="kavach_report", ref_id=incident.incident_id))
    session.commit()  # the report is safe before any other agent is called
    run_intelligence(session, app.storage, app.intelligence, incident)
    session.commit()
    with dispatch_service.DISPATCH_LOCK:
        task = dispatch_service.dispatch_incident(session, app.settings, app.categories, incident, router=app.router)
        if task is not None:
            incident_service.refresh_etr(session, app.settings, app.categories, task, incident, "ASSIGNED")
        session.commit()
    run_team_agents(session, app.agents, incident)  # advisory; never blocks the report
    session.commit()
    return incident


@router.post("/public/reports", status_code=201)
def public_report(body: ReportCreate, request: Request, actor: Actor = Depends(get_actor), session: Session = Depends(get_session),
                  idempotency_key: str | None = Header(default=None, max_length=80)):
    """Citizen report through the public portal. No photographs are collected.
    The suggested authority is stored; if it runs a Kavach workspace the report
    is routed there, otherwise it stays with the open civic team."""
    if actor.role != "CITIZEN":
        raise ServiceError("Public reports are submitted as a citizen.", 403, "FORBIDDEN")
    app = _app(request)
    if app.categories.get(body.category) is None or (app.categories.get(body.category) or {}).get("scope") == "event":
        raise ServiceError("Choose a civic issue category.", 422, "UNKNOWN_CATEGORY")
    loc = body.device_location or body.user_location
    if loc is None:
        raise ServiceError("The report needs a location: allow device location, or choose the spot on the map.", 422,
                           "LOCATION_REQUIRED")
    suggestion = svc.suggest_authority(session, loc.latitude, loc.longitude, body.category, body.road_type)
    a = suggestion["authority"]
    routed = a["workspace_id"] if a and a["on_kavach"] else None
    incident = _submit(request, session, actor, body, workspace_id=routed, channel="PUBLIC_PORTAL",
                       idempotency_key=idempotency_key, authority=suggestion)
    detail = incident_detail(session, app.categories, incident, task_of(session, incident.incident_id), actor)
    return {**detail, "authority": suggestion}


# ------------------------------------------------------- registration
@router.post("/register/organization", status_code=201)
def register_org(body: OrgRegistration, request: Request, session: Session = Depends(get_session)):
    _demo_only(request)
    if not _public_limiter.allow(f"register:{_client(request)}"):
        raise ServiceError("Too many registrations. Try again in a minute.", 429, "RATE_LIMITED")
    ws, admin = svc.register_organization(session, body.model_dump())
    session.commit()
    return {"workspace": svc.workspace_view(session, ws), "user_id": admin.user_id, "display_name": admin.display_name}


@router.post("/register/event-organizer", status_code=201)
def register_organizer(body: OrganizerRegistration, request: Request, session: Session = Depends(get_session)):
    _demo_only(request)
    if not _public_limiter.allow(f"register:{_client(request)}"):
        raise ServiceError("Too many registrations. Try again in a minute.", 429, "RATE_LIMITED")
    user = svc.register_event_organizer(session, body.model_dump())
    session.commit()
    return {"user_id": user.user_id, "display_name": user.display_name, "company": body.company}


@router.post("/join", status_code=201)
def join(body: InviteRedeem, request: Request, session: Session = Depends(get_session)):
    _demo_only(request)
    if not _public_limiter.allow(f"join:{_client(request)}"):
        raise ServiceError("Too many attempts. Try again in a minute.", 429, "RATE_LIMITED")
    user = svc.redeem_invite(session, body.code, body.name, body.phone)
    ws = session.get(WorkspaceRow, user.workspace_id)
    session.commit()
    return {"user_id": user.user_id, "display_name": user.display_name, "role": user.role,
            "workspace": {"workspace_id": ws.workspace_id, "name": ws.name, "kind": ws.kind}}


# ------------------------------------------------------------ context
@router.get("/me")
def my_context(actor: Actor = Depends(get_actor), session: Session = Depends(get_session)):
    ws = session.get(WorkspaceRow, actor.workspace_id) if actor.workspace_id else None
    events = []
    if actor.platform_role == "EVENT_ORGANIZER":
        events = [svc.workspace_view(session, e) for e in session.scalars(
            select(WorkspaceRow).where(WorkspaceRow.owner_id == actor.user_id, WorkspaceRow.kind == "EVENT",
                                       WorkspaceRow.status == "ACTIVE").order_by(WorkspaceRow.starts_at))]
    user = session.get(UserRow, actor.user_id)
    dep = session.get(DepartmentRow, user.department_id) if user.department_id else None
    return {"user_id": actor.user_id, "display_name": actor.display_name, "role": actor.role,
            "platform_role": actor.platform_role, "can_manage": bool(ws and svc.can_manage(actor, ws)),
            "workspace": svc.workspace_view(session, ws, detail=True) if ws else None,
            "department": dep.name if dep else None, "events": events}


# --------------------------------------------------------- workspaces
@router.get("/workspaces/{workspace_id}")
def workspace(workspace_id: str, actor: Actor = Depends(get_actor), session: Session = Depends(get_session)):
    ws = svc.viewable(session, actor, workspace_id)
    return {**svc.workspace_view(session, ws, detail=True), "can_manage": svc.can_manage(actor, ws)}


@router.put("/workspaces/{workspace_id}")
def update_workspace(workspace_id: str, body: WorkspaceUpdate, request: Request, actor: Actor = Depends(get_actor),
                     session: Session = Depends(get_session)):
    ws = svc.managed(session, actor, workspace_id)
    svc.update_workspace(session, actor, ws, body.model_dump(exclude_unset=True), _app(request).categories)
    session.commit()
    return svc.workspace_view(session, ws, detail=True)


@router.post("/workspaces/{workspace_id}/departments", status_code=201)
def add_department(workspace_id: str, body: DepartmentCreate, actor: Actor = Depends(get_actor),
                   session: Session = Depends(get_session)):
    ws = svc.managed(session, actor, workspace_id)
    row = svc.add_department(session, actor, ws, body.model_dump())
    session.commit()
    return svc.department_view(session, row)


@router.delete("/workspaces/{workspace_id}/departments/{department_id}")
def delete_department(workspace_id: str, department_id: str, actor: Actor = Depends(get_actor),
                      session: Session = Depends(get_session)):
    ws = svc.managed(session, actor, workspace_id)
    row = session.get(DepartmentRow, department_id)
    if row is None or row.workspace_id != ws.workspace_id:
        raise ServiceError("Department not found.", 404, "NOT_FOUND")
    for u in session.scalars(select(UserRow).where(UserRow.department_id == department_id)):
        u.department_id = None  # members stay in the workspace, just without a department
    session.delete(row)
    audit(session, actor, "DEPARTMENT_DELETED", None, workspace_id=ws.workspace_id, name=row.name)
    session.commit()
    return {"deleted": True}


@router.post("/workspaces/{workspace_id}/zones", status_code=201)
def add_zone(workspace_id: str, body: ZoneCreate, actor: Actor = Depends(get_actor), session: Session = Depends(get_session)):
    ws = svc.managed(session, actor, workspace_id)
    row = svc.add_zone(session, actor, ws, body.model_dump())
    session.commit()
    return svc.zone_view(row)


@router.delete("/workspaces/{workspace_id}/zones/{zone_id}")
def delete_zone(workspace_id: str, zone_id: str, actor: Actor = Depends(get_actor), session: Session = Depends(get_session)):
    ws = svc.managed(session, actor, workspace_id)
    row = session.get(ZoneRow, zone_id)
    if row is None or row.workspace_id != ws.workspace_id:
        raise ServiceError("Zone not found.", 404, "NOT_FOUND")
    session.delete(row)
    audit(session, actor, "ZONE_DELETED", None, workspace_id=ws.workspace_id, name=row.name)
    session.commit()
    return {"deleted": True}


@router.get("/workspaces/{workspace_id}/members")
def members(workspace_id: str, actor: Actor = Depends(get_actor), session: Session = Depends(get_session)):
    ws = svc.viewable(session, actor, workspace_id)
    if actor.role != "SUPERVISOR":
        raise ServiceError("You don't have access to this.", 403, "FORBIDDEN")
    return svc.members_view(session, ws)


@router.post("/workspaces/{workspace_id}/members", status_code=201)
def add_member(workspace_id: str, body: MemberCreate, actor: Actor = Depends(get_actor), session: Session = Depends(get_session)):
    ws = svc.managed(session, actor, workspace_id)
    user = svc.add_member(session, actor, ws, **body.model_dump())
    session.commit()
    return next(m for m in svc.members_view(session, ws) if m["user_id"] == user.user_id)


@router.patch("/workspaces/{workspace_id}/members/{user_id}")
def update_member(workspace_id: str, user_id: str, body: MemberUpdate, actor: Actor = Depends(get_actor),
                  session: Session = Depends(get_session)):
    ws = svc.managed(session, actor, workspace_id)
    svc.update_member(session, actor, ws, user_id, body.model_dump(exclude_unset=True))
    session.commit()
    return next(m for m in svc.members_view(session, ws) if m["user_id"] == user_id)


@router.get("/workspaces/{workspace_id}/invites")
def invites(workspace_id: str, actor: Actor = Depends(get_actor), session: Session = Depends(get_session)):
    ws = svc.managed(session, actor, workspace_id)
    rows = session.scalars(select(InviteRow).where(InviteRow.workspace_id == ws.workspace_id).order_by(InviteRow.created_at.desc()))
    return [{"code": r.code, "role": r.role, "skills": r.skills, "label": r.label, "created_at": iso(r.created_at),
             "used": r.used_by is not None, "used_at": iso(r.used_at),
             "used_by_name": (session.get(UserRow, r.used_by).display_name if r.used_by else None)} for r in rows]


@router.post("/workspaces/{workspace_id}/invites", status_code=201)
def create_invite(workspace_id: str, body: InviteCreate, actor: Actor = Depends(get_actor), session: Session = Depends(get_session)):
    ws = svc.managed(session, actor, workspace_id)
    row = svc.create_invite(session, actor, ws, body.model_dump())
    session.commit()
    return {"code": row.code, "role": row.role, "workspace_name": ws.name}


@router.post("/workspaces/{workspace_id}/incidents", status_code=201)
def workspace_report(workspace_id: str, body: ReportCreate, request: Request, actor: Actor = Depends(get_actor),
                     session: Session = Depends(get_session), idempotency_key: str | None = Header(default=None, max_length=80)):
    """A worker, supervisor or admin of the workspace reports an incident inside it."""
    ws = svc.get_workspace(session, workspace_id)
    if actor.workspace_id != ws.workspace_id or actor.role not in ("WORKER", "SUPERVISOR"):
        raise ServiceError("Workspace not found.", 404, "NOT_FOUND")
    enabled = (ws.settings or {}).get("categories") or []
    if body.category not in enabled:
        raise ServiceError("This category is not enabled for this workspace.", 422, "CATEGORY_DISABLED")
    loc = body.device_location or body.user_location
    if loc is None:
        raise ServiceError("The report needs a location: allow device location, or choose the spot on the map.", 422,
                           "LOCATION_REQUIRED")
    flags = []
    if body.zone_id:
        zone = session.get(ZoneRow, body.zone_id)
        if zone is None or zone.workspace_id != ws.workspace_id:
            raise ServiceError("Unknown zone.", 422, "INVALID_ZONE")
    if ws.center_latitude is not None and ws.radius_m and \
            haversine_m(loc.latitude, loc.longitude, ws.center_latitude, ws.center_longitude) > ws.radius_m:
        flags.append("OUTSIDE_WORKSPACE_AREA")
    incident = _submit(request, session, actor, body, workspace_id=ws.workspace_id, channel="WORKSPACE",
                       idempotency_key=idempotency_key, extra_flags=flags)
    session.commit()
    return incident_detail(session, _app(request).categories, incident, task_of(session, incident.incident_id), actor)


@router.get("/workspaces/{workspace_id}/report")
def workspace_report_summary(workspace_id: str, request: Request, actor: Actor = Depends(get_actor),
                             session: Session = Depends(get_session)):
    """Summary for the workspace's reports page: per category and per day."""
    ws = svc.viewable(session, actor, workspace_id)
    if actor.role != "SUPERVISOR":
        raise ServiceError("You don't have access to this.", 403, "FORBIDDEN")
    cats = _app(request).categories
    rows = list(session.scalars(select(IncidentRow).where(IncidentRow.workspace_id == ws.workspace_id)
                                .order_by(IncidentRow.created_at.desc())))
    by_cat, by_day = {}, {}
    for i in rows:
        c = by_cat.setdefault(i.category, {"category": i.category, "label": cats.label(i.category), "total": 0, "resolved": 0})
        c["total"] += 1
        c["resolved"] += i.status == "RESOLVED"
        day = i.created_at.date().isoformat()
        by_day[day] = by_day.get(day, 0) + 1
    return {"total": len(rows), "resolved": sum(i.status == "RESOLVED" for i in rows),
            "by_category": sorted(by_cat.values(), key=lambda c: -c["total"]),
            "by_day": [{"day": d, "count": n} for d, n in sorted(by_day.items())][-30:],
            "recent": [incident_summary(session, cats, i, task_of(session, i.incident_id)) for i in rows[:50]]}


# --------------------------------------------------------------- events
@router.post("/events", status_code=201)
def create_event(body: EventCreate, actor: Actor = Depends(get_actor), session: Session = Depends(get_session)):
    ws = svc.create_event(session, actor, body.model_dump())
    session.commit()
    return svc.workspace_view(session, ws, detail=True)


@router.post("/events/{workspace_id}/open")
def open_event(workspace_id: str, actor: Actor = Depends(get_actor), session: Session = Depends(get_session)):
    ws = svc.open_event(session, actor, workspace_id)
    session.commit()
    return svc.workspace_view(session, ws, detail=True)


@router.post("/events/{workspace_id}/archive")
def archive_event(workspace_id: str, actor: Actor = Depends(get_actor), session: Session = Depends(get_session)):
    ws = svc.managed(session, actor, workspace_id)
    ws.status = "ARCHIVED"
    user = session.get(UserRow, actor.user_id)
    if user.workspace_id == ws.workspace_id:
        user.workspace_id = None
    audit(session, actor, "EVENT_ARCHIVED", None, workspace_id=ws.workspace_id)
    session.commit()
    return {"archived": True}


# ---------------------------------------------------------------- admin
@router.get("/admin/overview")
def admin_overview(actor: Actor = Depends(get_actor), session: Session = Depends(get_session)):
    _require(actor, "PLATFORM_ADMIN")
    return svc.admin_overview(session)


@router.post("/admin/workspaces/{workspace_id}/verification")
def set_verification(workspace_id: str, body: VerificationDecision, actor: Actor = Depends(get_actor),
                     session: Session = Depends(get_session)):
    _require(actor, "PLATFORM_ADMIN")
    ws = svc.get_workspace(session, workspace_id)
    if ws.kind != "ORGANIZATION":
        raise ServiceError("Only organizations are verified.", 422, "NOT_AN_ORGANIZATION")
    ws.verification_status, ws.verification_note = body.status, (body.note or ws.verification_note)
    audit(session, actor, "WORKSPACE_VERIFICATION", None, workspace_id=ws.workspace_id, status=body.status, note=body.note[:300])
    session.commit()
    return svc.workspace_view(session, ws)


@router.post("/admin/authorities", status_code=201)
def create_authority(body: AuthorityCreate, request: Request, actor: Actor = Depends(get_actor),
                     session: Session = Depends(get_session)):
    _require(actor, "PLATFORM_ADMIN")
    if body.workspace_id:
        ws = svc.get_workspace(session, body.workspace_id)
        if ws.kind != "ORGANIZATION":
            raise ServiceError("An authority can only be linked to an organization workspace.", 422, "INVALID_WORKSPACE")
    unknown = [c for c in body.categories if _app(request).categories.get(c) is None]
    if unknown:
        raise ServiceError(f"Unknown categories: {', '.join(unknown)}", 422, "UNKNOWN_CATEGORY")
    row = AuthorityRow(authority_id=new_id("AUTH", 4), **body.model_dump())
    session.add(row)
    audit(session, actor, "AUTHORITY_CREATED", None, authority_id=row.authority_id, name=row.name)
    session.commit()
    return svc.authority_view(row)


@router.delete("/admin/authorities/{authority_id}")
def delete_authority(authority_id: str, actor: Actor = Depends(get_actor), session: Session = Depends(get_session)):
    _require(actor, "PLATFORM_ADMIN")
    row = session.get(AuthorityRow, authority_id)
    if row is None:
        raise ServiceError("Authority not found.", 404, "NOT_FOUND")
    session.delete(row)
    audit(session, actor, "AUTHORITY_DELETED", None, authority_id=authority_id)
    session.commit()
    return {"deleted": True}


@router.post("/incidents/{incident_id}/forwarded")
def mark_forwarded(incident_id: str, actor: Actor = Depends(get_actor), session: Session = Depends(get_session)):
    """A supervisor records that they forwarded the report to the suggested
    authority themselves (by phone, email or the authority's portal)."""
    from geosatya.api.deps import load_incident
    if actor.role != "SUPERVISOR":
        raise ServiceError("You don't have access to this.", 403, "FORBIDDEN")
    inc = load_incident(session, incident_id, actor)
    if not inc.authority_id:
        raise ServiceError("This report has no suggested authority.", 409, "NO_AUTHORITY")
    inc.forwarding_status = "FORWARDED_MANUALLY"
    audit(session, actor, "FORWARDED_MANUALLY", inc.incident_id, authority_id=inc.authority_id)
    session.commit()
    return {"forwarding_status": inc.forwarding_status}


# --------------------------------------------------------- team agents
@router.get("/incidents/{incident_id}/agents")
def incident_agents(incident_id: str, actor: Actor = Depends(get_actor), session: Session = Depends(get_session)):
    """Duplicate Detection, Supervisor and Sanitation results for one incident (staff only)."""
    from geosatya.api.deps import load_incident
    if actor.role != "SUPERVISOR":
        raise ServiceError("You don't have access to this.", 403, "FORBIDDEN")
    inc = load_incident(session, incident_id, actor)
    return {"incident_id": inc.incident_id, "agents": agents_view(session, inc, actor)}


@router.post("/incidents/{incident_id}/agents/retry")
def retry_agents(incident_id: str, request: Request, actor: Actor = Depends(get_actor), session: Session = Depends(get_session)):
    from geosatya.api.deps import load_incident
    if actor.role != "SUPERVISOR":
        raise ServiceError("You don't have access to this.", 403, "FORBIDDEN")
    inc = load_incident(session, incident_id, actor)
    app = _app(request)
    run_team_agents(session, app.agents, inc)
    from geosatya.models import CompletionRow
    latest = session.scalar(select(CompletionRow).where(CompletionRow.incident_id == inc.incident_id, CompletionRow.media_id.is_not(None))
                            .order_by(CompletionRow.submitted_at.desc()).limit(1))
    if latest is not None:
        run_verification(session, app.settings, app.categories, app.verifier, latest)
    audit(session, actor, "AGENTS_RETRIED", inc.incident_id)
    session.commit()
    return {"incident_id": inc.incident_id, "agents": agents_view(session, inc, actor)}


@router.get("/agents/status")
def agents_status(request: Request):
    """Which team agents this server is connected to, and whether they answer now."""
    app = _app(request)
    a = app.agents
    rows = [("INCIDENT_INTELLIGENCE", "shreyakaushik878-cloud", app.intelligence, "/health"),
            ("DUPLICATE_DETECTION", OWNERS["DUPLICATE_DETECTION"], a.duplicate, "/docs"),
            ("SUPERVISOR", OWNERS["SUPERVISOR"], a.supervisor, "/health"),
            ("SANITATION", OWNERS["SANITATION"], a.sanitation, "/health")]
    verification = {"agent": "VERIFICATION", "owner": OWNERS["VERIFICATION"], "configured": app.verifier is not None,
                    "reachable": app.verifier is not None, "mode": app.settings.verification_agent}
    out = []
    for name, owner, client, path in rows:
        if client is None:
            out.append({"agent": name, "owner": owner, "configured": False, "reachable": False})
            continue
        try:
            import httpx
            with httpx.Client(timeout=2.0) as c:
                ok = c.get(f"{client.base_url}{path}").status_code < 500
        except Exception:
            ok = False
        out.append({"agent": name, "owner": owner, "configured": True, "reachable": ok})
    return {"agents": [*out, verification]}


# ------------------------------------------- before photo and checklist
class ChecklistUpdate(BaseModel):
    model_config = Strict
    completed: list[str] = Field(default_factory=list, max_length=50)


class BeforePhotoMeta(BaseModel):
    model_config = ConfigDict(extra="forbid")
    photo_meta: PhotoMeta = PhotoMeta()
    device_location: DeviceLocation | None = None
    device_location_error: DeviceError | None = None


@router.get("/tasks/{task_id}/work-check")
def work_check(task_id: str, request: Request, actor: Actor = Depends(get_actor), session: Session = Depends(get_session)):
    """The job's steps, which ones the worker ticked, and their before photo."""
    from geosatya.api.deps import load_task
    from geosatya.kavach import workcheck
    if actor.role not in ("WORKER", "SUPERVISOR"):
        raise ServiceError("Task not found.", 404, "NOT_FOUND")
    return workcheck.view(session, _app(request).categories, load_task(session, task_id, actor))


@router.post("/tasks/{task_id}/checklist")
def update_checklist(task_id: str, body: ChecklistUpdate, request: Request, actor: Actor = Depends(get_actor),
                     session: Session = Depends(get_session)):
    from geosatya.api.deps import load_task
    from geosatya.kavach import workcheck
    if actor.role != "WORKER":
        raise ServiceError("Only the assigned worker ticks steps.", 403, "FORBIDDEN")
    out = workcheck.save_checklist(session, _app(request).categories, load_task(session, task_id, actor), actor, body.completed)
    session.commit()
    return out


@router.post("/tasks/{task_id}/before-photo", status_code=201)
def before_photo(task_id: str, request: Request, payload: str = Form(default="{}"), photo: UploadFile = File(...),
                 idempotency_key: str | None = Header(default=None, max_length=80),
                 actor: Actor = Depends(get_actor), session: Session = Depends(get_session)):
    from geosatya.api.deps import load_task
    from geosatya.api.routes import _remember_key, _replayed, dump, parse_payload, read_upload
    from geosatya.kavach import workcheck
    if actor.role != "WORKER":
        raise ServiceError("Only the assigned worker adds a before photo.", 403, "FORBIDDEN")
    app = _app(request)
    task = load_task(session, task_id, actor)
    if _replayed(session, actor, "before_photo", idempotency_key) is not None:  # a re-sent offline upload
        return workcheck.view(session, app.categories, task)
    body = parse_payload(BeforePhotoMeta, payload)
    meta = dump(body.photo_meta)
    out = workcheck.add_before_photo(session, app.storage, app.settings, app.categories, task, actor,
                                     data=read_upload(photo, app.settings.max_image_size_bytes), meta=meta,
                                     device=dump(body.device_location), device_error=body.device_location_error)
    _remember_key(session, actor, "before_photo", idempotency_key, task.incident_id, out["before_photo"]["media_id"])
    session.commit()
    return out
