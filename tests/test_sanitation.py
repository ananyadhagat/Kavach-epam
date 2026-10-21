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




def test_policy_based_plan_is_accepted():
    from app.ai.sanitation_graph import sanitation_graph

    result = sanitation_graph.invoke({
        "request": {
            "complaint_id": "KAVACH-009",
            "description": "Overflowing public dustbin near the main entrance",
            "location": "Main entrance",
            "priority": "high",
            "estimated_waste_kg": None,
        }
    })

    plan = result["plan"]
    assert plan["complaint_id"] == "KAVACH-009"
    assert len(plan["tasks"]) > 0
    assert plan["requires_human_review"] is True


def test_unknown_issue_requires_human_review():
    from app.ai.sanitation_graph import sanitation_graph

    result = sanitation_graph.invoke({
        "request": {
            "complaint_id": "KAVACH-010",
            "description": "Broken streetlight near the entrance",
            "location": "Main entrance",
            "priority": "medium",
            "estimated_waste_kg": None,
        }
    })

    plan = result["plan"]
    assert plan["complaint_id"] == "KAVACH-010"
    assert plan["requires_human_review"] is True
    assert "no matching sanitation policy" in plan["summary"].lower()


def test_graph_preserves_original_complaint_id():
    from app.ai.sanitation_graph import sanitation_graph

    result = sanitation_graph.invoke({
        "request": {
            "complaint_id": "KAVACH-011",
            "description": "Garbage pile near the entrance",
            "location": "Main entrance",
            "priority": "high",
            "estimated_waste_kg": None,
        }
    })

    assert result["plan"]["complaint_id"] == "KAVACH-011"


def test_unsafe_plan_claim_is_rejected():
    import pytest

    from app.schemas.sanitation import SanitationPlan
    from app.validators.sanitation_safety import validate_sanitation_safety

    unsafe_plan = SanitationPlan(
        complaint_id="KAVACH-012",
        summary="Workers have been assigned to the complaint",
        tasks=[],
        safety_notes=[],
        requires_human_review=True,
    )

    with pytest.raises(ValueError):
        validate_sanitation_safety(unsafe_plan)
