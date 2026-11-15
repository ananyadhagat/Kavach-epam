"""Worker's before photo and step checklist for a task (KAVACH addition).

Both are optional and additive: GeoSatya's completion rules (photo at the
spot, geofence, accuracy, freshness) are unchanged. They give the team's
Verification agent a real "before" image and the steps the worker says they
did, and they give the supervisor more to review."""

from __future__ import annotations

from sqlalchemy import select

from geosatya.kavach.agents import requirements_for
from geosatya.models import IncidentRow, MediaRow, TaskRow
from geosatya.platform_models import TaskChecklistRow
from geosatya.services.common import Actor, ServiceError, audit, device_evidence, store_photo
from geosatya.timeutil import iso, utcnow

OPEN = ("ASSIGNED", "IN_PROGRESS")


def view(session, categories, task: TaskRow) -> dict:
    incident = session.get(IncidentRow, task.incident_id)
    reqs = requirements_for(session, categories, incident)
    row = session.get(TaskChecklistRow, (task.task_id, task.attempt))
    done = set(row.completed if row else [])
    before = session.scalars(select(MediaRow).where(MediaRow.task_id == task.task_id, MediaRow.role == "BEFORE")
                             .order_by(MediaRow.received_at.desc())).first()
    return {"task_id": task.task_id, "attempt": task.attempt, "editable": task.status in OPEN,
            "steps": [{"id": r["requirement_id"], "label": r["label"], "done": r["requirement_id"] in done} for r in reqs],
            "steps_source": reqs[0]["source"] if reqs else None,
            "checklist_updated_at": iso(row.updated_at) if row else None,
            "before_photo": {"media_id": before.media_id, "url": f"/api/v1/media/{before.media_id}", "attempt": before.attempt,
                             "taken_at": iso(before.captured_at or before.received_at), "capture_source": before.capture_source}
            if before else None}


def save_checklist(session, categories, task: TaskRow, actor: Actor, completed: list[str]) -> dict:
    if task.status not in OPEN:
        raise ServiceError("The checklist can only change while the job is open.", 409, "TASK_LOCKED")
    incident = session.get(IncidentRow, task.incident_id)
    valid = {r["requirement_id"] for r in requirements_for(session, categories, incident)}
    unknown = [c for c in completed if c not in valid]
    if unknown:
        raise ServiceError("Unknown step: " + ", ".join(unknown[:5]), 422, "UNKNOWN_STEP")
    row = session.get(TaskChecklistRow, (task.task_id, task.attempt))
    if row is None:
        row = TaskChecklistRow(task_id=task.task_id, attempt=task.attempt)
        session.add(row)
    row.completed, row.updated_by, row.updated_at = list(dict.fromkeys(completed)), actor.user_id, utcnow()
    audit(session, actor, "CHECKLIST_UPDATED", incident.incident_id, task_id=task.task_id, attempt=task.attempt,
          completed=row.completed)
    session.flush()
    return view(session, categories, task)


def add_before_photo(session, storage, settings, categories, task: TaskRow, actor: Actor, *, data: bytes, meta: dict,
                     device: dict | None, device_error: str | None) -> dict:
    if task.status not in OPEN:
        raise ServiceError("A before photo can only be added while the job is open.", 409, "TASK_LOCKED")
    media, _exif = store_photo(session, storage, settings, data=data, incident=task.incident_id, task=task.task_id,
                               attempt=task.attempt, role="BEFORE", meta=meta, actor=actor)
    # Where the worker was when taking it, recorded like every other GeoSatya location source.
    device_evidence(session, incident=task.incident_id, task=task.task_id, attempt=task.attempt, actor=actor, device=device,
                    error=device_error, settings=settings, media_id=media.media_id)
    audit(session, actor, "BEFORE_PHOTO_ADDED", task.incident_id, task_id=task.task_id, media_id=media.media_id)
    session.flush()
    return view(session, categories, task)
