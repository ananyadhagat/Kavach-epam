"""POST /api/v1/incidents - citizen complaint intake (multipart: text + optional images + location)."""
from __future__ import annotations

import hmac
import threading
import time
import uuid
from collections import deque

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Request, UploadFile
from pydantic import ValidationError

from kavach.errors import (
    IdempotencyConflictError,
    IncidentProcessingError,
    LLMRequestRejectedError,
    LLMUnavailableError,
    RepositoryError,
)
from kavach.schemas.incident_intelligence import IncidentSubmission, StructuredIncidentRecord
from kavach.schemas.location import Coordinates, DeviceLocation
from kavach.services.incident_intelligence.handoff import build_duplicate_detection_request
from kavach.services.incident_intelligence.orchestrator import IncidentIntelligenceOrchestrator, UploadedFile

router = APIRouter(prefix="/api/v1/incidents", tags=["incidents"])


# ------------------------------------------------------------------ access control
class RateLimiter:
    """In-process sliding window per client key. Prototype-level: use the gateway/Redis in production."""

    def __init__(self, per_minute: int):
        self.per_minute = per_minute
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        if self.per_minute <= 0:
            return True
        now = time.monotonic()
        with self._lock:
            q = self._hits.setdefault(key, deque())
            while q and now - q[0] > 60:
                q.popleft()
            if len(q) >= self.per_minute:
                return False
            q.append(now)
            return True


def enforce_rate_limit(request: Request) -> None:
    limiter: RateLimiter | None = getattr(request.app.state, "rate_limiter", None)
    client = request.client.host if request.client else "unknown"
    if limiter is not None and not limiter.allow(client):
        raise HTTPException(429, detail={"code": "RATE_LIMITED", "message": "Too many complaints; please wait a minute."},
                            headers={"Retry-After": "60"})


def require_read_access(request: Request, x_api_key: str | None = Header(default=None)) -> None:
    """Incident records contain precise coordinates and citizen text: never public.
    Stop-gap until the gateway's JWT + RBAC dependency is wired in: a shared key (KAVACH_READ_API_KEY)."""
    expected: str | None = getattr(request.app.state, "read_api_key", None)
    if not expected:
        raise HTTPException(403, detail={"code": "READ_ACCESS_NOT_CONFIGURED",
                                         "message": "Set KAVACH_READ_API_KEY (or wire gateway auth) to enable reads."})
    if not x_api_key or not hmac.compare_digest(x_api_key, expected):
        raise HTTPException(401, detail={"code": "UNAUTHORIZED", "message": "Valid X-API-Key header required."})


# ------------------------------------------------------------------ helpers
def _opt_float(name: str, raw: str | None) -> float | None:
    if raw is None or raw.strip() == "":
        return None
    try:
        return float(raw)
    except ValueError:
        raise HTTPException(422, detail=[{"loc": ["form", name], "msg": "must be a number"}])


def _pair(lat: float | None, lon: float | None, prefix: str) -> bool:
    if (lat is None) != (lon is None):
        raise HTTPException(422, detail=[{"loc": ["form", f"{prefix}_latitude"],
                                          "msg": "latitude and longitude must be provided together"}])
    return lat is not None


def _errors(exc: ValidationError) -> list[dict]:
    return [{"loc": [str(p) for p in e["loc"]], "msg": e["msg"]} for e in exc.errors()]


def _orchestrator(request: Request) -> IncidentIntelligenceOrchestrator:
    return request.app.state.orchestrator


def _read_uploads(images: list[UploadFile], max_images: int, max_bytes: int) -> list[UploadedFile]:
    """Read at most max_images files (each capped at max_bytes + 1). Extra files are NOT read into
    memory; they are passed as empty placeholders so the orchestrator records TOO_MANY_IMAGES."""
    uploads: list[UploadedFile] = []
    for i, f in enumerate(images):
        if i < max_images:
            uploads.append(UploadedFile(f.filename, f.file.read(max_bytes + 1)))
        else:
            uploads.append(UploadedFile(f.filename, b""))
    return uploads


# ------------------------------------------------------------------ routes
@router.post("", response_model=StructuredIncidentRecord, status_code=201,
             dependencies=[Depends(enforce_rate_limit)])

def submit_incident(
    request: Request,
    complaint_text: str | None = Form(None, max_length=5000),
    selected_latitude: str | None = Form(None),
    selected_longitude: str | None = Form(None),
    device_latitude: str | None = Form(None),
    device_longitude: str | None = Form(None),
    device_accuracy_meters: str | None = Form(None),
    device_observed_at: str | None = Form(None),
    voice_transcript: str | None = Form(None, max_length=5000),
    images: list[UploadFile] = File(default=[]),
    x_request_id: str | None = Header(default=None),
) -> StructuredIncidentRecord:
    orch = _orchestrator(request)

    try:
        s_lat = _opt_float("selected_latitude", selected_latitude)
        s_lon = _opt_float("selected_longitude", selected_longitude)
        d_lat = _opt_float("device_latitude", device_latitude)
        d_lon = _opt_float("device_longitude", device_longitude)
        acc = _opt_float("device_accuracy_meters", device_accuracy_meters)

        complaint = (complaint_text or "").strip()
        transcript = (voice_transcript or "").strip()

        if not complaint and not transcript:
            raise HTTPException(
                status_code=422,
                detail="Provide either complaint text or a voice transcript.",
            )

        pin = (
            Coordinates(latitude=s_lat, longitude=s_lon)
            if _pair(s_lat, s_lon, "selected")
            else None
        )

        device = None
        if _pair(d_lat, d_lon, "device"):
            device = DeviceLocation(
                latitude=d_lat,
                longitude=d_lon,
                accuracy_meters=acc,
                observed_at=device_observed_at or None,
            )

        submission = IncidentSubmission(
            request_id=x_request_id or str(uuid.uuid4()),
            complaint_text=complaint or None,
            selected_incident_location=pin,
            device_location=device,
            voice_transcript=transcript or None,
        )

    except ValidationError as exc:
        raise HTTPException(422, detail=_errors(exc))

    uploads = _read_uploads(images, orch.max_images, orch.max_image_bytes)

    try:
        return orch.process(submission, uploads)

    except LLMUnavailableError:
        raise HTTPException(
            503,
            detail={
                "code": "LLM_UNAVAILABLE",
                "message": "Analysis temporarily unavailable; please retry.",
            },
            headers={"Retry-After": "30"},
        )

    except LLMRequestRejectedError:
        raise HTTPException(
            502,
            detail={
                "code": "LLM_REQUEST_REJECTED",
                "message": "Analysis service rejected the request; operators have been alerted.",
            },
        )

    except IncidentProcessingError:
        raise HTTPException(
            502,
            detail={
                "code": "MODEL_OUTPUT_INVALID",
                "message": "Could not produce a valid incident record; flagged for retry/review.",
            },
        )

    except IdempotencyConflictError:
        raise HTTPException(
            409,
            detail={
                "code": "REQUEST_ID_REUSED",
                "message": "This X-Request-ID was already used for a different complaint.",
            },
        )

    except RepositoryError:
        raise HTTPException(
            503,
            detail={
                "code": "STORAGE_UNAVAILABLE",
                "message": "Complaint could not be saved; please retry.",
            },
            headers={"Retry-After": "30"},
        )

def _get_or_404(request: Request, incident_id: str) -> StructuredIncidentRecord:
    try:
        record = _orchestrator(request).repository.get(incident_id)
    except RepositoryError:
        raise HTTPException(503, detail={"code": "STORAGE_UNAVAILABLE", "message": "Please retry."},
                            headers={"Retry-After": "30"})
    if record is None:
        raise HTTPException(404, detail="Incident not found")
    return record


@router.get("/{incident_id}", response_model=StructuredIncidentRecord,
            dependencies=[Depends(require_read_access)])
def get_incident(incident_id: str, request: Request) -> StructuredIncidentRecord:
    return _get_or_404(request, incident_id)


@router.get("/{incident_id}/duplicate-detection-request", dependencies=[Depends(require_read_access)])
def get_duplicate_detection_request(incident_id: str, request: Request) -> dict:
    """The exact payload Agent 1 hands to the Duplicate Detection Agent (draft contract, see handoff.py)."""
    return build_duplicate_detection_request(_get_or_404(request, incident_id))
