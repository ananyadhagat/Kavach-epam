"""Response shapes. What each role sees is decided here."""

from __future__ import annotations

from sqlalchemy import select

from geosatya.models import (
    AuditRow, CompletionRow, DispatchRow, EvidenceRow, IncidentRow, IntelligenceRow, MediaRow, ProgressUpdateRow,
    TaskProgressRow, TaskRow, UserRow,
)
from geosatya.services import estimates
from geosatya.services.common import Actor
from geosatya.services.intelligence import priority_of
from geosatya.services.tracking import PHASE_TEXT, phase_of
from geosatya.timeutil import as_utc, iso

STATUS_TEXT = {
    "SUBMITTED": "Received", "ASSIGNED": "Assigned to a field team", "IN_PROGRESS": "Work in progress",
    "AWAITING_VERIFICATION": "Work done, being verified", "RESOLVED": "Resolved",
}


def name_of(session, user_id):
    user = session.get(UserRow, user_id) if user_id else None
    return user.display_name if user else user_id


def media_view(m: MediaRow, exif: EvidenceRow | None, *, detail: bool) -> dict:
    data = {"media_id": m.media_id, "role": m.role, "url": f"/api/v1/media/{m.media_id}",
            "capture_source": m.capture_source, "width": m.width, "height": m.height}
    if detail:
        data.update({
            "exif_status": m.exif_status, "sha256": m.sha256,
            "times": {"image_captured_at": iso(m.captured_at), "exif_claimed_time": m.exif_datetime_original,
                      "uploaded_at": iso(m.uploaded_at), "server_received_at": iso(m.received_at)},
            "exif_gps": {"latitude": exif.latitude, "longitude": exif.longitude} if exif is not None and exif.available else None,
        })
    return data


def photos(session, incident_id, *, role=None, task_id=None, attempt=None, detail=False):
    q = select(MediaRow).where(MediaRow.incident_id == incident_id).order_by(MediaRow.received_at)
    if role:
        q = q.where(MediaRow.role == role)
    if task_id:
        q = q.where(MediaRow.task_id == task_id)
    if attempt:
        q = q.where(MediaRow.attempt == attempt)
    out = []
    for m in session.scalars(q):
        exif = session.scalar(select(EvidenceRow).where(EvidenceRow.media_id == m.media_id, EvidenceRow.source_type == "IMAGE_EXIF"))
        out.append(media_view(m, exif, detail=detail))
    return out


def completion_view(session, c: CompletionRow, *, detail: bool) -> dict:
    data = {"completion_id": c.completion_id, "incident_id": c.incident_id, "attempt": c.attempt,
            "outcome": c.outcome, "accepted": c.accepted, "message": c.result.get("message"),
            "distance_m": c.result.get("distance_m"), "accuracy_m": c.result.get("accuracy_m"),
            "radius_m": c.result.get("radius_m"), "reason_codes": c.result.get("reason_codes", []),
            "simulated": c.result.get("simulated", False), "description": c.description,
            "worker_name": name_of(session, c.worker_id), "submitted_at": iso(c.submitted_at),
            "review_decision": c.review_decision, "review_reason": c.review_reason,
            "reviewed_by_name": name_of(session, c.reviewed_by), "reviewed_at": iso(c.reviewed_at)}
    if detail:
        dev = session.get(EvidenceRow, c.device_evidence_id) if c.device_evidence_id else None
        data["result"] = c.result
        # Several retries can share one task attempt; pick this completion's own photo.
        data["photo"] = next((p for p in photos(session, c.incident_id, role="COMPLETION", detail=True)
                              if p["media_id"] == c.media_id), None)
        data["device"] = None if dev is None else {
            "available": dev.available, "latitude": dev.latitude, "longitude": dev.longitude,
            "accuracy_m": dev.accuracy_m, "mode": dev.mode, "observed_at": iso(dev.observed_at),
            "unavailable_reason": dev.unavailable_reason}
    return data


def task_view(session, t: TaskRow | None) -> dict | None:
    if t is None:
        return None
    return {"task_id": t.task_id, "status": t.status, "attempt": t.attempt, "worker_id": t.worker_id,
            "worker_name": name_of(session, t.worker_id), "target_latitude": t.target_latitude,
            "target_longitude": t.target_longitude, "target_source": t.target_source,
            "rework_reason": t.rework_reason, "assigned_at": iso(t.assigned_at)}


def incident_summary(session, categories, i: IncidentRow, task: TaskRow | None) -> dict:
    cat = categories.get(i.category) or {}
    return {"incident_id": i.incident_id, "category": i.category, "category_label": cat.get("label", i.category),
            "category_icon": cat.get("icon", "dots"), "title": i.title, "status": i.status,
            "status_text": STATUS_TEXT.get(i.status, i.status), "created_at": iso(i.created_at),
            "updated_at": iso(i.updated_at), "is_demo": i.is_demo, "task_id": task.task_id if task else None,
            "priority": priority_of(session.get(IntelligenceRow, i.incident_id)),
            "rework": bool(task and task.rework_reason and task.status in ("ASSIGNED", "IN_PROGRESS"))}


def incident_detail(session, categories, i: IncidentRow, task: TaskRow | None, actor: Actor) -> dict:
    cat = categories.get(i.category) or {}
    data = incident_summary(session, categories, i, task)
    data.update({
        "description": i.description, "asset_identifier": i.asset_identifier, "asset_label": cat.get("asset_label"),
        "instructions": cat.get("instructions", []),
        "location": {"latitude": i.latitude, "longitude": i.longitude, "source": i.location_source,
                     "accuracy_m": i.location_accuracy_m, "observed_at": iso(i.location_observed_at),
                     "mode": i.location_mode, "flags": i.location_flags},
        "photos": photos(session, i.incident_id, role="REPORT", detail=actor.role == "SUPERVISOR"),
        "task": task_view(session, task),
        "reporter_name": name_of(session, i.reporter_id) if actor.role != "WORKER" else None,
    })
    if task is not None and actor.role in ("WORKER", "SUPERVISOR"):
        rows = session.scalars(select(CompletionRow).where(CompletionRow.task_id == task.task_id)
                               .order_by(CompletionRow.submitted_at)).all()
        data["completions"] = [completion_view(session, c, detail=actor.role == "SUPERVISOR") for c in rows]
        data["completion_photos"] = photos(session, i.incident_id, role="COMPLETION", detail=actor.role == "SUPERVISOR")
    progress = session.get(TaskProgressRow, task.task_id) if task is not None else None
    data["progress"] = progress_view(session, task, progress, i)
    data["intelligence"] = intelligence_view(session.get(IntelligenceRow, i.incident_id), full=actor.role == "SUPERVISOR")
    if actor.role == "SUPERVISOR":
        data["dispatch"] = dispatch_view(session, list(session.scalars(
            select(DispatchRow).where(DispatchRow.incident_id == i.incident_id).order_by(DispatchRow.created_at))))
    events = session.scalars(select(AuditRow).where(AuditRow.incident_id == i.incident_id).order_by(AuditRow.event_time)).all()
    shown = events if actor.role == "SUPERVISOR" else [e for e in events if e.action in ("INCIDENT_REPORTED", "STATUS_CHANGED")]
    data["timeline"] = [audit_view(session, e) for e in shown]
    return data


def intelligence_view(row: IntelligenceRow | None, *, full: bool) -> dict:
    """System-generated analysis, labelled as such. Citizens see only that it ran."""
    if row is None:
        return {"status": "NOT_RUN", "priority": "NORMAL"}
    data = {"status": row.status, "priority": priority_of(row), "source": "Incident Intelligence agent (system generated)"}
    if full:
        data.update({"category": row.category, "incident_type": row.incident_type, "severity": row.severity,
                     "severity_reason": row.severity_reason, "severity_rule_matches": row.severity_rule_matches,
                     "summary": row.summary, "needs_clarification": row.needs_clarification,
                     "clarification_questions": row.clarification_questions,
                     "missing_information": row.missing_information, "location_check_status": row.location_check_status,
                     "external_incident_id": row.external_incident_id, "request_id": row.request_id,
                     "model_info": row.model_info, "attempts": row.attempts, "last_error": row.last_error,
                     "requested_at": iso(row.requested_at), "completed_at": iso(row.completed_at)})
    return data


def dispatch_view(session, rows: list[DispatchRow]) -> dict | None:
    if not rows:
        return None
    latest = rows[-1]
    names = {w: name_of(session, w) for r in rows for w in [r.worker_id, *[c["worker_id"] for c in r.ranking],
                                                           *[x["worker_id"] for x in r.rejected]] if w}
    return {"status": latest.status, "method": latest.method, "worker_id": latest.worker_id,
            "worker_name": names.get(latest.worker_id), "priority": latest.priority, "reason": latest.reason,
            "required_skills": latest.required_skills, "required_equipment": latest.required_equipment,
            "ranking": latest.ranking, "rejected": [{**x, "worker_name": names.get(x["worker_id"])} for x in latest.rejected],
            "decided_at": iso(latest.created_at),
            "history": [{"status": r.status, "method": r.method, "worker_name": names.get(r.worker_id), "reason": r.reason,
                         "time": iso(r.created_at)} for r in rows]}


def progress_view(session, task: TaskRow | None, progress: TaskProgressRow | None, i: IncidentRow) -> dict:
    """Milestones (recorded times only), the journey phase, the resolution estimate,
    and a timeline of events that actually happened."""
    p = progress
    phase = phase_of(task, p)
    intel = session.get(IntelligenceRow, i.incident_id)
    return {"phase": phase, "phase_text": PHASE_TEXT[phase],
            "reported_at": iso(i.created_at),
            "analysed_at": iso(intel.completed_at) if intel is not None and intel.status == "COMPLETED" else None,
            "assigned_at": iso(task.assigned_at) if task else None,
            "accepted_at": iso(p.accepted_at) if p else None,
            "tracking_started_at": iso(p.tracking_started_at) if p else None, "arrived_at": iso(p.arrived_at) if p else None,
            "work_started_at": iso(p.work_started_at) if p else None,
            "completion_submitted_at": iso(p.completion_submitted_at) if p else None,
            "resolved_at": iso(p.resolved_at) if p else None, "tracking_active": bool(p and p.tracking_active),
            "etr": estimates.etr_view(task, p, i), "events": timeline_events(session, i, task, p, intel)}


def timeline_events(session, i: IncidentRow, task, p, intel) -> list[dict]:
    """Citizen-facing events from persisted timestamps only; nothing is shown before it happens."""
    ev = [("REPORTED", i.created_at, "Incident reported", None)]
    if intel is not None and intel.status == "COMPLETED":
        ev.append(("ANALYSED", intel.completed_at, "Analysed by Incident Intelligence", f"Priority {priority_of(intel)}"))
    for d in session.scalars(select(DispatchRow).where(DispatchRow.incident_id == i.incident_id).order_by(DispatchRow.created_at)):
        if d.status == "UNASSIGNED":
            ev.append(("ASSIGNMENT_PENDING", d.created_at, "No field worker available yet", "A supervisor will assign it"))
        elif d.status == "RELEASED":
            ev.append(("ASSIGNMENT_RELEASED", d.created_at, "Assignment withdrawn", {"DECLINED": "Worker declined",
                       "ACCEPTANCE_TIMEOUT": "Not accepted in time", "CANCELLED": "Cancelled by a supervisor"}.get(d.method, d.method)))
        elif d.method == "REASSIGNED":
            ev.append(("REASSIGNED", d.created_at, "Reassigned to another worker", None))
        else:
            ev.append(("ASSIGNED", d.created_at, "Field worker assigned", None))
    if p is not None:
        for key, at, text in (("ACCEPTED", p.accepted_at, "Worker accepted"), ("EN_ROUTE", p.tracking_started_at, "Worker on the way"),
                              ("ARRIVED", p.arrived_at, "Worker arrived (estimated from shared location)"),
                              ("WORK_STARTED", p.work_started_at, "Work started")):
            if at is not None:
                ev.append((key, at, text, None))
    if task is not None:
        for u in session.scalars(select(ProgressUpdateRow).where(ProgressUpdateRow.task_id == task.task_id)):
            ev.append(("PROGRESS_UPDATE", u.created_at, "Progress update",
                       u.note + (f" · about {u.estimate_minutes} min left (worker's estimate)" if u.estimate_minutes else "")))
        for c in session.scalars(select(CompletionRow).where(CompletionRow.task_id == task.task_id, CompletionRow.accepted.is_(True))
                                 .order_by(CompletionRow.submitted_at)):
            ev.append(("EVIDENCE_SUBMITTED", c.submitted_at, "Completion evidence submitted", f"Attempt {c.attempt}"))
            ev.append(("LOCATION_VERIFIED", c.submitted_at, "Location verification completed",
                       {"PASS": "Verified on site", "REVIEW_REQUIRED": "Needs supervisor review"}.get(c.outcome, c.outcome)))
            if c.reviewed_at is not None:
                ev.append(("REVIEWED", c.reviewed_at, "Supervisor review completed",
                           {"APPROVE": "Approved", "REJECT": "Sent back for rework", "REQUEST_EVIDENCE": "More evidence requested"}
                           .get(c.review_decision, c.review_decision)))
    if p is not None and p.resolved_at is not None:
        ev.append(("RESOLVED", p.resolved_at, "Incident resolved", None))
    ev.sort(key=lambda e: as_utc(e[1]))
    return [{"event": k, "time": iso(t), "text": text, "detail": detail} for k, t, text, detail in ev]


def audit_view(session, e: AuditRow) -> dict:
    system_names = {"dispatch": "Dispatch", "incident-intelligence": "Incident Intelligence"}
    who = system_names.get(e.actor_id, "Verification engine") if e.actor_role == "SYSTEM" else name_of(session, e.actor_id)
    return {"event_id": e.event_id, "actor": who, "actor_role": e.actor_role, "action": e.action,
            "incident_id": e.incident_id, "time": iso(e.event_time), "details": e.details or {}}
