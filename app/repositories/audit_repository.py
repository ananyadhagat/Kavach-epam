import threading
from datetime import datetime, timezone
from typing import Any, Protocol
from pydantic import BaseModel, ConfigDict, Field


class PlanAuditRecord(BaseModel):
    """In-memory audit trail record for sanitation planning events."""

    model_config = ConfigDict(extra="ignore")

    plan_id: str
    incident_id: str
    event_id: str
    supervisor_decision_id: str
    contract_version: str
    planning_status: str
    dispatch_eligible: bool
    template_version: str | None = None
    policy_versions: dict[str, str] = Field(default_factory=dict)
    reason_codes: list[str] = Field(default_factory=list)
    hold_reason_codes: list[str] = Field(default_factory=list)
    recorded_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class AuditRepository(Protocol):
    """Protocol for audit record persistence."""

    def record_audit(self, record: PlanAuditRecord) -> None:
        ...

    def list_by_plan_id(self, plan_id: str) -> list[PlanAuditRecord]:
        ...


class InMemoryAuditRepository:
    """In-memory audit repository.

    LIMITATION: Stored exclusively in Python process memory. Does not survive restarts.
    """

    def __init__(self):
        self._audit_log: list[PlanAuditRecord] = []
        self._lock = threading.Lock()

    def record_audit(self, record: PlanAuditRecord) -> None:
        with self._lock:
            self._audit_log.append(record)

    def list_by_plan_id(self, plan_id: str) -> list[PlanAuditRecord]:
        with self._lock:
            return [r for r in self._audit_log if r.plan_id == plan_id]

    def list_all(self) -> list[PlanAuditRecord]:
        with self._lock:
            return list(self._audit_log)

    def clear(self) -> None:
        with self._lock:
            self._audit_log.clear()


# Default singleton instance
audit_repo = InMemoryAuditRepository()
