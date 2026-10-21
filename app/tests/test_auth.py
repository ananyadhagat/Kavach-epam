import pytest

from app.config import settings
from app.main import app
from app.tests.conftest import API, AUTH, DEMO_TOKEN


def protected_routes() -> list[tuple[str, str]]:
    # Discovered from the OpenAPI schema; FastAPI may wrap included
    # routers lazily, so app.routes does not list them directly.
    routes = []

    for path, operations in app.openapi()["paths"].items():
        if not path.startswith("/api/v1"):
            continue

        concrete = (
            path.replace("{task_id}", "TASK-001")
            .replace("{step_id}", "STEP-001")
        )

        for method in operations:
            routes.append((method.upper(), concrete))

    return sorted(routes)


PROTECTED = protected_routes()

BAD_HEADERS = {
    "missing": {},
    "wrong_token": {"Authorization": "Bearer wrong-token"},
    "empty_token": {"Authorization": "Bearer "},
    "scheme_only": {"Authorization": "Bearer"},
    "no_scheme": {"Authorization": DEMO_TOKEN},
    "basic_scheme": {"Authorization": f"Basic {DEMO_TOKEN}"},
    "token_with_suffix": {"Authorization": f"Bearer {DEMO_TOKEN}x"},
    "token_prefix_only": {"Authorization": f"Bearer {DEMO_TOKEN[:-1]}"},
    "extra_part": {"Authorization": f"Bearer {DEMO_TOKEN} extra"},
    "empty_header": {"Authorization": ""},
}


def test_every_api_route_is_covered():
    # Guards against the route discovery silently returning nothing.
    assert len(PROTECTED) >= 13


def test_valid_bearer_token(client):
    response = client.get(API, headers=AUTH)

    assert response.status_code == 200
    assert response.json()["tasks"][0]["task_id"] == "TASK-001"


def test_bearer_scheme_is_case_insensitive(client):
    response = client.get(
        API, headers={"Authorization": f"bearer {DEMO_TOKEN}"}
    )

    assert response.status_code == 200


@pytest.mark.parametrize("label", BAD_HEADERS)
def test_bad_credentials_rejected_on_task_list(client, label):
    response = client.get(API, headers=BAD_HEADERS[label])

    assert response.status_code == 401
    assert response.json() == {"detail": "Invalid authentication."}
    assert response.headers["www-authenticate"] == "Bearer"


@pytest.mark.parametrize(("method", "path"), PROTECTED)
@pytest.mark.parametrize("label", ["missing", "wrong_token", "basic_scheme"])
def test_every_protected_endpoint_rejects_bad_credentials(
    client, method, path, label
):
    response = client.request(method, path, headers=BAD_HEADERS[label])

    assert response.status_code == 401, (method, path, response.text)
    assert "TASK-001" not in response.text
    assert "Clean overflowing dustbin" not in response.text


@pytest.mark.parametrize(("method", "path"), PROTECTED)
def test_failed_auth_does_not_change_state(client, method, path):
    client.request(method, path, headers=BAD_HEADERS["wrong_token"])

    task = client.get(f"{API}/TASK-001", headers=AUTH).json()
    assert task["status"] == "ASSIGNED"


def test_demo_auth_disabled_in_production(client, monkeypatch):
    monkeypatch.setattr(settings, "app_env", "production")

    response = client.get(API, headers=AUTH)

    assert response.status_code == 401
    assert "disabled in production" in response.json()["detail"]


def test_token_override_is_honoured(client, monkeypatch):
    from pydantic import SecretStr

    monkeypatch.setattr(
        settings, "demo_worker_token", SecretStr("rotated-token-123")
    )

    assert client.get(API, headers=AUTH).status_code == 401
    assert client.get(
        API, headers={"Authorization": "Bearer rotated-token-123"}
    ).status_code == 200


def test_openapi_declares_bearer_security_scheme(client):
    schema = client.get("/openapi.json").json()

    schemes = schema["components"]["securitySchemes"]
    assert schemes["HTTPBearer"] == {
        "type": "http",
        "scheme": "bearer",
        "description": "Demo worker token (local development only).",
    }

    for path, operations in schema["paths"].items():
        if not path.startswith("/api/v1"):
            continue

        for operation in operations.values():
            assert {"HTTPBearer": []} in operation["security"], path
            # The old plain "authorization" header parameter is gone.
            names = [p["name"].lower() for p in operation.get("parameters", [])]
            assert "authorization" not in names, path
