import hashlib
import json
import threading
from typing import Any, Protocol
from pydantic import BaseModel, ConfigDict

from app.schemas.sanitation_response import SanitationPlanResult


class IdempotencyRecord(BaseModel):
    """Tracks idempotency key, request hash, and generated plan."""

    model_config = ConfigDict(extra="ignore")

    idempotency_key: str
    canonical_hash: str
    plan_id: str
    result: SanitationPlanResult


class IdempotencyConflictError(Exception):
    """Raised when an existing idempotency key is reused with a different input payload."""

    def __init__(self, key: str, message: str = "Idempotency key reused with different input payload."):
        super().__init__(message)
        self.key = key
        self.reason_code = "IDEMPOTENCY_KEY_REUSED_WITH_DIFFERENT_INPUT"


class IdempotencyRepository(Protocol):
    """Protocol for in-memory idempotency tracking."""

    def get(self, key: str) -> IdempotencyRecord | None:
        ...

    def record(self, key: str, canonical_hash: str, result: SanitationPlanResult) -> None:
        ...


class InMemoryIdempotencyRepository:
    """In-memory idempotency record storage.

    LIMITATION: Stored in Python process memory. Does not survive restarts.
    """

    def __init__(self):
        self._records: dict[str, IdempotencyRecord] = {}
        self._lock = threading.Lock()

    @staticmethod
    def compute_hash(data: dict[str, Any]) -> str:
        """Produce a deterministic SHA-256 hash of a dictionary."""
        serialized = json.dumps(data, sort_keys=True, default=str)
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()

    def get(self, key: str) -> IdempotencyRecord | None:
        with self._lock:
            return self._records.get(key)

    def check_or_record(
        self,
        key: str,
        payload_dict: dict[str, Any],
        result_factory: Any,
    ) -> tuple[SanitationPlanResult, bool]:
        """Check for existing idempotency key in a thread-safe manner.

        Returns:
            (SanitationPlanResult, is_replay: bool)
        Raises:
            IdempotencyConflictError if key reused with different payload.
        """
        current_hash = self.compute_hash(payload_dict)
        with self._lock:
            existing = self._records.get(key)

            if existing is not None:
                if existing.canonical_hash == current_hash:
                    return existing.result, True
                raise IdempotencyConflictError(
                    key=key,
                    message=f"Idempotency key '{key}' already exists with a different input payload.",
                )

            new_result: SanitationPlanResult = result_factory()
            self._records[key] = IdempotencyRecord(
                idempotency_key=key,
                canonical_hash=current_hash,
                plan_id=new_result.plan_id,
                result=new_result,
            )
            return new_result, False

    def clear(self) -> None:
        with self._lock:
            self._records.clear()


# Default singleton instance
idempotency_repo = InMemoryIdempotencyRepository()
