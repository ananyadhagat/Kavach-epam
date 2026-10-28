from datetime import datetime, timezone
import pytest
from fastapi.testclient import TestClient

from app.schemas.duplicate_contract import DuplicateDecision, DuplicateResult
from app.schemas.incident_contract import IncidentRecord, LocationData
from app.schemas.sanitation_request import SanitationPlanRequest
from app.schemas.sanitation_response import PlanningStatus
from app.schemas.supervisor_contract import (
    ActionPlan,
    RoutingInfo,
    SupervisorDecision,
    SupervisorDecisionStatus,
)
from app.services.sanitation_planning_service import planning_service
from main import app

client = TestClient(app)


def make_plan_request(complaint_id="KAVACH-009", category="WASTE_OVERFLOW", incident_type="BIN_OVERFLOW", template_id="BIN_OVERFLOW_RESPONSE", **overrides):
    now = datetime.now(timezone.utc)
    data = {
        "contract_version": "1.0.0",
        "event_id": f"evt-{complaint_id}",
        "incident": IncidentRecord(
            incident_id=f"INC-{complaint_id}",
            complaint_id=complaint_id,
            incident_summary="Overflowing public dustbin near the main entrance",
            complaint_text="There is waste spilling out of the dustbin",
            category=category,
            incident_type=incident_type,
            reported_at=now,
            location=LocationData(location_id="Main entrance"),
            estimated_waste_kg=overrides.get("estimated_waste_kg", None),
        ),
        "duplicate_result": DuplicateResult(
            decision=DuplicateDecision.NEW,
        ),
        "supervisor_decision": SupervisorDecision(
            decision_id=f"SUP-{complaint_id}",
            decision_status=SupervisorDecisionStatus.APPROVED_TO_PROCEED,
            department="SANITATION",
            priority="HIGH",
            routing=RoutingInfo(status="RESOLVED", location_id="Main entrance"),
            action_plan=ActionPlan(
                template_id=template_id,
                template_version="1",
                objective="Resolve overflowing bin",
            ),
        ),
    }
    return SanitationPlanRequest(**data)


def test_health_endpoint():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"
    assert response.json()["storage"] == "in-memory-only"


def test_missing_payload_is_rejected_by_api():
    response = client.post("/api/v1/sanitation/plan", json={})
    assert response.status_code == 422


def test_policy_based_plan_is_accepted():
    req = make_plan_request("KAVACH-009")
    plan, _ = planning_service.create_plan(req)

    assert plan.complaint_id == "KAVACH-009"
    assert len(plan.tasks) > 0
    assert plan.tasks[0].task_id == "SAN-T001"
    assert all(t.status.value == "NOT_STARTED" for t in plan.tasks)


def test_unknown_issue_requires_review():
    req = make_plan_request(
        "KAVACH-010",
        category="STREETLIGHT",
        incident_type="BROKEN_LIGHT",
        template_id="NON_EXISTENT",
    )
    plan, _ = planning_service.create_plan(req)

    assert plan.complaint_id == "KAVACH-010"
    assert plan.planning_status in (PlanningStatus.NEEDS_REVIEW, PlanningStatus.BLOCKED)
    assert plan.dispatch_eligible is False
    assert len(plan.hold_reason_codes) > 0


def test_plan_preserves_original_complaint_and_incident_id():
    req = make_plan_request("KAVACH-011")
    plan, _ = planning_service.create_plan(req)

    assert plan.complaint_id == "KAVACH-011"
    assert plan.incident_id == "INC-KAVACH-011"


def test_plan_does_not_invent_duration_without_measured_quantity():
    req = make_plan_request("KAVACH-DURATION-001", estimated_waste_kg=None)
    plan, _ = planning_service.create_plan(req)

    assert plan.duration_estimate.status.value == "NEEDS_MORE_DATA"
    assert plan.duration_estimate.total_minutes is None
    assert "QUANTITY_NOT_MEASURED" in plan.hold_reason_codes
    assert plan.dispatch_eligible is False
