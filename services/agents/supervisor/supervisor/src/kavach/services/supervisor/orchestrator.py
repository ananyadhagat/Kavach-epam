# src/kavach/services/supervisor/orchestrator.py
from __future__ import annotations

from kavach.agents.supervisor import SupervisorAgentClient
from kavach.schemas.supervisor import (
    LlmResponseRecord,
    SupervisorEvaluationResponse,
    SupervisorIncidentInput,
)
from kavach.services.supervisor.hard_gates import run_hard_gates
from kavach.services.supervisor.output_validator import (
    build_needs_review_response,
    validate_and_finalize_decision,
)


class SupervisorOrchestrator:
    """Incident report in, decision JSON out (including the Gemini response). Stateless."""

    def __init__(self, agent_client: SupervisorAgentClient) -> None:
        self.agent_client = agent_client

    @property
    def _actor(self) -> str:
        return f"supervisor_agent:{self.agent_client.llm_mode}"

    def _llm_record(self, skipped_reason: str | None = None) -> LlmResponseRecord:
        c = self.agent_client
        if skipped_reason is None and c.llm_mode == "mock":
            skipped_reason = "MOCK_MODE_NO_API_CALL"
        return LlmResponseRecord(
            mode=c.llm_mode,
            model=c.model_name if c.llm_mode == "gemini" else None,
            called=False if skipped_reason == "HARD_GATE_FAILED" else c.last_called,
            skipped_reason=skipped_reason,
            raw_text=None if skipped_reason == "HARD_GATE_FAILED" else c.last_raw_text,
            parsed_suggestion=None if skipped_reason == "HARD_GATE_FAILED" else c.last_suggestion,
            error=None if skipped_reason == "HARD_GATE_FAILED" else c.last_error,
        )

    def evaluate_incident(self, incident: SupervisorIncidentInput) -> SupervisorEvaluationResponse:
        gate = run_hard_gates(incident)
        if not gate.passed:
            response = build_needs_review_response(
                incident, [*gate.reason_codes, *gate.notes], gate.rationale, actor=self._actor
            )
            return response.model_copy(update={"llm_response": self._llm_record("HARD_GATE_FAILED")})

        suggestion = self.agent_client.evaluate(incident)
        response = validate_and_finalize_decision(
            incident,
            suggestion,
            extra_reason_codes=gate.notes,
            actor=self._actor,
            llm_failure_note=self.agent_client.last_error,
        )
        return response.model_copy(update={"llm_response": self._llm_record()})
