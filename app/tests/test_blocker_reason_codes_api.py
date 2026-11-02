import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.api.blocker_routes import reason_codes_router
from app.api.worker_task_routes import get_worker_id
from app.config import (
    DEVELOPMENT_BLOCKER_REASON_CODES,
    settings,
)

API = "/api/v1/worker/blockers/reason-codes"
TOKEN = "test-worker-token"


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(settings, "app_env", "development")
    monkeypatch.setattr(settings, "demo_worker_token", SecretStr(TOKEN))
    monkeypatch.setattr(settings, "blocker_reason_codes", ("TEAM_ACCESS",))
    monkeypatch.setattr(settings, "blocker_reason_codes_approved", False)

    app = FastAPI()
    app.include_router(reason_codes_router, prefix="/api/v1")
    return TestClient(app)


def test_reason_codes_requires_worker_authentication(client):
    response = client.get(API)

    assert response.status_code == 401


def test_reason_codes_returns_only_configured_codes(client):
    response = client.get(
        API,
        headers={"Authorization": f"Bearer {TOKEN}"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "reason_codes": [{"code": "TEAM_ACCESS"}],
    }


def test_reason_codes_includes_other_when_configured(client, monkeypatch):
    monkeypatch.setattr(
        settings,
        "blocker_reason_codes",
        ("DEV_ACCESS", "DEV_EQUIPMENT", "OTHER"),
    )

    response = client.get(
        API,
        headers={"Authorization": f"Bearer {TOKEN}"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "reason_codes": [
            {"code": "DEV_ACCESS"},
            {"code": "DEV_EQUIPMENT"},
            {"code": "OTHER"},
        ],
    }


def test_development_default_reason_codes_include_other():
    assert DEVELOPMENT_BLOCKER_REASON_CODES == (
        "DEV_ACCESS",
        "DEV_EQUIPMENT",
        "OTHER",
    )


@pytest.mark.parametrize("codes", [(), None])
def test_empty_or_unavailable_configuration_fails_closed(
    client,
    monkeypatch,
    codes,
):
    monkeypatch.setattr(settings, "blocker_reason_codes", codes)

    response = client.get(
        API,
        headers={"Authorization": f"Bearer {TOKEN}"},
    )

    assert response.status_code == 503


@pytest.mark.parametrize(
    "codes",
    [("lowercase",), ("DUPLICATE", "DUPLICATE")],
)
def test_invalid_configuration_fails_closed(
    client,
    monkeypatch,
    codes,
):
    monkeypatch.setattr(settings, "blocker_reason_codes", codes)

    response = client.get(
        API,
        headers={"Authorization": f"Bearer {TOKEN}"},
    )

    assert response.status_code == 503


def test_production_codes_require_explicit_approval(client, monkeypatch):
    monkeypatch.setattr(settings, "app_env", "production")
    monkeypatch.setattr(settings, "blocker_reason_codes", ("TEAM_ACCESS",))
    monkeypatch.setattr(settings, "blocker_reason_codes_approved", False)
    client.app.dependency_overrides[get_worker_id] = lambda: "worker-test"

    response = client.get(API)

    assert response.status_code == 503


def test_approved_production_codes_are_returned(client, monkeypatch):
    monkeypatch.setattr(settings, "app_env", "production")
    monkeypatch.setattr(settings, "blocker_reason_codes", ("TEAM_ACCESS",))
    monkeypatch.setattr(settings, "blocker_reason_codes_approved", True)
    client.app.dependency_overrides[get_worker_id] = lambda: "worker-test"

    response = client.get(API)

    assert response.status_code == 200
    assert response.json() == {
        "reason_codes": [{"code": "TEAM_ACCESS"}],
    }
