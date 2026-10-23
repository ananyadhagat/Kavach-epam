"""Response shapes. What each role sees is decided here."""

from __future__ import annotations

from sqlalchemy import select

from geosatya.models import AuditRow, CompletionRow, EvidenceRow, IncidentRow, MediaRow, TaskRow, UserRow
from geosatya.services.common import Actor
from geosatya.timeutil import iso

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
    events = session.scalars(select(AuditRow).where(AuditRow.incident_id == i.incident_id).order_by(AuditRow.event_time)).all()
    shown = events if actor.role == "SUPERVISOR" else [e for e in events if e.action in ("INCIDENT_REPORTED", "STATUS_CHANGED")]
    data["timeline"] = [audit_view(session, e) for e in shown]
    return data


def audit_view(session, e: AuditRow) -> dict:
    who = "Verification engine" if e.actor_role == "SYSTEM" else name_of(session, e.actor_id)
    return {"event_id": e.event_id, "actor": who, "actor_role": e.actor_role, "action": e.action,
            "incident_id": e.incident_id, "time": iso(e.event_time), "details": e.details or {}}
