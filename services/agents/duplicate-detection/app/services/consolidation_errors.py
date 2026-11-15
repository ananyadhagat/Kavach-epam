"""Domain errors raised by the consolidation service.

Errors carry a machine-readable code and the HTTP status the edge should use.
The service layer stays transport-free; the router only translates these
objects into the uniform error envelope.
"""

from __future__ import annotations

#: Stored complaint already exists under a different idempotency key.
COMPLAINT_ALREADY_EXISTS = "COMPLAINT_ALREADY_EXISTS"

#: Idempotency key was reused with a different payload.
IDEMPOTENCY_KEY_REUSED = "IDEMPOTENCY_KEY_REUSED"

#: M3 matched an incident that is not stored at all.
MATCHED_PRIMARY_NOT_FOUND = "MATCHED_PRIMARY_NOT_FOUND"

#: M3 matched a stored complaint that has no consolidation group.
MATCHED_PRIMARY_NOT_CONSOLIDATED = "MATCHED_PRIMARY_NOT_CONSOLIDATED"

#: The target group is closed and accepts no new duplicates.
GROUP_CLOSED = "GROUP_CLOSED"

#: Requested complaint does not exist.
COMPLAINT_NOT_FOUND = "COMPLAINT_NOT_FOUND"

#: Requested group does not exist.
GROUP_NOT_FOUND = "GROUP_NOT_FOUND"

#: A stored complaint has neither a link nor a review.
COMPLAINT_NOT_CONSOLIDATED = "COMPLAINT_NOT_CONSOLIDATED"

#: Database could not be reached or a query failed.
DATABASE_UNAVAILABLE = "DATABASE_UNAVAILABLE"

#: Unexpected internal failure.
INTERNAL_ERROR = "INTERNAL_ERROR"


class ConsolidationError(Exception):
    """A domain or infrastructure failure with a stable code.

    Parameters
    ----------
    code:
        Upper-snake machine-readable identifier.
    message:
        Human-readable explanation safe to return to an internal caller.
    http_status:
        Suggested HTTP status for the API edge.
    """

    def __init__(
        self,
        code: str,
        message: str,
        *,
        http_status: int = 409,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.message


def complaint_already_exists(complaint_id: str) -> ConsolidationError:
    return ConsolidationError(
        COMPLAINT_ALREADY_EXISTS,
        f"A complaint with id {complaint_id!r} is already stored. Reuse the "
        "original Idempotency-Key to replay its result.",
    )


def idempotency_key_reused() -> ConsolidationError:
    return ConsolidationError(
        IDEMPOTENCY_KEY_REUSED,
        "The Idempotency-Key was already used with a different payload.",
    )


def matched_primary_not_found(matched_incident_id: str) -> ConsolidationError:
    return ConsolidationError(
        MATCHED_PRIMARY_NOT_FOUND,
        "M3 returned a matched incident that is not stored "
        f"({matched_incident_id!r}).",
    )


def matched_primary_not_consolidated(
    matched_incident_id: str,
) -> ConsolidationError:
    return ConsolidationError(
        MATCHED_PRIMARY_NOT_CONSOLIDATED,
        "M3 returned a matched incident that has no consolidation group "
        f"({matched_incident_id!r}).",
    )


def group_closed(group_id: str) -> ConsolidationError:
    return ConsolidationError(
        GROUP_CLOSED,
        f"Consolidation group {group_id!r} is closed.",
    )


def complaint_not_found(complaint_id: str) -> ConsolidationError:
    return ConsolidationError(
        COMPLAINT_NOT_FOUND,
        f"Complaint {complaint_id!r} was not found.",
        http_status=404,
    )


def group_not_found(group_id: str) -> ConsolidationError:
    return ConsolidationError(
        GROUP_NOT_FOUND,
        f"Consolidation group {group_id!r} was not found.",
        http_status=404,
    )


def complaint_not_consolidated(complaint_id: str) -> ConsolidationError:
    return ConsolidationError(
        COMPLAINT_NOT_CONSOLIDATED,
        f"Complaint {complaint_id!r} has no consolidation link or review.",
    )


def database_unavailable() -> ConsolidationError:
    return ConsolidationError(
        DATABASE_UNAVAILABLE,
        "The consolidation database is unavailable.",
        http_status=503,
    )


def internal_error() -> ConsolidationError:
    return ConsolidationError(
        INTERNAL_ERROR,
        "The consolidation request failed before a result was available.",
        http_status=500,
    )


__all__ = [
    "COMPLAINT_ALREADY_EXISTS",
    "COMPLAINT_NOT_CONSOLIDATED",
    "COMPLAINT_NOT_FOUND",
    "ConsolidationError",
    "DATABASE_UNAVAILABLE",
    "GROUP_CLOSED",
    "GROUP_NOT_FOUND",
    "IDEMPOTENCY_KEY_REUSED",
    "INTERNAL_ERROR",
    "MATCHED_PRIMARY_NOT_CONSOLIDATED",
    "MATCHED_PRIMARY_NOT_FOUND",
    "complaint_already_exists",
    "complaint_not_consolidated",
    "complaint_not_found",
    "database_unavailable",
    "group_closed",
    "group_not_found",
    "idempotency_key_reused",
    "internal_error",
    "matched_primary_not_consolidated",
    "matched_primary_not_found",
]
