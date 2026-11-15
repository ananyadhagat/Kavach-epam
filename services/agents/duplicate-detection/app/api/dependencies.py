"""FastAPI dependencies for the M3 HTTP edge."""

from __future__ import annotations

from typing import Protocol, cast

from fastapi import Request

from app.schemas.complaint import Complaint
from app.services.detection_service import DetectionResult, DuplicateDetectionService


class DetailedDetectionService(Protocol):
    """The single service method the HTTP edge depends on.

    Keeping the dependency narrow lets tests inject a deterministic double
    without subclassing the concrete service. Production always stores a
    :class:`DuplicateDetectionService` in ``app.state``.
    """

    def check_detailed(self, complaint: Complaint) -> DetectionResult: ...


def get_service(request: Request) -> DetailedDetectionService:
    """Return the service configured on the application state.

    :func:`app.api.app.create_app` sets this attribute so the repository and
    comparators can be injected once, at startup, without rebuilding routes.
    """

    service = getattr(request.app.state, "duplicate_detection_service", None)
    if service is None:
        raise RuntimeError(
            "duplicate detection service is not configured on app.state"
        )
    return cast(DuplicateDetectionService, service)


__all__ = ["DetailedDetectionService", "get_service"]
