"""HTTP routes for complaint consolidation.

These routes are additive. The existing M3 check route and its wire contract are
unchanged. Business outcomes that are successfully persisted return HTTP 200
(for reads) or 201 (for ingestion); HTTP errors are reserved for invalid
requests, conflicts, and infrastructure failures.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from typing import Any, TypeVar

from fastapi import APIRouter, Body, Depends, Header, Query, Response
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from app.adapters.incident_payload import IncidentPayloadError, to_complaint
from app.api.consolidation_dependencies import get_consolidation_service
from app.schemas.consolidation import (
    ComplaintDetailResponse,
    ConsolidationResult,
    GroupDetailResponse,
    GroupStatus,
    PaginatedGroups,
    PaginatedReviews,
    ReviewStatus,
)
from app.services.consolidation_errors import ConsolidationError
from app.services.consolidation_service import ConsolidationService

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/internal/v1/consolidation",
    tags=["consolidation"],
)

INVALID_PAYLOAD_CODE = "INVALID_COMPLAINT_PAYLOAD"
INVALID_IDEMPOTENCY_KEY_CODE = "INVALID_IDEMPOTENCY_KEY"
TIMEOUT_CODE = "DUPLICATE_CHECK_TIMEOUT"
INTERNAL_ERROR_CODE = "INTERNAL_ERROR"

#: Printable ASCII without whitespace, 1-128 characters.
_IDEMPOTENCY_KEY_PATTERN = re.compile(r"^[\x21-\x7E]{1,128}$")

_T = TypeVar("_T")


def _error_body(code: str, message: str) -> dict[str, Any]:
    return {"detail": {"code": code, "message": message}}


def _validation_message(exc: ValidationError) -> str:
    problems: list[str] = []
    for error in exc.errors(include_url=False):
        location = ".".join(str(part) for part in error.get("loc", ())) or "payload"
        problems.append(f"{location}: {error.get('msg', 'invalid value')}")
    return "complaint payload failed validation: " + "; ".join(problems)


def _normalise_idempotency_key(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    if not _IDEMPOTENCY_KEY_PATTERN.fullmatch(stripped):
        return None
    return stripped


def _handle(operation: Callable[[], _T]) -> _T | JSONResponse:
    """Run a service call and translate domain/infrastructure failures."""

    try:
        return operation()
    except ConsolidationError as exc:
        return JSONResponse(
            status_code=exc.http_status,
            content=_error_body(exc.code, exc.message),
        )
    except TimeoutError:
        logger.warning("consolidation duplicate check timed out", exc_info=True)
        return JSONResponse(
            status_code=504,
            content=_error_body(
                TIMEOUT_CODE,
                "The duplicate check timed out before a result was available.",
            ),
        )
    except Exception:
        logger.exception("consolidation request failed unexpectedly")
        return JSONResponse(
            status_code=500,
            content=_error_body(
                INTERNAL_ERROR_CODE,
                "The consolidation request failed before a result was "
                "available.",
            ),
        )


@router.post(
    "/complaints",
    response_model=ConsolidationResult,
    status_code=201,
    responses={
        409: {"description": "Idempotency or consolidation conflict"},
        422: {"description": "Invalid complaint payload or idempotency key"},
        500: {"description": "Internal failure"},
        503: {"description": "Database unavailable"},
    },
)
def ingest_complaint(
    response: Response,
    payload: Any = Body(...),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    service: ConsolidationService = Depends(get_consolidation_service),
) -> ConsolidationResult | JSONResponse:
    """Store one complaint, run M3, and consolidate or queue a review."""

    normalised_key = _normalise_idempotency_key(idempotency_key)
    if normalised_key is None:
        return JSONResponse(
            status_code=422,
            content=_error_body(
                INVALID_IDEMPOTENCY_KEY_CODE,
                "Idempotency-Key is required and must be 1-128 printable "
                "ASCII characters without whitespace.",
            ),
        )

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

    result = _handle(
        lambda: service.ingest(complaint, normalised_key)
    )
    if isinstance(result, JSONResponse):
        return result

    if result.idempotent_replay:
        response.headers["Idempotent-Replay"] = "true"
    return result


@router.get(
    "/complaints/{complaint_id}",
    response_model=ComplaintDetailResponse,
    responses={
        404: {"description": "Complaint not found"},
        409: {"description": "Complaint has no consolidation state"},
        503: {"description": "Database unavailable"},
    },
)
def get_complaint(
    complaint_id: str,
    service: ConsolidationService = Depends(get_consolidation_service),
) -> ComplaintDetailResponse | JSONResponse:
    """Return a stored complaint and its consolidation state."""

    return _handle(lambda: service.get_complaint_detail(complaint_id))


@router.get(
    "/groups",
    response_model=PaginatedGroups,
    responses={503: {"description": "Database unavailable"}},
)
def list_groups(
    status: GroupStatus | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    service: ConsolidationService = Depends(get_consolidation_service),
) -> PaginatedGroups | JSONResponse:
    """List consolidation groups for Supervisor/Dispatch consumption."""

    return _handle(
        lambda: service.list_groups(
            status=status.value if status is not None else None,
            limit=limit,
            offset=offset,
        )
    )


@router.get(
    "/groups/{group_id}",
    response_model=GroupDetailResponse,
    responses={
        404: {"description": "Group not found"},
        503: {"description": "Database unavailable"},
    },
)
def get_group(
    group_id: str,
    service: ConsolidationService = Depends(get_consolidation_service),
) -> GroupDetailResponse | JSONResponse:
    """Return a group, its canonical primary, and its duplicate members."""

    return _handle(lambda: service.get_group_detail(group_id))


@router.get(
    "/review-queue",
    response_model=PaginatedReviews,
    responses={503: {"description": "Database unavailable"}},
)
def get_review_queue(
    status: ReviewStatus | None = Query(default=ReviewStatus.OPEN),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    service: ConsolidationService = Depends(get_consolidation_service),
) -> PaginatedReviews | JSONResponse:
    """Return complaints that M3 could not safely link."""

    return _handle(
        lambda: service.list_review_queue(
            status=status.value if status is not None else None,
            limit=limit,
            offset=offset,
        )
    )


__all__ = [
    "INTERNAL_ERROR_CODE",
    "INVALID_IDEMPOTENCY_KEY_CODE",
    "INVALID_PAYLOAD_CODE",
    "TIMEOUT_CODE",
    "router",
]
