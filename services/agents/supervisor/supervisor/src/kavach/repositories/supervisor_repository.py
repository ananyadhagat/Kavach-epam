# src/kavach/repositories/supervisor_repository.py
from __future__ import annotations

from threading import RLock
from typing import Optional
from uuid import UUID

from kavach.schemas.supervisor import (
    AuditLogRecord,
    SupervisorDecisionRecord,
    SupervisorEvaluationResponse,
)


class InMemorySupervisorRepository:
    """
    Persistence store for Supervisor_Decision and Audit_Log (D3).
    Maintains 1-to-many history from Incident to Supervisor_Decision.
    """

    def __init__(self) -> None:
        self._lock = RLock()
        self._decisions_by_id: dict[UUID, SupervisorDecisionRecord] = {}
        self._decisions_by_incident: dict[UUID, list[UUID]] = {}
        self._audit_logs_by_decision: dict[UUID, list[AuditLogRecord]] = {}
        self._latest_routing_by_decision: dict[UUID, SupervisorEvaluationResponse] = {}

    def save_evaluation(
        self, response: SupervisorEvaluationResponse
    ) -> SupervisorEvaluationResponse:
        with self._lock:
            decision = response.supervisor_decision
            audit = response.audit

            self._decisions_by_id[decision.decision_id] = decision
            incident_list = self._decisions_by_incident.setdefault(decision.incident_id, [])
            if decision.decision_id not in incident_list:
                incident_list.append(decision.decision_id)

            audit_list = self._audit_logs_by_decision.setdefault(decision.decision_id, [])
            audit_list.append(audit)
            self._latest_routing_by_decision[decision.decision_id] = response
            return response

    def get_by_decision_id(self, decision_id: UUID) -> Optional[SupervisorEvaluationResponse]:
        with self._lock:
            return self._latest_routing_by_decision.get(decision_id)

    def list_by_incident_id(self, incident_id: UUID) -> list[SupervisorEvaluationResponse]:
        with self._lock:
            decision_ids = self._decisions_by_incident.get(incident_id, [])
            return [
                self._latest_routing_by_decision[d_id]
                for d_id in decision_ids
                if d_id in self._latest_routing_by_decision
            ]

    def list_audit_logs(self, decision_id: UUID) -> list[AuditLogRecord]:
        with self._lock:
            return list(self._audit_logs_by_decision.get(decision_id, []))