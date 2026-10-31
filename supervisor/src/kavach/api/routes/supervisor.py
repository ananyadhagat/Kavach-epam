# src/kavach/api/routes/supervisor.py
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from kavach.agents.supervisor import SupervisorAgentClient
from kavach.schemas.supervisor import SupervisorEvaluationResponse, SupervisorIncidentInput
from kavach.services.supervisor.orchestrator import SupervisorOrchestrator

router = APIRouter(prefix="/api/v1/supervisor", tags=["supervisor"])


def get_supervisor_orchestrator() -> SupervisorOrchestrator:
    try:
        client = SupervisorAgentClient()
    except ValueError as exc:  # invalid KAVACH_LLM_MODE
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc
    return SupervisorOrchestrator(agent_client=client)


@router.post(
    "/evaluate",
    response_model=SupervisorEvaluationResponse,
    summary="Incident report JSON in, Supervisor decision JSON out",
)
def evaluate_incident_endpoint(
    payload: SupervisorIncidentInput,
    orchestrator: SupervisorOrchestrator = Depends(get_supervisor_orchestrator),
) -> SupervisorEvaluationResponse:
    return orchestrator.evaluate_incident(payload)
