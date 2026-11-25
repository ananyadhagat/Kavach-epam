import threading
from typing import Protocol
from app.schemas.sanitation_response import SanitationPlanResult


class PlanRepository(Protocol):
    """Protocol for sanitation plan storage."""

    def save(self, plan: SanitationPlanResult) -> None:
        ...

    def get_by_id(self, plan_id: str) -> SanitationPlanResult | None:
        ...

    def get_by_incident_id(self, incident_id: str) -> list[SanitationPlanResult]:
        ...

    def list_all(self) -> list[SanitationPlanResult]:
        ...


class InMemoryPlanRepository:
    """In-memory storage for sanitation plans.

    LIMITATION: Stored exclusively in Python process memory. Does not survive restarts.
    """

    def __init__(self):
        self._plans_by_id: dict[str, SanitationPlanResult] = {}
        self._plans_by_incident: dict[str, list[SanitationPlanResult]] = {}
        self._lock = threading.Lock()

    def save(self, plan: SanitationPlanResult) -> None:
        with self._lock:
            self._plans_by_id[plan.plan_id] = plan
            if plan.incident_id not in self._plans_by_incident:
                self._plans_by_incident[plan.incident_id] = []
            self._plans_by_incident[plan.incident_id].append(plan)

    def get_by_id(self, plan_id: str) -> SanitationPlanResult | None:
        with self._lock:
            return self._plans_by_id.get(plan_id)

    def get_by_incident_id(self, incident_id: str) -> list[SanitationPlanResult]:
        with self._lock:
            return list(self._plans_by_incident.get(incident_id, []))

    def list_all(self) -> list[SanitationPlanResult]:
        with self._lock:
            return list(self._plans_by_id.values())

    def clear(self) -> None:
        with self._lock:
            self._plans_by_id.clear()
            self._plans_by_incident.clear()


# Default singleton instance
plan_repo = InMemoryPlanRepository()
