from datetime import datetime, timezone
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.schemas.duplicate_contract import DuplicateDecision, DuplicateResult
from app.schemas.incident_contract import IncidentRecord, LocationData
from app.schemas.sanitation_request import SanitationPlanRequest
from app.schemas.sanitation_response import PlanningStatus, SanitationPlanResult
from app.schemas.supervisor_contract import (
    ActionPlan,
    RoutingInfo,
    SupervisorDecision,
    SupervisorDecisionStatus,
)
from app.services.plan_validator import PlanValidationError, validate_plan_result
from app.services.sanitation_planning_service import planning_service
from main import app

client = TestClient(app)


def build_test_request(event_id="evt-test-manual-001", **overrides) -> SanitationPlanRequest:
    fixed_time = datetime(2026, 10, 26, 12, 0, 0, tzinfo=timezone.utc)
    return SanitationPlanRequest(
        contract_version="1.0.0",
        event_id=event_id,
        incident=IncidentRecord(
            incident_id="INC-2026-000999",
            complaint_id="CMP-2026-000999",
            incident_summary="Waste overflowing near gate",
            complaint_text="There is overflow from bin",
            category="WASTE_OVERFLOW",
            incident_type="BIN_OVERFLOW",
            reported_at=fixed_time,
            location=LocationData(location_id="GATE"),
            estimated_waste_kg=50.0,
        ),
        duplicate_result=DuplicateResult(
            processing_status="COMPLETED",
            decision=DuplicateDecision.NEW,
        ),
        supervisor_decision=SupervisorDecision(
            decision_id="SUP-2026-000999",
            decision_status=SupervisorDecisionStatus.APPROVED_TO_PROCEED,
            department="SANITATION",
            priority="MEDIUM",
            routing=RoutingInfo(status="RESOLVED", location_id="GATE"),
            action_plan=ActionPlan(
                template_id="BIN_OVERFLOW_RESPONSE",
                template_version="1",
                objective="Resolve bin overflow",
            ),
        ),
        **overrides,
    )


def test_health_endpoint():
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["storage"] == "in-memory-only"
    assert data["zero_llm_mode"] is True


def test_missing_description_is_rejected_by_api():
    response = client.post(
        "/api/v1/sanitation/plan",
        json={
            "contract_version": "1.0.0",
            "event_id": "evt-001",
        },
    )
    assert response.status_code == 422


def test_negative_waste_quantity_is_rejected():
    with pytest.raises(ValidationError):
        IncidentRecord(
            incident_id="INC-1",
            complaint_id="CMP-1",
            category="WASTE_OVERFLOW",
            incident_type="BIN_OVERFLOW",
            reported_at=datetime.now(timezone.utc),
            estimated_waste_kg=-5.0,
        )


def test_unsafe_plan_with_forbidden_claims_is_rejected():
    request = build_test_request()
    plan, _ = planning_service.create_plan(request)
    plan.safety_constraints.append("Workers have been assigned to clean the bin")

    with pytest.raises(PlanValidationError, match="forbidden claims"):
        validate_plan_result(plan)


def test_deterministic_plan_created_without_llm():
    request = build_test_request(event_id="evt-test-manual-002")
    plan, is_replay = planning_service.create_plan(request)

    assert plan.plan_id == "SAN-PLAN-2026-000999"
    assert plan.incident_id == "INC-2026-000999"
    assert plan.department == "SANITATION"
    assert len(plan.tasks) >= 3
    assert all(t.status.value == "NOT_STARTED" for t in plan.tasks)
    assert plan.resource_estimate.availability_confirmed is False
