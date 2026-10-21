import pytest
from fastapi.testclient import TestClient

from app.main import app

# The app requires PostgreSQL; use the isolated, freshly seeded test DB.
pytestmark = pytest.mark.usefixtures("clean_database")


def test_health_endpoint():
    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_tasks_requires_authentication():
    with TestClient(app) as client:
        response = client.get("/api/v1/worker/tasks")

    assert response.status_code == 401


def test_worker_sees_assigned_tasks():
    with TestClient(app) as client:
        response = client.get(
            "/api/v1/worker/tasks",
            headers={"Authorization": "Bearer dev-worker-token"},
        )

    assert response.status_code == 200
    assert len(response.json()["tasks"]) >= 1