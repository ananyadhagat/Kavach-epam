import pytest

from app.tests.conftest import API, AUTH

EXPECTED_OPERATIONS = {
    ("get", "/health"),
    ("get", "/api/v1/worker/tasks"),
    ("get", "/api/v1/worker/tasks/{task_id}"),
    ("post", "/api/v1/worker/tasks/{task_id}/accept"),
    ("post", "/api/v1/worker/tasks/{task_id}/reject"),
    ("post", "/api/v1/worker/tasks/{task_id}/start"),
    ("post", "/api/v1/worker/tasks/{task_id}/resume"),
    ("post", "/api/v1/worker/tasks/{task_id}/pause"),
    ("get", "/api/v1/worker/tasks/{task_id}/checklist"),
    ("patch", "/api/v1/worker/tasks/{task_id}/checklist/{step_id}"),
    ("post", "/api/v1/worker/tasks/{task_id}/completion"),
    ("post", "/api/v1/worker/tasks/{task_id}/evidence"),
    ("post", "/api/v1/worker/tasks/{task_id}/arrival"),
    ("post", "/api/v1/worker/tasks/{task_id}/completion-location"),
}


@pytest.fixture
def schema(client):
    response = client.get("/openapi.json")
    assert response.status_code == 200
    return response.json()


def operations(schema) -> set[tuple[str, str]]:
    return {
        (method, path)
        for path, item in schema["paths"].items()
        for method in item
    }


def test_openapi_lists_exactly_the_expected_operations(schema):
    assert operations(schema) == EXPECTED_OPERATIONS


def test_openapi_request_bodies(schema):
    paths = schema["paths"]

    def body_ref(path, method, content="application/json"):
        body = paths[path][method]["requestBody"]
        assert body["required"] is True
        return body["content"][content]["schema"]["$ref"].rsplit("/", 1)[-1]

    base = "/api/v1/worker/tasks/{task_id}"
    assert body_ref(f"{base}/reject", "post") == "TaskActionRequest"
    assert body_ref(f"{base}/checklist/{{step_id}}", "patch") == (
        "ChecklistStepUpdate"
    )
    assert body_ref(f"{base}/completion", "post") == "CompletionClaim"
    assert body_ref(f"{base}/arrival", "post") == "LocationEventCreate"
    assert body_ref(f"{base}/completion-location", "post") == (
        "LocationEventCreate"
    )
    assert "multipart/form-data" in (
        paths[f"{base}/evidence"]["post"]["requestBody"]["content"]
    )


def test_completion_requires_idempotency_header(schema):
    params = schema["paths"]["/api/v1/worker/tasks/{task_id}/completion"][
        "post"
    ]["parameters"]

    header = next(p for p in params if p["name"] == "Idempotency-Key")
    assert header["in"] == "header"
    assert header["required"] is True


def test_health_is_public(schema):
    assert "security" not in schema["paths"]["/health"]["get"]


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("put", f"{API}/TASK-001"),
        ("delete", f"{API}/TASK-001"),
        ("get", f"{API}/TASK-001/accept"),
        ("post", f"{API}/TASK-001/checklist/STEP-001"),
        ("get", f"{API}/TASK-001/completion"),
    ],
)
def test_wrong_method_returns_405(client, method, path):
    assert client.request(method, path, headers=AUTH).status_code == 405


def test_unknown_route_returns_404(client):
    assert client.get(f"{API}/TASK-001/unknown", headers=AUTH).status_code == (
        404
    )


def test_list_response_structure(client):
    body = client.get(API, headers=AUTH).json()

    assert set(body) == {"tasks"}
    task = body["tasks"][0]
    assert set(task) == {
        "task_id", "incident_id", "assigned_worker_id", "title",
        "description", "priority", "status", "location", "checklist",
        "created_at", "updated_at", "arrival_location_event_id",
        "completion_location_event_id", "completion_submission_id",
    }


def test_action_response_structure(client):
    body = client.post(f"{API}/TASK-001/accept", headers=AUTH).json()

    assert set(body) == {"task", "message"}


def test_validation_error_structure(client):
    client.post(f"{API}/TASK-001/accept", headers=AUTH)
    client.post(f"{API}/TASK-001/start", headers=AUTH)

    response = client.patch(f"{API}/TASK-001/checklist/STEP-001",
                            json={"status": "NOPE"}, headers=AUTH)

    assert response.status_code == 422
    error = response.json()["detail"][0]
    assert error["loc"] == ["body", "status"]
    assert error["msg"]


def test_business_error_structure(client):
    response = client.post(f"{API}/TASK-001/pause", headers=AUTH)

    assert response.status_code == 409
    assert response.json() == {
        "detail": "Transition ASSIGNED -> PAUSED is not allowed."
    }


def test_malformed_json_returns_422(client):
    response = client.post(
        f"{API}/TASK-001/reject", content=b"{not json",
        headers={**AUTH, "Content-Type": "application/json"},
    )

    assert response.status_code == 422


def test_swagger_ui_is_served(client):
    response = client.get("/docs")

    assert response.status_code == 200
    assert "swagger-ui" in response.text.lower()
