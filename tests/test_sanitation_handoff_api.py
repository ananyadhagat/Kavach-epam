from fastapi.testclient import TestClient

from main import app

client = TestClient(app)

BASE_URL = "/api/v1/sanitation/handoff"


def make_request(approval_status="approved"):
    return {
        "complaint_id": "KAVACH-201",
        "description": "Overflowing public dustbin near the main entrance",
        "location": "Main entrance",
        "priority": "high",
        "approval_status": approval_status,
        "estimated_waste_kg": None,
        "evidence_urls": [],
    }


def test_approved_complaint_returns_dispatch_contract():
    response = client.post(
        BASE_URL,
        json=make_request("approved"),
    )

    assert response.status_code == 200

    body = response.json()
    assert body["complaint_id"] == "KAVACH-201"
    assert body["approval_status"] == "approved"
    assert body["planning_status"] == "PROPOSED"
    assert body["requires_human_review"] is True
    assert body["dispatch_eligible"] is False
    assert len(body["tasks"]) > 0


def test_pending_complaint_returns_forbidden():
    response = client.post(
        BASE_URL,
        json=make_request("pending"),
    )

    assert response.status_code == 403


def test_rejected_complaint_returns_forbidden():
    response = client.post(
        BASE_URL,
        json=make_request("rejected"),
    )

    assert response.status_code == 403


def test_invalid_priority_returns_validation_error():
    request = make_request("approved")
    request["priority"] = "urgent"

    response = client.post(BASE_URL, json=request)

    assert response.status_code == 422


def test_missing_description_returns_validation_error():
    request = make_request("approved")
    del request["description"]

    response = client.post(BASE_URL, json=request)

    assert response.status_code == 422
