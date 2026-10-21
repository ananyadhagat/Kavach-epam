import logging
import math
import socket
from typing import Any

import asyncpg
from fastapi import Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError, InterfaceError, OperationalError
from sqlalchemy.exc import TimeoutError as SQLAlchemyTimeoutError

logger = logging.getLogger(__name__)


def json_safe(value: Any) -> Any:
    # JSON has no NaN/Infinity. FastAPI echoes rejected input back in 422
    # bodies, so a raw NaN in a request used to crash the error response
    # with HTTP 500. Non-finite floats are reported as strings instead.
    if isinstance(value, float) and not math.isfinite(value):
        return str(value)

    if isinstance(value, dict):
        return {key: json_safe(item) for key, item in value.items()}

    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]

    return value


# Connection-level failures only. Other OSErrors (e.g. disk errors while
# saving evidence) are not database outages and remain HTTP 500.
DATABASE_UNAVAILABLE_ERRORS: tuple[type[Exception], ...] = (
    OperationalError,
    InterfaceError,
    SQLAlchemyTimeoutError,
    ConnectionError,
    TimeoutError,
    socket.gaierror,
    asyncpg.PostgresConnectionError,
    asyncpg.CannotConnectNowError,
)


async def database_unavailable_handler(
    request: Request,
    exc: Exception,
) -> JSONResponse:
    logger.error("Database unavailable: %s", type(exc).__name__)
    return JSONResponse(
        status_code=503,
        content={"detail": "Database unavailable. Please retry later."},
    )


async def integrity_error_handler(
    request: Request,
    exc: IntegrityError,
) -> JSONResponse:
    # Constraint violations not handled by a service, e.g. a concurrent
    # duplicate. The transaction has already been rolled back.
    logger.warning("Integrity error: %s", type(exc.orig).__name__)
    return JSONResponse(
        status_code=409,
        content={"detail": "Request conflicts with existing data."},
    )


async def request_validation_handler(
    request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={"detail": json_safe(jsonable_encoder(exc.errors()))},
    )
