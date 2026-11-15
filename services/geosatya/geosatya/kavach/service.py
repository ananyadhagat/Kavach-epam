"""KAVACH workspace, jurisdiction and public-reporting services.

Authorization rules (enforced here, on the server):
- An organization admin manages only their own organization workspace.
- An event organizer manages only events they own; the event they have
  open is their working scope for GeoSatya's supervisor screens.
- Workers and supervisors belong to exactly one workspace.
- The platform admin sees tenant metadata (names, counts, verification),
  never a tenant's incidents or worker locations.
"""

from __future__ import annotations

import secrets
from collections import Counter
from datetime import datetime, timedelta

from sqlalchemy import func, select

from geosatya.kavach import catalog
from geosatya.location.coordinates import CoordinateError, haversine_m, validate_coordinates
from geosatya.models import AuditRow, IncidentRow, TaskProgressRow, TaskRow, UserRow, WorkerProfileRow
from geosatya.platform_models import AuthorityRow, DepartmentRow, InviteRow, PlanRow, WorkspaceRow, ZoneRow
from geosatya.scope import is_active
from geosatya.services.common import Actor, ServiceError, audit, new_id
from geosatya.timeutil import as_utc, iso, utcnow

TENANT_ADMINS = ("ORG_ADMIN", "EVENT_ORGANIZER")


# ------------------------------------------------------------------ plans
def ensure_plans(session) -> None:
    for plan_id, name, audience, basis, workers, events, sups, features in catalog.PLANS:
        if session.get(PlanRow, plan_id) is None:
            session.add(PlanRow(plan_id=plan_id, name=name, audience=audience, billing_basis=basis, max_workers=workers,
                                max_events=events, max_supervisors=sups, features=features, price_note=None))
    session.flush()


def plan_view(p: PlanRow | None) -> dict | None:
    if p is None:
        return None
    return {"plan_id": p.plan_id, "name": p.name, "audience": p.audience, "billing_basis": p.billing_basis,
            "max_workers": p.max_workers, "max_events": p.max_events, "max_supervisors": p.max_supervisors,
            "features": p.features, "price": p.price_note or "Pricing to be confirmed"}


# ------------------------------------------------------------- access
def get_workspace(session, workspace_id: str) -> WorkspaceRow:
    ws = session.get(WorkspaceRow, workspace_id)
    if ws is None or ws.status == "ARCHIVED":
        raise ServiceError("Workspace not found.", 404, "NOT_FOUND")
    return ws


def can_manage(actor: Actor, ws: WorkspaceRow) -> bool:
    if actor.platform_role == "EVENT_ORGANIZER":
        return ws.kind == "EVENT" and ws.owner_id == actor.user_id
    if actor.platform_role == "ORG_ADMIN":
        return ws.kind == "ORGANIZATION" and (ws.owner_id == actor.user_id or actor.workspace_id == ws.workspace_id)
    return False


def can_view(actor: Actor, ws: WorkspaceRow) -> bool:
    return can_manage(actor, ws) or actor.workspace_id == ws.workspace_id


def managed(session, actor: Actor, workspace_id: str) -> WorkspaceRow:
    ws = session.get(WorkspaceRow, workspace_id)
    if ws is None or not can_manage(actor, ws):
        raise ServiceError("Workspace not found.", 404, "NOT_FOUND")  # never reveal other tenants
    return ws


def viewable(session, actor: Actor, workspace_id: str) -> WorkspaceRow:
    ws = session.get(WorkspaceRow, workspace_id)
    if ws is None or not can_view(actor, ws):
        raise ServiceError("Workspace not found.", 404, "NOT_FOUND")
    return ws


# ------------------------------------------------------- registration
def _new_user(session, *, name: str, role: str, platform_role: str | None = None, workspace_id: str | None = None,
              department_id: str | None = None, phone: str | None = None, prefix: str = "U") -> UserRow:
    # Development access: identities are created without passwords and are
    # flagged is_demo, so they only work while AUTH_MODE=demo.
    user = UserRow(user_id=new_id(prefix, 4), display_name=name.strip()[:120], role=role, is_demo=True,
                   platform_role=platform_role, workspace_id=workspace_id, department_id=department_id, phone=phone)
    session.add(user)
    session.flush()
    return user


def _default_settings(kind: str) -> dict:
    cats = ([c for c in ("medical_assistance", "crowd_management", "security_concern", "missing_person", "event_operations",
                         "garbage", "safety_hazard")] if kind == "EVENT"
            else ["road_damage", "garbage", "water_leakage", "drainage", "streetlight", "infrastructure", "safety_hazard", "other"])
    return {
        "categories": cats,
        "priority_levels": list(catalog.PRIORITY_LEVELS),
        "worker_roles": list(catalog.DEFAULT_WORKER_ROLES[kind]),
        "target_hours": {c: catalog.DEFAULT_TARGET_HOURS.get(c, 24) for c in cats},
        "escalation": {"unassigned_after_min": 10 if kind == "EVENT" else 60, "notify_admin": True},
        "notifications": {"high_priority_alerts": True, "daily_summary": kind == "ORGANIZATION", "channels_connected": False},
        "dashboard": {"default_view": "map", "show_offline_workers": True},
        "assignment": {"auto_dispatch": True, "respect_zones": kind == "EVENT"},
    }


def _area(payload: dict) -> tuple[float | None, float | None, float | None]:
    lat, lon, radius = payload.get("center_latitude"), payload.get("center_longitude"), payload.get("radius_m")
    if lat is None or lon is None:
        return None, None, radius
    try:
        lat, lon = validate_coordinates(lat, lon)
    except CoordinateError as exc:
        raise ServiceError(f"Location: {exc}", 422, exc.code) from exc
    return lat, lon, radius


def register_organization(session, payload: dict) -> tuple[WorkspaceRow, UserRow]:
    if payload["category"] not in dict(catalog.ORG_CATEGORIES):
        raise ServiceError("Choose an organization category.", 422, "INVALID_CATEGORY")
    admin = _new_user(session, name=payload["admin_name"], role="SUPERVISOR", platform_role="ORG_ADMIN", prefix="ORG",
                      phone=payload.get("phone"))
    lat, lon, radius = _area(payload)
    now = utcnow()
    ws = WorkspaceRow(workspace_id=new_id("WS", 4), kind="ORGANIZATION", name=payload["name"].strip(), category=payload["category"],
                      description=payload.get("description", "").strip(), owner_id=admin.user_id,
                      organization_name=payload.get("legal_name") or payload["name"].strip(), contact_email=payload.get("contact_email"),
                      verification_status="PENDING" if payload.get("verification_details") else "UNVERIFIED",
                      verification_note=(payload.get("verification_details") or "")[:300] or None,
                      venue=payload.get("address"), center_latitude=lat, center_longitude=lon, radius_m=radius or 10000,
                      settings=_default_settings("ORGANIZATION"), plan_id="ORG_STANDARD", subscription_status="TRIAL",
                      renews_at=now + timedelta(days=30), created_at=now)
    session.add(ws)
    session.flush()
    admin.workspace_id = ws.workspace_id
    audit(session, Actor(admin.user_id, admin.role, admin.display_name), "WORKSPACE_REGISTERED", None,
          workspace_id=ws.workspace_id, kind="ORGANIZATION")
    return ws, admin


def register_event_organizer(session, payload: dict) -> UserRow:
    user = _new_user(session, name=payload["name"], role="SUPERVISOR", platform_role="EVENT_ORGANIZER", prefix="EO",
                     phone=payload.get("phone"))
    audit(session, Actor(user.user_id, user.role, user.display_name), "ORGANIZER_REGISTERED", None,
          company=(payload.get("company") or "")[:120])
    session.flush()
    return user  # the company name is stored on each event the organizer creates


def create_event(session, actor: Actor, payload: dict) -> WorkspaceRow:
    if actor.platform_role != "EVENT_ORGANIZER":
        raise ServiceError("Only event organizers can create events.", 403, "FORBIDDEN")
    if payload["category"] not in dict(catalog.EVENT_CATEGORIES):
        raise ServiceError("Choose an event category.", 422, "INVALID_CATEGORY")
    starts, ends = payload.get("starts_at"), payload.get("ends_at")
    if starts and ends and as_utc(ends) <= as_utc(starts):
        raise ServiceError("The event must end after it starts.", 422, "INVALID_DATES")
    lat, lon, radius = _area(payload)
    if lat is None:
        raise ServiceError("Set the event location on the map.", 422, "LOCATION_REQUIRED")
    owned = session.scalar(select(func.count()).select_from(WorkspaceRow).where(
        WorkspaceRow.owner_id == actor.user_id, WorkspaceRow.kind == "EVENT", WorkspaceRow.status == "ACTIVE")) or 0
    pilot = session.get(PlanRow, "PILOT")
    if pilot and pilot.max_events is not None and owned >= pilot.max_events:
        raise ServiceError(f"Your plan allows {pilot.max_events} active events. Archive one to create another.", 409, "PLAN_LIMIT")
    settings = _default_settings("EVENT")
    if payload.get("categories"):
        settings["categories"] = list(dict.fromkeys(payload["categories"]))
    ws = WorkspaceRow(workspace_id=new_id("EV", 4), kind="EVENT", name=payload["name"].strip(), category=payload["category"],
                      description=(payload.get("description") or "").strip(), owner_id=actor.user_id,
                      organization_name=payload.get("company"), contact_email=payload.get("contact_email"),
                      verification_status="UNVERIFIED", venue=payload.get("venue"), center_latitude=lat, center_longitude=lon,
                      radius_m=radius or 1000, starts_at=starts, ends_at=ends, settings=settings, plan_id="EVENT_PASS",
                      subscription_status="TRIAL", created_at=utcnow())
    session.add(ws)
    session.flush()
    session.get(UserRow, actor.user_id).workspace_id = ws.workspace_id  # the new event becomes the open one
    audit(session, actor, "EVENT_CREATED", None, workspace_id=ws.workspace_id)
    return ws


def open_event(session, actor: Actor, workspace_id: str) -> WorkspaceRow:
    ws = managed(session, actor, workspace_id)
    session.get(UserRow, actor.user_id).workspace_id = ws.workspace_id
    return ws


def update_workspace(session, actor: Actor, ws: WorkspaceRow, payload: dict, categories) -> WorkspaceRow:
    for key in ("name", "description", "venue", "contact_email", "organization_name"):
        if payload.get(key) is not None:
            setattr(ws, key, str(payload[key]).strip())
    if payload.get("center_latitude") is not None:
        ws.center_latitude, ws.center_longitude, r = _area(payload)
        ws.radius_m = r or ws.radius_m
    elif payload.get("radius_m"):
        ws.radius_m = payload["radius_m"]
    for key in ("starts_at", "ends_at"):
        if payload.get(key) is not None:
            setattr(ws, key, payload[key])
    if ws.starts_at and ws.ends_at and as_utc(ws.ends_at) <= as_utc(ws.starts_at):
        raise ServiceError("The event must end after it starts.", 422, "INVALID_DATES")
    if payload.get("settings"):
        merged = dict(ws.settings or {})
        incoming = payload["settings"]
        if "categories" in incoming:
            unknown = [c for c in incoming["categories"] if categories.get(c) is None]
            if unknown or not incoming["categories"]:
                raise ServiceError("Choose at least one known incident category.", 422, "INVALID_CATEGORY")
        if "priority_levels" in incoming:
            bad = [p for p in incoming["priority_levels"] if p not in catalog.PRIORITY_LEVELS]
            if bad or not incoming["priority_levels"]:
                raise ServiceError("Priority levels must be chosen from LOW, NORMAL, MEDIUM and HIGH.", 422, "INVALID_PRIORITY")
        for key in ("categories", "priority_levels", "worker_roles", "target_hours", "escalation", "notifications",
                    "dashboard", "assignment"):
            if key in incoming:
                merged[key] = incoming[key]
        merged.setdefault("notifications", {})["channels_connected"] = False  # not something a client can claim
        ws.settings = merged
    audit(session, actor, "WORKSPACE_UPDATED", None, workspace_id=ws.workspace_id)
    session.flush()
    return ws


# --------------------------------------------------------- structure
def add_department(session, actor: Actor, ws: WorkspaceRow, payload: dict) -> DepartmentRow:
    sup = payload.get("supervisor_id")
    if sup:
        user = session.get(UserRow, sup)
        if user is None or user.workspace_id != ws.workspace_id or user.role != "SUPERVISOR":
            raise ServiceError("The department supervisor must be a supervisor in this workspace.", 422, "INVALID_SUPERVISOR")
    row = DepartmentRow(department_id=new_id("DEP", 4), workspace_id=ws.workspace_id, name=payload["name"].strip(),
                        description=(payload.get("description") or "").strip(), categories=payload.get("categories") or [],
                        supervisor_id=sup, created_at=utcnow())
    session.add(row)
    audit(session, actor, "DEPARTMENT_CREATED", None, workspace_id=ws.workspace_id, name=row.name)
    session.flush()
    return row


def add_zone(session, actor: Actor, ws: WorkspaceRow, payload: dict) -> ZoneRow:
    try:
        lat, lon = validate_coordinates(payload["latitude"], payload["longitude"])
    except CoordinateError as exc:
        raise ServiceError(f"Zone location: {exc}", 422, exc.code) from exc
    row = ZoneRow(zone_id=new_id("ZN", 4), workspace_id=ws.workspace_id, name=payload["name"].strip(),
                  kind=payload.get("kind") or "AREA", latitude=lat, longitude=lon, radius_m=payload.get("radius_m") or 100,
                  created_at=utcnow())
    session.add(row)
    audit(session, actor, "ZONE_CREATED", None, workspace_id=ws.workspace_id, name=row.name)
    session.flush()
    return row


def _member_limit(session, ws: WorkspaceRow, role: str) -> None:
    plan = session.get(PlanRow, ws.plan_id) if ws.plan_id else None
    if plan is None:
        return
    limit = plan.max_workers if role == "WORKER" else plan.max_supervisors
    current = session.scalar(select(func.count()).select_from(UserRow).where(
        UserRow.workspace_id == ws.workspace_id, UserRow.role == role, UserRow.platform_role.is_(None))) or 0
    if limit is not None and current >= limit:
        raise ServiceError(f"The {plan.name} plan allows {limit} {role.lower()}s in this workspace.", 409, "PLAN_LIMIT")


def add_member(session, actor: Actor | None, ws: WorkspaceRow, *, name: str, role: str, skills: list[str] | None = None,
               department_id: str | None = None, phone: str | None = None, job_role: str | None = None) -> UserRow:
    if role not in ("WORKER", "SUPERVISOR"):
        raise ServiceError("A member is a worker or a supervisor.", 422, "INVALID_ROLE")
    if department_id:
        dep = session.get(DepartmentRow, department_id)
        if dep is None or dep.workspace_id != ws.workspace_id:
            raise ServiceError("Unknown department.", 422, "INVALID_DEPARTMENT")
    _member_limit(session, ws, role)
    user = _new_user(session, name=name, role=role, workspace_id=ws.workspace_id, department_id=department_id,
                     phone=phone, prefix="W" if role == "WORKER" else "SUP")
    if role == "WORKER":
        session.add(WorkerProfileRow(user_id=user.user_id, skills=list(dict.fromkeys(skills or [])), equipment=[],
                                     available=True, max_active_tasks=3))
    if actor is not None:
        audit(session, actor, "MEMBER_ADDED", None, workspace_id=ws.workspace_id, member_id=user.user_id, role=role,
              job_role=job_role)
    session.flush()
    return user


def update_member(session, actor: Actor, ws: WorkspaceRow, user_id: str, payload: dict) -> UserRow:
    user = session.get(UserRow, user_id)
    if user is None or user.workspace_id != ws.workspace_id or user.platform_role is not None:
        raise ServiceError("Member not found.", 404, "NOT_FOUND")
    if payload.get("active") is not None:
        user.is_active = bool(payload["active"])
    if payload.get("department_id") is not None:
        dep = session.get(DepartmentRow, payload["department_id"]) if payload["department_id"] else None
        if payload["department_id"] and (dep is None or dep.workspace_id != ws.workspace_id):
            raise ServiceError("Unknown department.", 422, "INVALID_DEPARTMENT")
        user.department_id = payload["department_id"] or None
    prof = session.get(WorkerProfileRow, user.user_id)
    if prof is not None:
        if payload.get("skills") is not None:
            prof.skills = list(dict.fromkeys(payload["skills"]))
        if payload.get("available") is not None:
            prof.available = bool(payload["available"])
    audit(session, actor, "MEMBER_UPDATED", None, workspace_id=ws.workspace_id, member_id=user.user_id,
          changes=sorted(k for k, v in payload.items() if v is not None))
    session.flush()
    return user


def create_invite(session, actor: Actor, ws: WorkspaceRow, payload: dict) -> InviteRow:
    role = payload.get("role") or "WORKER"
    if role not in ("WORKER", "SUPERVISOR"):
        raise ServiceError("Invite a worker or a supervisor.", 422, "INVALID_ROLE")
    code = "".join(secrets.choice("ABCDEFGHJKLMNPQRSTUVWXYZ23456789") for _ in range(8))
    row = InviteRow(code=code, workspace_id=ws.workspace_id, role=role, skills=payload.get("skills") or [],
                    department_id=payload.get("department_id"), label=payload.get("label"), created_by=actor.user_id,
                    created_at=utcnow())
    session.add(row)
    audit(session, actor, "INVITE_CREATED", None, workspace_id=ws.workspace_id, role=role)
    session.flush()
    return row


def redeem_invite(session, code: str, name: str, phone: str | None) -> UserRow:
    row = session.get(InviteRow, code.strip().upper())
    if row is None or row.used_by is not None:
        raise ServiceError("This invite code is not valid or has already been used.", 404, "INVALID_INVITE")
    ws = get_workspace(session, row.workspace_id)
    user = add_member(session, None, ws, name=name, role=row.role, skills=row.skills, department_id=row.department_id, phone=phone)
    row.used_by, row.used_at = user.user_id, utcnow()
    audit(session, Actor(user.user_id, user.role, user.display_name), "INVITE_REDEEMED", None, workspace_id=ws.workspace_id)
    session.flush()
    return user


# ------------------------------------------------------------- views
def workspace_view(session, ws: WorkspaceRow, *, detail: bool = False) -> dict:
    members = session.execute(select(UserRow.role, func.count()).where(UserRow.workspace_id == ws.workspace_id,
                                                                       UserRow.platform_role.is_(None))
                              .group_by(UserRow.role)).all()
    counts = dict(members)
    incidents = dict(session.execute(select(IncidentRow.status, func.count()).where(IncidentRow.workspace_id == ws.workspace_id)
                                     .group_by(IncidentRow.status)).all())
    labels = dict(catalog.EVENT_CATEGORIES if ws.kind == "EVENT" else catalog.ORG_CATEGORIES)
    now = utcnow()
    phase = None
    if ws.kind == "EVENT":
        phase = ("UPCOMING" if ws.starts_at and as_utc(ws.starts_at) > now else
                 "ENDED" if ws.ends_at and as_utc(ws.ends_at) < now else "LIVE" if ws.starts_at else "NOT_SCHEDULED")
    out = {
        "workspace_id": ws.workspace_id, "kind": ws.kind, "name": ws.name, "category": ws.category,
        "category_label": labels.get(ws.category, ws.category), "description": ws.description, "venue": ws.venue,
        "organization_name": ws.organization_name, "verification_status": ws.verification_status,
        "center": ({"latitude": ws.center_latitude, "longitude": ws.center_longitude} if ws.center_latitude is not None else None),
        "radius_m": ws.radius_m, "starts_at": iso(ws.starts_at), "ends_at": iso(ws.ends_at), "phase": phase,
        "workers": counts.get("WORKER", 0), "supervisors": counts.get("SUPERVISOR", 0),
        "incidents": {"total": sum(incidents.values()), "open": sum(v for k, v in incidents.items() if k != "RESOLVED"),
                      "resolved": incidents.get("RESOLVED", 0)},
        "plan": plan_view(session.get(PlanRow, ws.plan_id) if ws.plan_id else None),
        "subscription_status": ws.subscription_status, "renews_at": iso(ws.renews_at),
        "is_demo": ws.is_demo, "created_at": iso(ws.created_at),
    }
    if detail:
        out["settings"] = ws.settings or {}
        out["contact_email"] = ws.contact_email
        out["departments"] = [department_view(session, d) for d in
                              session.scalars(select(DepartmentRow).where(DepartmentRow.workspace_id == ws.workspace_id)
                                              .order_by(DepartmentRow.name))]
        out["zones"] = [zone_view(z) for z in session.scalars(select(ZoneRow).where(ZoneRow.workspace_id == ws.workspace_id)
                                                               .order_by(ZoneRow.name))]
    return out


def department_view(session, d: DepartmentRow) -> dict:
    n = session.scalar(select(func.count()).select_from(UserRow).where(UserRow.department_id == d.department_id)) or 0
    sup = session.get(UserRow, d.supervisor_id) if d.supervisor_id else None
    return {"department_id": d.department_id, "name": d.name, "description": d.description, "categories": d.categories,
            "supervisor_id": d.supervisor_id, "supervisor_name": sup.display_name if sup else None, "members": n}


def zone_view(z: ZoneRow) -> dict:
    return {"zone_id": z.zone_id, "name": z.name, "kind": z.kind, "latitude": z.latitude, "longitude": z.longitude,
            "radius_m": z.radius_m}


def members_view(session, ws: WorkspaceRow) -> list[dict]:
    deps = {d.department_id: d.name for d in session.scalars(select(DepartmentRow).where(DepartmentRow.workspace_id == ws.workspace_id))}
    load = dict(session.execute(select(TaskRow.worker_id, func.count()).where(
        TaskRow.status.in_(("ASSIGNED", "IN_PROGRESS", "AWAITING_VERIFICATION"))).group_by(TaskRow.worker_id)).all())
    out = []
    for u in session.scalars(select(UserRow).where(UserRow.workspace_id == ws.workspace_id, UserRow.platform_role.is_(None))
                             .order_by(UserRow.role.desc(), UserRow.display_name)):
        prof = session.get(WorkerProfileRow, u.user_id)
        out.append({"user_id": u.user_id, "name": u.display_name, "role": u.role, "active": is_active(u),
                    "department_id": u.department_id, "department": deps.get(u.department_id),
                    "skills": prof.skills if prof else [], "available": prof.available if prof else None,
                    "active_tasks": load.get(u.user_id, 0),
                    "location_shared_at": iso(prof.last_received_at) if prof else None})
    return out


# ------------------------------------------------------- jurisdiction
def suggest_authority(session, lat: float, lon: float, category: str, road_type: str | None) -> dict:
    """The configured authority whose area contains the point and which handles
    this category (and road type, when the citizen gave one). The most
    specific match wins: a matching road type, then the smallest area."""
    road = road_type if road_type and road_type != "UNKNOWN" else None
    matches = []
    for a in session.scalars(select(AuthorityRow)):
        distance_km = haversine_m(lat, lon, a.center_latitude, a.center_longitude) / 1000
        if distance_km > a.radius_km:
            continue
        if a.categories and category not in a.categories:
            continue
        if a.road_types:
            if road not in a.road_types:
                continue  # a highway authority only takes reports about its own road type
        matches.append((0 if a.road_types else 1, a.radius_km, a))
    if not matches:
        return {"authority": None, "reason": "No configured authority covers this location yet. The report stays with Kavach's "
                                             "open civic team for manual review."}
    matches.sort(key=lambda m: (m[0], m[1]))
    a = matches[0][2]
    why = [f"location is inside {a.name}'s configured area"]
    if a.road_types:
        why.append(f"road type given as {catalog.label_of(catalog.ROAD_TYPES, road).lower()}")
    if a.categories:
        why.append("it handles this category")
    return {"authority": authority_view(a), "reason": "Suggested because the " + ", ".join(why) + "."}


def authority_view(a: AuthorityRow) -> dict:
    return {"authority_id": a.authority_id, "name": a.name, "kind": a.kind, "radius_km": a.radius_km,
            "center": {"latitude": a.center_latitude, "longitude": a.center_longitude},
            "categories": a.categories, "road_types": a.road_types, "on_kavach": a.workspace_id is not None,
            "workspace_id": a.workspace_id, "integration": a.integration, "contact": a.contact, "data_note": a.data_note,
            "is_demo": a.is_demo}


# ------------------------------------------------------ public views
PUBLIC_STAGES = [("SUBMITTED", "Received"), ("ASSIGNED", "Assigned"), ("IN_PROGRESS", "Work in progress"),
                 ("AWAITING_VERIFICATION", "Being verified"), ("RESOLVED", "Resolved")]


def public_scope():
    """Incidents that are public civic reports (never private event or
    organization-internal incidents)."""
    return (IncidentRow.channel == "PUBLIC_PORTAL") | (IncidentRow.workspace_id.is_(None))


def public_track(session, categories, reference: str) -> dict:
    inc = session.get(IncidentRow, reference.strip().upper())
    if inc is None or not (inc.channel == "PUBLIC_PORTAL" or inc.workspace_id is None):
        raise ServiceError("No public report has this reference.", 404, "NOT_FOUND")
    reached = {}
    for e in session.scalars(select(AuditRow).where(AuditRow.incident_id == inc.incident_id).order_by(AuditRow.event_time)):
        to = (e.details or {}).get("to_status")
        if e.action == "INCIDENT_REPORTED":
            reached.setdefault("SUBMITTED", e.event_time)
        elif to:
            reached[to] = e.event_time  # the latest time each stage was reached (rework can repeat a stage)
    order = [s for s, _ in PUBLIC_STAGES]
    current = order.index(inc.status) if inc.status in order else 0
    authority = session.get(AuthorityRow, inc.authority_id) if inc.authority_id else None
    return {
        "reference": inc.incident_id, "category": inc.category, "category_label": categories.label(inc.category),
        "status": inc.status, "reported_at": iso(inc.created_at), "updated_at": iso(inc.updated_at),
        "stages": [{"status": s, "label": label, "done": i <= current, "current": i == current,
                    "at": iso(reached.get(s)) if i <= current else None} for i, (s, label) in enumerate(PUBLIC_STAGES)],
        "authority": {"name": authority.name, "kind": authority.kind, "on_kavach": authority.workspace_id is not None}
        if authority else None,
        "forwarding_status": inc.forwarding_status or "NOT_FORWARDED",
        "is_demo": inc.is_demo,
    }


def public_stats(session, categories) -> dict:
    rows = list(session.scalars(select(IncidentRow).where(public_scope())))
    by_status = Counter(i.status for i in rows)
    by_cat = Counter(i.category for i in rows)
    durations = []
    for p, inc in session.execute(select(TaskProgressRow, IncidentRow).join(TaskRow, TaskRow.task_id == TaskProgressRow.task_id)
                                  .join(IncidentRow, IncidentRow.incident_id == TaskRow.incident_id)
                                  .where(TaskProgressRow.resolved_at.is_not(None), public_scope())):
        durations.append((as_utc(p.resolved_at) - as_utc(inc.created_at)).total_seconds() / 3600)
    durations.sort()
    median = round(durations[len(durations) // 2], 1) if durations else None
    # Location is shown only as ~1 km cells with counts, never exact points.
    cells = Counter((round(i.latitude, 2), round(i.longitude, 2)) for i in rows)
    week_ago = utcnow() - timedelta(days=7)
    return {
        "total": len(rows), "resolved": by_status.get("RESOLVED", 0),
        "open": len(rows) - by_status.get("RESOLVED", 0),
        "reported_this_week": sum(as_utc(i.created_at) >= week_ago for i in rows),
        "resolution_rate": round(100 * by_status.get("RESOLVED", 0) / len(rows)) if rows else None,
        "median_resolution_hours": median,
        "by_status": [{"status": s, "label": label, "count": by_status.get(s, 0)} for s, label in PUBLIC_STAGES],
        "by_category": [{"category": c, "label": categories.label(c), "count": n} for c, n in by_cat.most_common()],
        "areas": [{"latitude": lat, "longitude": lon, "count": n} for (lat, lon), n in cells.items()],
        "includes_demo_data": any(i.is_demo for i in rows),
    }


def admin_overview(session) -> dict:
    out = []
    for ws in session.scalars(select(WorkspaceRow).order_by(WorkspaceRow.created_at.desc())):
        v = workspace_view(session, ws)
        owner = session.get(UserRow, ws.owner_id)
        out.append({**{k: v[k] for k in ("workspace_id", "kind", "name", "category_label", "verification_status", "workers",
                                          "supervisors", "incidents", "plan", "subscription_status", "phase", "is_demo",
                                          "created_at", "organization_name")},
                    "owner_name": owner.display_name if owner else None, "verification_note": ws.verification_note})
    users = Counter(r for r, in session.execute(select(UserRow.role)))
    return {"workspaces": out, "users": dict(users),
            "civic_incidents": session.scalar(select(func.count()).select_from(IncidentRow).where(public_scope())) or 0,
            "plans": [plan_view(p) for p in session.scalars(select(PlanRow).order_by(PlanRow.plan_id))],
            "authorities": [authority_view(a) for a in session.scalars(select(AuthorityRow).order_by(AuthorityRow.name))]}


def in_event_window(ws: WorkspaceRow, now: datetime | None = None) -> bool:
    now = now or utcnow()
    return not ((ws.starts_at and as_utc(ws.starts_at) - timedelta(hours=12) > now) or
                (ws.ends_at and as_utc(ws.ends_at) + timedelta(hours=12) < now))
