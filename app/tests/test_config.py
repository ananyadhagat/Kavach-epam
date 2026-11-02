import importlib

import pytest
from pydantic import ValidationError

from app.config import BASE_DIR, Settings
from app.tests.conftest import AUTH, DEMO_TOKEN


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch):
    # Ignore any developer .env so defaults can be checked reliably.
    for name in (
        "APP_ENV", "DEMO_WORKER_TOKEN", "DEMO_WORKER_ID",
        "MAX_IMAGE_SIZE_BYTES", "MAX_GPS_ACCURACY_METERS",
        "BLOCKER_REASON_CODES", "BLOCKER_REASON_CODES_APPROVED",
        "DEMO_OPERATOR_TOKEN", "DEMO_OPERATOR_ID",
        "DATABASE_URL", "TEST_DATABASE_URL",
        "SEED_DEMO_DATA", "DATABASE_CONNECT_TIMEOUT_SECONDS",
        "KAVACH_DEMO_RESET_ENABLED", "KAVACH_DEMO_RESET_LOCAL_ONLY",
    ):
        monkeypatch.delenv(name, raising=False)


def test_application_imports():
    module = importlib.import_module("app.main")
    assert module.app.title == "KAVACH Field Worker Execution Task"


def test_health_endpoint(client):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "KAVACH Field Worker Execution Task",
    }


def test_defaults(clean_env):
    config = Settings(_env_file=None)

    assert config.app_env == "development"
    assert config.max_image_size_bytes == 5 * 1024 * 1024
    assert config.max_gps_accuracy_meters == 100.0
    # Development-only examples are not represented as mentor-approved.
    assert config.blocker_reason_codes == (
        "DEV_ACCESS",
        "DEV_EQUIPMENT",
        "OTHER",
    )
    assert config.blocker_reason_codes_approved is False
    assert config.demo_operator_id == "operator-demo"
    assert config.demo_worker_id == "worker-001"
    # No database is assumed: startup refuses to run without DATABASE_URL.
    assert config.database_url is None
    assert config.test_database_url is None
    assert config.seed_demo_data is False
    assert config.kavach_demo_reset_enabled is False
    assert config.kavach_demo_reset_local_only is False


def test_database_url_from_environment_is_secret(clean_env, monkeypatch):
    monkeypatch.setenv(
        "DATABASE_URL", "postgresql+asyncpg://kavach:pw-123456@db/kavach"
    )
    monkeypatch.setenv("SEED_DEMO_DATA", "true")

    config = Settings(_env_file=None)

    assert config.database_url.get_secret_value().endswith("@db/kavach")
    assert "pw-123456" not in repr(config)
    assert config.seed_demo_data is True


def test_env_file_is_resolved_from_project_root():
    assert Settings.model_config["env_file"] == BASE_DIR / ".env"


def test_environment_variables_override_defaults(clean_env, monkeypatch):
    monkeypatch.setenv("DEMO_WORKER_TOKEN", "override-token-123")
    monkeypatch.setenv("BLOCKER_REASON_CODES", '["CODE_A", "CODE_B"]')
    monkeypatch.setenv("MAX_GPS_ACCURACY_METERS", "25.5")
    monkeypatch.setenv("APP_ENV", "production")

    config = Settings(_env_file=None)

    assert config.demo_worker_token.get_secret_value() == "override-token-123"
    assert config.blocker_reason_codes == ("CODE_A", "CODE_B")
    assert config.max_gps_accuracy_meters == 25.5
    assert config.app_env == "production"


def test_demo_reset_requires_explicit_environment_flags(clean_env, monkeypatch):
    disabled = Settings(_env_file=None)
    assert disabled.kavach_demo_reset_enabled is False
    assert disabled.kavach_demo_reset_local_only is False

    monkeypatch.setenv("KAVACH_DEMO_RESET_ENABLED", "true")
    monkeypatch.setenv("KAVACH_DEMO_RESET_LOCAL_ONLY", "true")
    enabled = Settings(_env_file=None)
    assert enabled.kavach_demo_reset_enabled is True
    assert enabled.kavach_demo_reset_local_only is True


def test_production_blocker_codes_require_explicit_approval(
    clean_env, monkeypatch
):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("BLOCKER_REASON_CODES", '["TEAM_CODE"]')

    config = Settings(_env_file=None)

    assert config.blocker_reason_codes == ("TEAM_CODE",)
    assert config.blocker_reason_codes_approved is False


def test_production_blocker_codes_can_be_marked_approved(
    clean_env, monkeypatch
):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("BLOCKER_REASON_CODES", '["TEAM_CODE"]')
    monkeypatch.setenv("BLOCKER_REASON_CODES_APPROVED", "true")

    config = Settings(_env_file=None)

    assert config.blocker_reason_codes == ("TEAM_CODE",)
    assert config.blocker_reason_codes_approved is True


def test_env_file_values_are_loaded(clean_env, tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("DEMO_WORKER_TOKEN=file-token-456\n", encoding="utf-8")

    config = Settings(_env_file=env_file)

    assert config.demo_worker_token.get_secret_value() == "file-token-456"


def test_environment_variable_beats_env_file(clean_env, tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("DEMO_WORKER_TOKEN=file-token-456\n", encoding="utf-8")
    monkeypatch.setenv("DEMO_WORKER_TOKEN", "env-var-token-789")

    config = Settings(_env_file=env_file)

    assert config.demo_worker_token.get_secret_value() == "env-var-token-789"


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("MAX_GPS_ACCURACY_METERS", "0"),
        ("MAX_GPS_ACCURACY_METERS", "-5"),
        ("MAX_GPS_ACCURACY_METERS", "not-a-number"),
        ("MAX_IMAGE_SIZE_BYTES", "0"),
        ("APP_ENV", "staging"),
        ("DEMO_WORKER_TOKEN", "short"),
        ("BLOCKER_REASON_CODES", '["lower_case"]'),
        ("BLOCKER_REASON_CODES", '["CODE_A\\n"]'),
        ("BLOCKER_REASON_CODES", '["CODE_A", "CODE_A"]'),
        ("DEMO_OPERATOR_TOKEN", "short"),
        # The worker and operator tokens must differ.
        ("DEMO_OPERATOR_TOKEN", "dev-worker-token"),
        ("DATABASE_CONNECT_TIMEOUT_SECONDS", "0"),
        ("SEED_DEMO_DATA", "sometimes"),
    ],
)
def test_invalid_configuration_is_rejected(clean_env, monkeypatch, name, value):
    monkeypatch.setenv(name, value)

    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_malformed_reason_code_list_is_rejected(clean_env, monkeypatch):
    from pydantic_settings import SettingsError

    monkeypatch.setenv("BLOCKER_REASON_CODES", "not-json")

    with pytest.raises(SettingsError):
        Settings(_env_file=None)


def test_token_is_not_exposed_in_repr(clean_env):
    config = Settings(_env_file=None)

    assert "dev-worker-token" not in repr(config)
    assert "dev-worker-token" not in str(config.demo_worker_token)


def test_responses_do_not_expose_token(client):
    responses = [
        client.get("/health"),
        client.get("/openapi.json"),
        client.get("/api/v1/worker/tasks", headers=AUTH),
        client.get("/api/v1/worker/tasks"),
    ]

    for response in responses:
        assert DEMO_TOKEN not in response.text
