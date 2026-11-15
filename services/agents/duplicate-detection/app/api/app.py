"""Application factory for the KAVACH HTTP edge.

The default application wires the in-memory repository, which starts empty. A
deployment that needs real candidates (or a synthetic demo set) constructs its
own :class:`DuplicateDetectionService` and passes it to :func:`create_app`.

Consolidation is additive and opt-in. When a
:class:`~app.services.consolidation_service.ConsolidationService` is supplied,
its routes are mounted under ``/internal/v1/consolidation`` and the read-only
``/check`` route reads the same persistent complaint store. When it is omitted,
the application behaves exactly as before: an empty in-memory M3 service.
"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.api.consolidation_router import (
    INVALID_PAYLOAD_CODE as CONSOLIDATION_INVALID_PAYLOAD_CODE,
)
from app.api.consolidation_router import router as consolidation_router
from app.api.dependencies import DetailedDetectionService
from app.api.router import INVALID_PAYLOAD_CODE, router
from app.repositories.in_memory import InMemoryComplaintRepository
from app.services.consolidation_service import ConsolidationService
from app.services.detection_service import DuplicateDetectionService

__version__ = "0.3.0"

_CONSOLIDATION_PREFIX = "/internal/v1/consolidation"


def create_app(
    service: DetailedDetectionService | None = None,
    *,
    consolidation_service: ConsolidationService | None = None,
) -> FastAPI:
    """Build the FastAPI application.

    Parameters
    ----------
    service:
        Optional duplicate-detection service. When omitted and a consolidation
        service is supplied, the M3 route reads persisted complaints through
        the consolidation service's database. When both are omitted, a service
        with an empty in-memory repository is created.
    consolidation_service:
        Optional consolidation service. Its router is mounted only when it is
        supplied, so deployments without database configuration keep the
        original in-memory surface.
    """

    app = FastAPI(
        title="KAVACH Duplicate Detection Agent",
        version=__version__,
        description=(
            "M3 duplicate detection over the Agent 1 incident handoff payload, "
            "returning the Agent 3 response contract, plus persistent "
            "consolidation of confirmed duplicates."
        ),
    )

    if service is None:
        if consolidation_service is not None:
            service = consolidation_service.build_detection_service()
        else:
            service = DuplicateDetectionService(
                repository=InMemoryComplaintRepository()
            )

    app.state.duplicate_detection_service = service
    app.state.consolidation_service = consolidation_service
    app.include_router(router)
    if consolidation_service is not None:
        app.include_router(consolidation_router)

    @app.exception_handler(RequestValidationError)
    async def _invalid_request(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        # Malformed JSON and missing bodies are rejected before the route can
        # adapt them. Keep the same uniform 422 envelope the route uses, with
        # the code that matches the mounted surface.
        if request.url.path.startswith(_CONSOLIDATION_PREFIX):
            code = CONSOLIDATION_INVALID_PAYLOAD_CODE
            message = "The request body is not a valid complaint payload."
        else:
            code = INVALID_PAYLOAD_CODE
            message = (
                "The request body is not a valid Agent 1 incident payload."
            )
        return JSONResponse(
            status_code=422,
            content={"detail": {"code": code, "message": message}},
        )

    return app


__all__ = ["create_app"]
