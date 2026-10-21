"""Domain errors mapped to controlled HTTP responses by the API layer."""
from __future__ import annotations


class KavachError(Exception):
    """Base class for controlled, expected failures."""


class LLMUnavailableError(KavachError):
    """Gemini timed out, was rate-limited, or is not configured. Retryable; never fabricate output."""


class LLMRequestRejectedError(KavachError):
    """Gemini rejected the request (bad API key, permission, invalid request). NOT retryable as-is."""


class OutputValidationError(KavachError):
    """Model output failed schema or business validation."""

    def __init__(self, message: str, problems: list[str] | None = None):
        super().__init__(message)
        self.problems = problems or [message]


class IncidentProcessingError(KavachError):
    """Controlled failure after bounded retry/repair was exhausted."""


class RepositoryError(KavachError):
    """Persistence failed (database down, write rejected). Retryable; the record was NOT stored."""


class IdempotencyConflictError(KavachError):
    """The same request_id was reused with a different request payload."""
