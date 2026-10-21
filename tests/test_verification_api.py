import tempfile

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.repositories.verification_repository import SQLiteVerificationRepository


@pytest.fixture
def client(monkeypatch, make_service):
    from app import main

    monkeypatch.setenv("KAVACH_API_KEY", "test-verification-key")
    with tempfile.TemporaryDirectory(prefix=".tmp-api-", dir=".") as temp_dir:
        monkeypatch.setattr(main, "audit_repository", SQLiteVerificationRepository(f"{temp_dir}/audit.sqlite"))
        main.app.state.verification_service = make_service()
        with TestClient(main.app) as test_client:
            yield test_client


def auth_headers():
    return {"X-KAVACH-API-Key": "test-verification-key"}


def test_app_lifespan_health_endpoint_starts_successfully(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["contract_version"] == "1.1"


def test_http_verification_demo_returns_versioned_contract(client):
    response = client.post("/api/v1/tasks/TASK-100/verification", json={"submission_id": "SUB-PASS"},
                           headers=auth_headers())
    assert response.status_code == 200
    assert response.json()["contract_version"] == "1.1"
    assert response.headers["X-KAVACH-Contract-Version"] == "1.1"
    assert response.json()["reason_codes"] == ["QUALITY_NOT_CHECKED"]
    assert response.json()["failed_requirement_ids"] == []
    assert response.json()["verification_status"] == "PASS"


def test_http_unknown_task_and_invalid_request_are_rejected(client):
    missing_task = client.post("/api/v1/tasks/NO-SUCH-TASK/verification", json={"submission_id": "SUB-PASS"},
                               headers=auth_headers())
    assert missing_task.status_code == 404
    assert missing_task.json()["detail"] == "Unknown task ID"
    invalid = client.post("/api/v1/tasks/TASK-100/verification",
                          json={"submission_id": "SUB-PASS", "unexpected": "value"}, headers=auth_headers())
    assert invalid.status_code == 422


def test_http_idempotency_returns_the_saved_result(client):
    body = {"submission_id": "SUB-PASS"}
    first = client.post("/api/v1/tasks/TASK-100/verification", json=body, headers=auth_headers()).json()
    second = client.post("/api/v1/tasks/TASK-100/verification", json=body, headers=auth_headers()).json()
    assert second["verification_id"] == first["verification_id"]
    assert second["created_at"] == first["created_at"]


def test_http_unauthorized_and_rejected_evidence_do_not_disclose_protected_data(client):
    denied = client.post("/api/v1/tasks/TASK-100/verification", json={"submission_id": "SUB-PASS"})
    assert denied.status_code == 401
    assert denied.json()["detail"] == "Unauthorized."

    service = client.app.state.verification_service
    service.submissions.submissions["SUB-PASS"]["evidence"][1]["task_id"] = "TASK-OTHER"
    rejected = client.post("/api/v1/tasks/TASK-100/verification", json={"submission_id": "SUB-PASS"},
                           headers=auth_headers())
    assert rejected.status_code == 422
    body = rejected.text
    assert "belongs to another task" in body
    assert "28.6142" not in body
    assert "77.2092" not in body
    assert "storage_path" not in body


def test_http_blurry_stored_fixture_returns_manual_review_and_quality_reason(client, tmp_path):
    service = client.app.state.verification_service
    service.submissions.storage_root = tmp_path
    checker = (np.indices((480, 640)).sum(axis=0) % 2 * 255).astype(np.uint8)
    crisp = np.dstack((checker, checker, checker))
    blurred = cv2.GaussianBlur(crisp, (31, 31), 0)
    for record, image in zip(service.submissions.submissions["SUB-PASS"]["evidence"], (crisp, blurred)):
        ok, encoded = cv2.imencode(".png", image)
        assert ok
        filename = f"{record['evidence_id']}.png"
        (tmp_path / filename).write_bytes(encoded.tobytes())
        record["storage_path"] = filename

    response = client.post("/api/v1/tasks/TASK-100/verification", json={"submission_id": "SUB-PASS"},
                           headers=auth_headers())
    assert response.status_code == 200
    assert response.json()["verification_status"] == "MANUAL_REVIEW"
    assert "IMAGE_BLURRY" in response.json()["reason_codes"]
    assert "Image is blurry" in response.json()["image_findings"]["limitations"]
    assert "storage_path" not in response.text
