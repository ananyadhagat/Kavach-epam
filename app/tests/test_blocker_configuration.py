import pytest
from fastapi import HTTPException

from app.config import settings
from app.schemas.blocker import BlockerReport
from app.services.blocker_service import BlockerService
from app.services.task_state_service import TaskStateService


class UnitOfWorkReached(RuntimeError):
    pass


def fail_if_database_is_reached():
    raise UnitOfWorkReached


def service() -> BlockerService:
    return BlockerService(fail_if_database_is_reached, TaskStateService())


def report(reason_code: str = "TEAM_ACCESS") -> BlockerReport:
    return BlockerReport(
        reason_code=reason_code,
        description="Access is unavailable.",
    )


@pytest.fixture(autouse=True)
def clear_reason_code_settings(monkeypatch):
    monkeypatch.setattr(settings, "app_env", "development")
    monkeypatch.setattr(settings, "blocker_reason_codes", ())
    monkeypatch.setattr(settings, "blocker_reason_codes_approved", False)


@pytest.mark.asyncio
async def test_missing_reason_codes_returns_service_unavailable_without_db():
    with pytest.raises(HTTPException) as exc_info:
        await service().report("TASK-1", "worker-1", report())

    assert exc_info.value.status_code == 503
    assert "BLOCKER_REASON_CODES" in exc_info.value.detail


@pytest.mark.asyncio
async def test_unconfigured_reason_code_returns_client_error_without_db(
    monkeypatch,
):
    monkeypatch.setattr(settings, "blocker_reason_codes", ("TEAM_ACCESS",))

    with pytest.raises(HTTPException) as exc_info:
        await service().report("TASK-1", "worker-1", report("TEAM_OTHER"))

    assert exc_info.value.status_code == 422
    assert "Invalid blocker reason code" in exc_info.value.detail


@pytest.mark.asyncio
async def test_configured_reason_code_passes_configuration_checks(
    monkeypatch,
):
    monkeypatch.setattr(settings, "blocker_reason_codes", ("TEAM_ACCESS",))

    with pytest.raises(UnitOfWorkReached):
        await service().report("TASK-1", "worker-1", report())


@pytest.mark.asyncio
async def test_other_reason_code_passes_configuration_checks(monkeypatch):
    monkeypatch.setattr(
        settings,
        "blocker_reason_codes",
        ("DEV_ACCESS", "DEV_EQUIPMENT", "OTHER"),
    )

    with pytest.raises(UnitOfWorkReached):
        await service().report(
            "TASK-1",
            "worker-1",
            BlockerReport(
                reason_code="OTHER",
                description="The assigned access method is unavailable.",
            ),
        )


@pytest.mark.asyncio
async def test_production_requires_explicit_reason_code_approval(
    monkeypatch,
):
    monkeypatch.setattr(settings, "app_env", "production")
    monkeypatch.setattr(settings, "blocker_reason_codes", ("TEAM_ACCESS",))

    with pytest.raises(HTTPException) as exc_info:
        await service().report("TASK-1", "worker-1", report())

    assert exc_info.value.status_code == 503
    assert "BLOCKER_REASON_CODES_APPROVED" in exc_info.value.detail


@pytest.mark.asyncio
async def test_approved_production_code_passes_configuration_checks(
    monkeypatch,
):
    monkeypatch.setattr(settings, "app_env", "production")
    monkeypatch.setattr(settings, "blocker_reason_codes", ("TEAM_ACCESS",))
    monkeypatch.setattr(settings, "blocker_reason_codes_approved", True)

    with pytest.raises(UnitOfWorkReached):
        await service().report("TASK-1", "worker-1", report())
