"""Optional voice notes, in two places only:

* SOS: the citizen can record what is happening. The owner can play it back, and
  each trusted ally can play it from their private link while the SOS is active.
* Task completion: the field worker can add a spoken note (extra work done,
  problems, missing resources, instructions) to a task attempt. The worker and
  supervisors of the task's workspace can play it back.

A voice note is never required and never changes a GeoSatya decision (geofence,
verification, approval). Files are kept in private storage outside any public
folder, named by the server, and served only through these authorized routes.
"""

from __future__ import annotations

import hashlib
import os
import re
import secrets
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from geosatya.api.deps import get_actor, get_session, load_task
from geosatya.models import CompletionRow, IncidentRow
from geosatya.platform_models import AudioNoteRow, SosNotificationRow, SosRow
from geosatya.services.common import Actor, ServiceError, audit, new_id
from geosatya.timeutil import iso, utcnow

router = APIRouter(tags=["Voice notes"])

MAX_BYTES = 6 * 1024 * 1024
MIN_BYTES = 200
MAX_SECONDS = 180
MAX_PER_SOS = 5
MAX_PER_ATTEMPT = 3
EXTENSIONS = {"audio/webm": ".webm", "audio/ogg": ".ogg", "audio/mp4": ".m4a", "audio/mpeg": ".mp3", "audio/wav": ".wav"}
_KEY = re.compile(r"^[0-9a-f]{32}\.(?:webm|ogg|m4a|mp3|wav)$")


class AudioStorage:
    """Private local storage for voice notes (same contract as the image storage)."""

    def __init__(self, base_dir: Path) -> None:
        self.base_dir = Path(base_dir).resolve()
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        if not _KEY.fullmatch(key):
            raise ServiceError("Invalid storage key", 500, "STORAGE")
        path = (self.base_dir / key).resolve()
        if path.parent != self.base_dir:
            raise ServiceError("Invalid storage key", 500, "STORAGE")
        return path

    def save(self, data: bytes, mime: str) -> str:
        key = secrets.token_hex(16) + EXTENSIONS[mime]
        path = self._path(key)
        temp = path.with_suffix(path.suffix + ".part")
        with open(temp, "xb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
        return key

    def read(self, key: str) -> bytes:
        return self._path(key).read_bytes()


def storage(request: Request) -> AudioStorage:
    state = request.app.state
    if not hasattr(state, "audio_storage"):
        state.audio_storage = AudioStorage(Path(state.settings.storage_dir) / "audio")
    return state.audio_storage


def sniff(data: bytes) -> str | None:
    """The real audio type from the file's own bytes (the browser's claim is not trusted)."""
    if data[:4] == b"\x1aE\xdf\xa3":
        return "audio/webm"
    if data[:4] == b"OggS":
        return "audio/ogg"
    if data[4:8] == b"ftyp":
        return "audio/mp4"
    if data[:4] == b"RIFF" and data[8:12] == b"WAVE":
        return "audio/wav"
    if data[:3] == b"ID3" or (len(data) > 1 and data[0] == 0xFF and data[1] & 0xE0 == 0xE0):
        return "audio/mpeg"
    return None


def _read(upload: UploadFile | None, duration_s: float | None) -> tuple[bytes, str]:
    if upload is None or not upload.filename:
        raise ServiceError("Record a voice note first.", 422, "AUDIO_REQUIRED")
    data = upload.file.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise ServiceError(f"The voice note is larger than {MAX_BYTES // (1024 * 1024)} MB.", 413, "FILE_TOO_LARGE")
    if len(data) < MIN_BYTES:
        raise ServiceError("The recording is empty. Record again.", 422, "AUDIO_EMPTY")
    mime = sniff(data)
    if mime is None:
        raise ServiceError("This file is not a supported voice recording.", 422, "AUDIO_UNSUPPORTED")
    if duration_s is not None and not 0 < duration_s <= MAX_SECONDS + 5:
        raise ServiceError(f"A voice note can be up to {MAX_SECONDS // 60} minutes long.", 422, "AUDIO_TOO_LONG")
    return data, mime


def _store(request, session, actor: Actor, data: bytes, mime: str, duration_s: float | None, **links) -> AudioNoteRow:
    row = AudioNoteRow(note_id=new_id("AUD", 6), uploaded_by=actor.user_id, storage_key=storage(request).save(data, mime),
                       mime_type=mime, size_bytes=len(data), duration_s=round(duration_s, 1) if duration_s else None,
                       sha256=hashlib.sha256(data).hexdigest(), received_at=utcnow(), **links)
    session.add(row)
    return row


def note_view(n: AudioNoteRow, url: str) -> dict:
    return {"note_id": n.note_id, "kind": n.kind, "duration_s": n.duration_s, "size_bytes": n.size_bytes,
            "mime_type": n.mime_type, "received_at": iso(n.received_at), "attempt": n.attempt,
            "completion_id": n.completion_id, "url": url}


def sos_notes(session, sos_id: str, *, token: str | None = None) -> list[dict]:
    rows = session.scalars(select(AudioNoteRow).where(AudioNoteRow.sos_id == sos_id).order_by(AudioNoteRow.received_at))
    base = f"/api/v1/women/share/{token}/audio-notes" if token else f"/api/v1/women/sos/{sos_id}/audio-notes"
    return [note_view(n, f"{base}/{n.note_id}") for n in rows]


def task_notes(session, task_id: str, *, completion_id: str | None = None) -> list[dict]:
    q = select(AudioNoteRow).where(AudioNoteRow.task_id == task_id)
    if completion_id:
        q = q.where(AudioNoteRow.completion_id == completion_id)
    rows = session.scalars(q.order_by(AudioNoteRow.received_at))
    return [note_view(n, f"/api/v1/tasks/{task_id}/audio-notes/{n.note_id}") for n in rows]


def _audio_response(request, n: AudioNoteRow) -> Response:
    return Response(storage(request).read(n.storage_key), media_type=n.mime_type,
                    headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"})


# ------------------------------------------------------------------ SOS
def _own_sos(session, actor: Actor, sos_id: str) -> SosRow:
    if actor.role != "CITIZEN":
        raise ServiceError("Women's safety is part of the citizen account.", 403, "FORBIDDEN")
    sos = session.get(SosRow, sos_id)
    if sos is None or sos.user_id != actor.user_id:
        raise ServiceError("SOS not found.", 404, "NOT_FOUND")
    return sos


@router.post("/women/sos/{sos_id}/audio-notes", status_code=201)
def add_sos_note(sos_id: str, request: Request, audio: UploadFile | None = File(default=None),
                 duration_s: float | None = Form(default=None), actor: Actor = Depends(get_actor),
                 session: Session = Depends(get_session)):
    sos = _own_sos(session, actor, sos_id)
    if sos.status != "ACTIVE":
        raise ServiceError("This SOS has ended. A voice note can only be added while it is active.", 409, "SOS_ENDED")
    count = session.scalar(select(func.count()).select_from(AudioNoteRow).where(AudioNoteRow.sos_id == sos_id)) or 0
    if count >= MAX_PER_SOS:
        raise ServiceError(f"Up to {MAX_PER_SOS} voice notes can be added to one SOS.", 409, "TOO_MANY_NOTES")
    data, mime = _read(audio, duration_s)
    row = _store(request, session, actor, data, mime, duration_s, kind="SOS", sos_id=sos_id)
    from geosatya.kavach.women import _event   # SOS history is kept in its own private event log
    _event(session, sos_id, "VOICE_NOTE", note_id=row.note_id, duration_s=row.duration_s)
    session.commit()
    return {"note": note_view(row, f"/api/v1/women/sos/{sos_id}/audio-notes/{row.note_id}"),
            "notes": sos_notes(session, sos_id)}


@router.get("/women/sos/{sos_id}/audio-notes/{note_id}")
def play_sos_note(sos_id: str, note_id: str, request: Request, actor: Actor = Depends(get_actor),
                  session: Session = Depends(get_session)):
    _own_sos(session, actor, sos_id)
    n = session.get(AudioNoteRow, note_id)
    if n is None or n.sos_id != sos_id:
        raise ServiceError("Voice note not found.", 404, "NOT_FOUND")
    return _audio_response(request, n)


@router.get("/women/share/{token}/audio-notes/{note_id}")
def play_shared_note(token: str, note_id: str, request: Request, session: Session = Depends(get_session)):
    """A trusted ally's private link: the voice note plays only while the SOS is active."""
    alert = session.scalar(select(SosNotificationRow).where(SosNotificationRow.token == token[:60], SosNotificationRow.kind == "ALERT"))
    sos = session.get(SosRow, alert.sos_id) if alert else None
    n = session.get(AudioNoteRow, note_id)
    if sos is None or n is None or n.sos_id != sos.sos_id or sos.status != "ACTIVE":
        raise ServiceError("Voice note not found.", 404, "NOT_FOUND")
    return _audio_response(request, n)


# ------------------------------------------------------------------ task completion
@router.post("/tasks/{task_id}/audio-notes", status_code=201)
def add_task_note(task_id: str, request: Request, audio: UploadFile | None = File(default=None),
                  duration_s: float | None = Form(default=None), completion_id: str | None = Form(default=None),
                  actor: Actor = Depends(get_actor), session: Session = Depends(get_session)):
    if actor.role != "WORKER":
        raise ServiceError("Only the assigned field worker can add a voice note to this task.", 403, "FORBIDDEN")
    task = load_task(session, task_id, actor)
    if task.status not in ("IN_PROGRESS", "AWAITING_VERIFICATION"):
        raise ServiceError("Voice notes are added while working on the task or when submitting it.", 409, "TASK_NOT_ACTIVE")
    if completion_id:
        c = session.get(CompletionRow, completion_id)
        if c is None or c.task_id != task_id or c.worker_id != actor.user_id:
            raise ServiceError("That completion is not part of this task.", 404, "NOT_FOUND")
    count = session.scalar(select(func.count()).select_from(AudioNoteRow)
                           .where(AudioNoteRow.task_id == task_id, AudioNoteRow.attempt == task.attempt)) or 0
    if count >= MAX_PER_ATTEMPT:
        raise ServiceError(f"Up to {MAX_PER_ATTEMPT} voice notes can be added to one attempt.", 409, "TOO_MANY_NOTES")
    data, mime = _read(audio, duration_s)
    row = _store(request, session, actor, data, mime, duration_s, kind="COMPLETION", task_id=task_id,
                 incident_id=task.incident_id, completion_id=completion_id, attempt=task.attempt)
    audit(session, actor, "VOICE_NOTE_ADDED", task.incident_id, task_id=task_id, note_id=row.note_id,
          completion_id=completion_id, attempt=task.attempt, duration_s=row.duration_s)
    session.commit()
    return {"note": note_view(row, f"/api/v1/tasks/{task_id}/audio-notes/{row.note_id}"),
            "notes": task_notes(session, task_id)}


@router.get("/tasks/{task_id}/audio-notes")
def list_task_notes(task_id: str, actor: Actor = Depends(get_actor), session: Session = Depends(get_session)):
    load_task(session, task_id, actor)
    return task_notes(session, task_id)


@router.get("/tasks/{task_id}/audio-notes/{note_id}")
def play_task_note(task_id: str, note_id: str, request: Request, actor: Actor = Depends(get_actor),
                   session: Session = Depends(get_session)):
    task = load_task(session, task_id, actor)   # the worker on the task, or a supervisor of its workspace
    n = session.get(AudioNoteRow, note_id)
    if n is None or n.task_id != task.task_id:
        raise ServiceError("Voice note not found.", 404, "NOT_FOUND")
    incident = session.get(IncidentRow, task.incident_id)
    if incident is None:
        raise ServiceError("Voice note not found.", 404, "NOT_FOUND")
    return _audio_response(request, n)
