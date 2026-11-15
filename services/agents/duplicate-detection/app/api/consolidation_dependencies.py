"""FastAPI dependencies for the consolidation API."""

from __future__ import annotations

from fastapi import HTTPException, Request, status

from app.services.consolidation_service import ConsolidationService


def get_consolidation_service(request: Request) -> ConsolidationService:
    """Return the consolidation service configured on application state.

    The router is only installed when a service was supplied to
    :func:`app.api.app.create_app`, so this is a defensive check for
    misconfigured deployments rather than the normal path.
    """

    service = getattr(request.app.state, "consolidation_service", None)
    if service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "DATABASE_UNAVAILABLE",
                "message": "Consolidation storage is not configured.",
            },
        )
    return service


__all__ = ["get_consolidation_service"]
