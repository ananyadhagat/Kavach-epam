"""HTTP route for the M3 duplicate-detection check.

The route is a thin edge:

1. accept the Agent 1 handoff payload;
2. adapt it with :func:`app.adapters.incident_payload.to_complaint`;
3. run the unchanged orchestration service via ``check_detailed``;
4. map the internal result with :func:`app.api.mapper.to_m3_response`.

Business outcomes (including partial and failed candidate retrieval) are
HTTP 200, as required by the Agent 3 contract. HTTP errors are reserved for
invalid requests and for failures that produced no trustworthy result at all.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Body, Depends
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from app.adapters.incident_payload import IncidentPayloadError, to_complaint
from app.api.dependencies import DetailedDetectionService, get_service
from app.api.mapper import to_m3_response
from app.schemas.m3_response import M3DuplicateCheckResponse

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/internal/v1/duplicate-detection",
    tags=["duplicate-detection"],
)

INVALID_PAYLOAD_CODE = "INVALID_INCIDENT_PAYLOAD"
TIMEOUT_CODE = "DUPLICATE_CHECK_TIMEOUT"
INTERNAL_ERROR_CODE = "INTERNAL_ERROR"


def _error_body(code: str, message: str) -> dict[str, Any]:
    """The uniform HTTP error envelope (never an Agent 3 result body)."""

    return {"detail": {"code": code, "message": message}}


def _validation_message(exc: ValidationError) -> str:
    """Summarise Pydantic errors without echoing submitted values."""

    problems: list[str] = []
    for error in exc.errors(include_url=False):
        location = ".".join(str(part) for part in error.get("loc", ())) or "payload"
        problems.append(f"{location}: {error.get('msg', 'invalid value')}")
    return "incident payload failed validation: " + "; ".join(problems)


@router.post(
    "/check",
    response_model=M3DuplicateCheckResponse,
    responses={
        422: {"description": "Invalid Agent 1 incident payload"},
        500: {"description": "Internal duplicate-detection failure"},
        504: {"description": "Duplicate-detection timeout"},
    },
)
def check_duplicate(
    payload: Any = Body(...),
    service: DetailedDetectionService = Depends(get_service),
) -> M3DuplicateCheckResponse | JSONResponse:
    """Run one duplicate check and return the Agent 3 response contract."""

    try:
        complaint = to_complaint(payload)
    except IncidentPayloadError as exc:
        return JSONResponse(
            status_code=422,
            content=_error_body(INVALID_PAYLOAD_CODE, str(exc)),
        )
    except ValidationError as exc:
        return JSONResponse(
            status_code=422,
            content=_error_body(INVALID_PAYLOAD_CODE, _validation_message(exc)),
        )

    try:
        result = service.check_detailed(complaint)
    except TimeoutError:
        logger.warning("duplicate check timed out", exc_info=True)
        return JSONResponse(
            status_code=504,
            content=_error_body(
                TIMEOUT_CODE,
                "The duplicate check timed out before a result was available.",
            ),
        )
    except Exception:
        # Deliberately broad: an unexpected edge failure must never become a
        # fabricated NEW/REVIEW response. The stack trace stays in the log.
        logger.exception("duplicate check failed unexpectedly")
        return JSONResponse(
            status_code=500,
            content=_error_body(
                INTERNAL_ERROR_CODE,
                "The duplicate check failed before a result was available.",
            ),
        )

    return to_m3_response(result)


__all__ = [
    "INTERNAL_ERROR_CODE",
    "INVALID_PAYLOAD_CODE",
    "TIMEOUT_CODE",
    "check_duplicate",
    "router",
]
