import sys
from fastapi.testclient import TestClient
import pytest

from app.repositories.idempotency_repository import idempotency_repo
from app.repositories.plan_repository import plan_repo
from app.schemas.duplicate_contract import DuplicateDecision
from app.schemas.supervisor_contract import SupervisorDecisionStatus
from main import app
from tests.contract.test_module04_contracts import get_master_plan_sample_request_dict

client = TestClient(app)


@pytest.fixture(autouse=True)
def clean_repos():
    plan_repo.clear()
    idempotency_repo.clear()
    yield
    plan_repo.clear()
    idempotency_repo.clear()


def test_api_health_endpoint():
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "healthy"
    assert data["agent"] == "sanitation-agent"
    assert data["storage"] == "in-memory-only"
    assert data["zero_llm_mode"] is True


def test_api_create_plan_success():
    payload = get_master_plan_sample_request_dict()
    resp = client.post("/api/v1/sanitation/plan", json=payload)
    assert resp.status_code == 200
    data = resp.json()

    assert data["plan_id"] == "SAN-PLAN-2026-000123"
    assert data["contract_version"] == "1.0.0"
    assert data["planning_status"] == "PRELIMINARY_PLAN"
    assert data["dispatch_eligible"] is False
    assert "QUANTITY_NOT_MEASURED" in data["hold_reason_codes"]
    assert len(data["tasks"]) == 4
    assert all(t["status"] == "NOT_STARTED" for t in data["tasks"])
    assert data["resource_estimate"]["availability_confirmed"] is False


def test_api_idempotency_identical_replay():
    payload = get_master_plan_sample_request_dict()
    payload["event_id"] = "evt-idem-test-101"

    # First request
    resp1 = client.post(
        "/api/v1/sanitation/plan",
        json=payload,
        headers={"Idempotency-Key": "key-test-101"},
    )
    assert resp1.status_code == 200

    # Second identical request
    resp2 = client.post(
        "/api/v1/sanitation/plan",
        json=payload,
        headers={"Idempotency-Key": "key-test-101"},
    )
    assert resp2.status_code == 200
    assert resp1.json()["plan_id"] == resp2.json()["plan_id"]


def test_api_idempotency_conflict_returns_409():
    payload1 = get_master_plan_sample_request_dict()
    payload1["event_id"] = "evt-idem-test-102"
    payload1["incident"]["estimated_waste_kg"] = 50.0

    resp1 = client.post(
        "/api/v1/sanitation/plan",
        json=payload1,
        headers={"Idempotency-Key": "key-test-102"},
    )
    assert resp1.status_code == 200

    # Same key, modified payload
    payload2 = get_master_plan_sample_request_dict()
    payload2["event_id"] = "evt-idem-test-102"
    payload2["incident"]["estimated_waste_kg"] = 500.0

    resp2 = client.post(
        "/api/v1/sanitation/plan",
        json=payload2,
        headers={"Idempotency-Key": "key-test-102"},
    )
    assert resp2.status_code == 409
    data = resp2.json()
    assert data["detail"]["reason_code"] == "IDEMPOTENCY_KEY_REUSED_WITH_DIFFERENT_INPUT"


def test_api_held_plan_when_supervisor_pending_approval():
    payload = get_master_plan_sample_request_dict()
    payload["event_id"] = "evt-pending-001"
    payload["supervisor_decision"]["decision_status"] = SupervisorDecisionStatus.PENDING_APPROVAL.value

    resp = client.post("/api/v1/sanitation/plan", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["planning_status"] == "BLOCKED"
    assert data["dispatch_eligible"] is False
    assert "SUPERVISOR_NOT_APPROVED" in data["hold_reason_codes"]
    assert len(data["tasks"]) == 0


def test_api_held_plan_when_duplicate():
    payload = get_master_plan_sample_request_dict()
    payload["event_id"] = "evt-dup-001"
    payload["duplicate_result"]["decision"] = DuplicateDecision.DUPLICATE.value

    resp = client.post("/api/v1/sanitation/plan", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["dispatch_eligible"] is False
    assert "DUPLICATE_OF_EXISTING_INCIDENT" in data["hold_reason_codes"]


def test_api_handoff_rejects_ineligible_plan_with_403():
    payload = get_master_plan_sample_request_dict()
    payload["event_id"] = "evt-handoff-prelim"

    # Preliminary plan has dispatch_eligible = False, so handoff is forbidden
    resp = client.post("/api/v1/sanitation/handoff", json=payload)
    assert resp.status_code == 403
    assert resp.json()["detail"]["error"] == "Plan not dispatch-eligible"


def test_api_malformed_request_returns_422():
    resp = client.post("/api/v1/sanitation/plan", json={"invalid": "payload"})
    assert resp.status_code == 422


def test_zero_llm_guarantee():
    """Verify that no LangChain, LangGraph, or Gemini module is imported or invoked during planning."""
    prohibited = ["langchain", "langgraph", "langsmith", "google.genai"]
    for mod in prohibited:
        # Check that prohibited modules are not in sys.modules of the planning service
        assert mod not in sys.modules, f"Prohibited module {mod} found loaded in sys.modules!"

    # Run planning pipeline
    payload = get_master_plan_sample_request_dict()
    resp = client.post("/api/v1/sanitation/plan", json=payload)
    assert resp.status_code == 200

    # Verify again after execution
    for mod in prohibited:
        assert mod not in sys.modules, f"Prohibited module {mod} loaded during planning!"


def test_no_database_persistence_configured():
    """Verify in-memory repository usage only; no sqlalchemy, databases, or migrations."""
    db_modules = ["sqlalchemy", "databases", "alembic", "psycopg2", "asyncpg"]
    for mod in db_modules:
        assert mod not in sys.modules


def test_api_get_plan_by_id_and_by_incident():
    payload = get_master_plan_sample_request_dict()
    payload["event_id"] = "evt-get-test-01"
    create_resp = client.post("/api/v1/sanitation/plan", json=payload)
    assert create_resp.status_code == 200
    plan_id = create_resp.json()["plan_id"]
    incident_id = create_resp.json()["incident_id"]

    # Retrieve by plan_id
    get_resp = client.get(f"/api/v1/sanitation/plan/{plan_id}")
    assert get_resp.status_code == 200
    assert get_resp.json()["plan_id"] == plan_id

    # Retrieve non-existent plan_id -> 404
    get_404 = client.get("/api/v1/sanitation/plan/NON_EXISTENT_PLAN_ID")
    assert get_404.status_code == 404

    # Retrieve by incident_id
    inc_resp = client.get(f"/api/v1/sanitation/plans/by-incident/{incident_id}")
    assert inc_resp.status_code == 200
    plans = inc_resp.json()
    assert len(plans) >= 1
    assert any(p["plan_id"] == plan_id for p in plans)


def test_api_supervisor_evaluation_incomplete_returns_blocked():
    payload = get_master_plan_sample_request_dict()
    payload["event_id"] = "evt-sup-eval-incomp"
    payload["supervisor_decision"]["evaluation_status"] = "PENDING"
    resp = client.post("/api/v1/sanitation/plan", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["planning_status"] == "BLOCKED"
    assert "SUPERVISOR_EVALUATION_INCOMPLETE" in data["hold_reason_codes"]


def test_api_handoff_eligible_plan_success():
    """When a plan meets all criteria and is PLAN_READY, handoff produces a DispatchWorkPackage."""
    payload = get_master_plan_sample_request_dict()
    payload["event_id"] = "evt-handoff-ready"
    payload["incident"]["estimated_waste_kg"] = 100.0  # Measured quantity
    payload["incident"]["affected_area_sqm"] = 25.0  # Measured affected area

    resp = client.post("/api/v1/sanitation/handoff", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["plan_id"] == "SAN-PLAN-2026-000123"
    assert data["dispatch_eligible"] is True
    assert data["assigned_worker_id"] is None
    assert data["assignment_status"] == "UNASSIGNED"
    assert data["availability_confirmed"] is False
    assert len(data["tasks"]) > 0

