
import pytest
from pydantic import ValidationError
from fastapi.testclient import TestClient

from app.schemas.sanitation import (
    SanitationPriority,
    SanitationRequest,
)
from main import app


client = TestClient(app)


def test_valid_complaint_is_accepted():
    request = SanitationRequest(
        complaint_id="KAVACH-001",
        description="Overflowing public dustbin",
        location="Zone A",
        priority=SanitationPriority.HIGH,
    )

    assert request.complaint_id == "KAVACH-001"
    assert request.priority == SanitationPriority.HIGH
    assert request.estimated_waste_kg is None


def test_negative_waste_quantity_is_rejected():
    with pytest.raises(ValidationError):
        SanitationRequest(
            complaint_id="KAVACH-002",
            description="Overflowing public dustbin",
            location="Zone A",
            priority=SanitationPriority.HIGH,
            estimated_waste_kg=-5,
        )


def test_invalid_priority_is_rejected():
    with pytest.raises(ValidationError):
        SanitationRequest(
            complaint_id="KAVACH-003",
            description="Overflowing public dustbin",
            location="Zone A",
            priority="URGENT",
        )


def test_missing_description_is_rejected_by_api():
    response = client.post(
        "/api/v1/sanitation/plan",
        json={
            "complaint_id": "KAVACH-004",
            "location": "Zone A",
            "priority": "high",
        },
    )

    assert response.status_code == 422


def test_invalid_priority_is_rejected_by_api():
    response = client.post(
        "/api/v1/sanitation/plan",
        json={
            "complaint_id": "KAVACH-005",
            "description": "Overflowing public dustbin",
            "location": "Zone A",
            "priority": "URGENT",
        },
    )

    assert response.status_code == 422


def test_health_endpoint():
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "healthy"


def test_malformed_gemini_json_returns_502(monkeypatch):
    monkeypatch.setattr(
        "app.ai.sanitation_graph.generate_text",
        lambda prompt: "this is not valid JSON",
    )

    response = client.post(
        "/api/v1/sanitation/plan",
        json={
            "complaint_id": "KAVACH-006",
            "description": "Overflowing public dustbin",
            "location": "Zone A",
            "priority": "high",
        },
    )

    assert response.status_code == 502


def test_gemini_failure_returns_502(monkeypatch):
    def simulate_gemini_failure(prompt):
        raise RuntimeError("Simulated Gemini service failure")

    monkeypatch.setattr(
        "app.ai.sanitation_graph.generate_text",
        simulate_gemini_failure,
    )

    response = client.post(
        "/api/v1/sanitation/plan",
        json={
            "complaint_id": "KAVACH-007",
            "description": "Overflowing public dustbin",
            "location": "Zone A",
            "priority": "high",
        },
    )

    assert response.status_code == 502


def test_unsafe_generated_plan_is_rejected(monkeypatch):
    unsafe_plan = """
    {
        "complaint_id": "KAVACH-008",
        "summary": "Workers have been assigned to the complaint",
        "tasks": [],
        "safety_notes": [],
        "requires_human_review": true
    }
    """

    monkeypatch.setattr(
        "app.ai.sanitation_graph.generate_text",
        lambda prompt: unsafe_plan,
    )

    response = client.post(
        "/api/v1/sanitation/plan",
        json={
            "complaint_id": "KAVACH-008",
            "description": "Overflowing public dustbin",
            "location": "Zone A",
            "priority": "high",
        },
    )

    assert response.status_code == 502


def test_safe_policy_based_plan_is_accepted(monkeypatch):
    monkeypatch.setattr(
        "app.ai.sanitation_graph.generate_text",
        lambda prompt: (
            '{"issue_type": "overflowing_dustbin", '
            '"reason": "The dustbin is overflowing."}'
        ),
    )

    response = client.post(
        "/api/v1/sanitation/plan",
        json={
            "complaint_id": "KAVACH-009",
            "description": "Overflowing public dustbin",
            "location": "Zone A",
            "priority": "high",
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["complaint_id"] == "KAVACH-009"
    assert data["requires_human_review"] is True
    assert len(data["tasks"]) >= 1
