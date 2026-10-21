import pytest

from app.schemas.location_event import (
    LocationCaptureStatus,
    LocationEventCreate,
    LocationEventType,
)
from app.schemas.worker_task import TaskStatus
from app.services.location_capture_service import LocationCaptureService
from app.tests.conftest import force_status


@pytest.mark.asyncio
async def test_gps_unavailable_is_recorded_without_coordinates(database):
    await force_status(database, "TASK-001", TaskStatus.ACCEPTED)

    service = LocationCaptureService(database.unit_of_work)

    payload = LocationEventCreate(
        event_type=LocationEventType.ARRIVAL,
        capture_status=LocationCaptureStatus.UNAVAILABLE,
        latitude=None,
        longitude=None,
        accuracy_meters=None,
    )

    result = await service.capture(
        "TASK-001",
        "worker-001",
        payload,
    )

    assert result.capture_status == LocationCaptureStatus.UNAVAILABLE
    assert result.latitude is None
    assert result.longitude is None


@pytest.mark.asyncio
async def test_gps_accuracy_is_checked(database):
    await force_status(database, "TASK-001", TaskStatus.ACCEPTED)

    service = LocationCaptureService(database.unit_of_work)

    payload = LocationEventCreate(
        event_type=LocationEventType.ARRIVAL,
        capture_status=LocationCaptureStatus.CAPTURED,
        latitude=23.2599,
        longitude=77.4126,
        accuracy_meters=500,
    )

    result = await service.capture("TASK-001", "worker-001", payload)

    assert result.capture_status == LocationCaptureStatus.INACCURATE
    assert result.latitude is None
    assert result.longitude is None
