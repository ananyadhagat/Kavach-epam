"""Worker tasks: start, submit completion evidence, supervisor review."""

from __future__ import annotations

from sqlalchemy import select


from geosatya.location.geofence import Fix, check_worker_location
from geosatya.models import CompletionRow, IncidentRow, MediaRow, TaskRow
from geosatya.services.common import (
    Actor, ServiceError, audit, device_evidence, make_policy, move_incident, new_id, set_task_status, store_photo,
)
from geosatya.timeutil import utcnow


def start_task(session, task: TaskRow, incident: IncidentRow, actor: Actor) -> None:
    if task.status == "IN_PROGRESS":
        return
    if task.status != "ASSIGNED":
        raise ServiceError(f"The task cannot be started while it is {task.status}.", 409, "INVALID_TRANSITION")
    set_task_status(task, "IN_PROGRESS")
    move_incident(session, incident, "IN_PROGRESS", actor, "Worker started")


def submit_completion(session, storage, settings, task: TaskRow, incident: IncidentRow, actor: Actor, *,
                      photo: bytes | None, meta: dict, device: dict | None, device_error: str | None,
                      description: str) -> CompletionRow:
    """Verify the worker's location against the incident's *original* location.

    FAIL and NOT_CHECKED attempts are recorded but not accepted: the task stays
    IN_PROGRESS so the worker can move and retry. PASS and REVIEW_REQUIRED
    attempts go to a supervisor. Nothing is resolved here."""
    if task.status != "IN_PROGRESS":
        raise ServiceError(f"Start the task first (it is {task.status}).", 409, "TASK_NOT_IN_PROGRESS")
    description = (description or "").strip()
    missing = []
    if not photo:
        missing.append("MISSING_COMPLETION_PHOTO")
    if len(description) < settings.min_completion_chars:
        missing.append("COMPLETION_DESCRIPTION_TOO_SHORT")
    if device is None and not device_error:
        missing.append("DEVICE_LOCATION_NOT_RECORDED")
    if missing:
        raise ServiceError("Required completion evidence is missing: " + ", ".join(missing), 422, ",".join(missing))

    media, exif_row = store_photo(session, storage, settings, data=photo, incident=incident.incident_id, task=task.task_id,
                                  attempt=task.attempt, role="COMPLETION", meta=meta, actor=actor)
    device_row = device_evidence(session, incident=incident.incident_id, task=task.task_id, attempt=task.attempt,
                                 actor=actor, device=device, error=device_error, settings=settings, media_id=media.media_id)
    session.flush()

    # A photo reused from this incident or another job is not new evidence.
    # (A photo from an earlier attempt that was never accepted doesn't count.)
    rejected = set(session.scalars(select(CompletionRow.media_id).where(CompletionRow.accepted.is_(False))))
    duplicate = any(m not in rejected for m in session.scalars(
        select(MediaRow.media_id).where(MediaRow.sha256 == media.sha256, MediaRow.media_id != media.media_id)))
    fix = Fix(device_row.latitude, device_row.longitude, device_row.accuracy_m, device_row.mode == "SIMULATED") \
        if device_row.available else None
    exif = (exif_row.latitude, exif_row.longitude) if exif_row.available else None
    # The target is the task's stored location. The request cannot change it.
    result = check_worker_location(
        target=(task.target_latitude, task.target_longitude), fix=fix, unavailable_reason=device_row.unavailable_reason,
        exif=exif, photo_source=media.capture_source, duplicate=duplicate, policy=make_policy(session, settings))
    result["times"] = {
        "image_captured_at": media.captured_at.isoformat() if media.captured_at else None,
        "location_observed_at": device_row.observed_at.isoformat() if device_row.observed_at else None,
        "uploaded_at": media.uploaded_at.isoformat() if media.uploaded_at else None,
        "server_received_at": media.received_at.isoformat(),
    }
    result["photo_source"] = media.capture_source
    result["exif_status"] = media.exif_status
    outcome = result["outcome"]
    accepted = outcome in ("PASS", "REVIEW_REQUIRED")

    completion = CompletionRow(
        completion_id=new_id("CMP", 4), task_id=task.task_id, incident_id=incident.incident_id, attempt=task.attempt,
        worker_id=actor.user_id, media_id=media.media_id, device_evidence_id=device_row.evidence_id,
        description=description, outcome=outcome, accepted=accepted, result=result, submitted_at=utcnow())
    session.add(completion)
    audit(session, Actor("verification-engine", "SYSTEM", "Verification"), "LOCATION_VERIFIED", incident.incident_id,
          outcome=outcome, reason_codes=result["reason_codes"], distance_m=result["distance_m"],
          accuracy_m=result["accuracy_m"], radius_m=result["radius_m"], accepted=accepted, attempt=task.attempt)
    if accepted:
        set_task_status(task, "AWAITING_VERIFICATION")
        move_incident(session, incident, "AWAITING_VERIFICATION", actor, f"Evidence submitted ({outcome})")
    session.flush()
    return completion


def pending_completion(session, task: TaskRow) -> CompletionRow | None:
    """The accepted, not-yet-reviewed completion of the current attempt."""
    return session.scalar(select(CompletionRow).where(
        CompletionRow.task_id == task.task_id, CompletionRow.attempt == task.attempt,
        CompletionRow.accepted.is_(True), CompletionRow.reviewed_at.is_(None))
        .order_by(CompletionRow.submitted_at.desc()).limit(1))


def review(session, completion: CompletionRow, task: TaskRow, incident: IncidentRow, actor: Actor,
           decision: str, reason: str) -> None:
    reason = (reason or "").strip()
    if (completion.reviewed_at is not None or not completion.accepted or completion.attempt != task.attempt
            or task.status != "AWAITING_VERIFICATION"):
        raise ServiceError("This evidence is not waiting for a decision.", 409, "NOT_AWAITING_REVIEW")
    # Approving something the checks did not pass, or rejecting something they
    # did, is an override and needs a recorded reason. Sending work back always does.
    override = (decision == "APPROVE") != (completion.outcome == "PASS")
    if decision != "APPROVE" or override:
        if len(reason) < 5:
            raise ServiceError("Please give a reason (at least 5 characters).", 422, "REASON_REQUIRED")
    completion.review_decision, completion.reviewed_by = decision, actor.user_id
    completion.review_reason, completion.reviewed_at = reason or None, utcnow()
    if decision == "APPROVE":
        set_task_status(task, "RESOLVED")
        move_incident(session, incident, "RESOLVED", actor, reason or "Approved after review")
    else:
        # REJECT and REQUEST_EVIDENCE both send the job back to the worker as a new attempt.
        task.attempt += 1
        task.rework_reason = reason
        set_task_status(task, "ASSIGNED")
        move_incident(session, incident, "ASSIGNED", actor, f"Sent back for rework: {reason}")
    audit(session, actor, "SUPERVISOR_DECISION", incident.incident_id, decision=decision, reason=reason[:500],
          automated_outcome=completion.outcome, override=override, attempt=completion.attempt)
