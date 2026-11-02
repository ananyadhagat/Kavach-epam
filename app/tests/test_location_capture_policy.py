from contextlib import AbstractAsyncContextManager
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.config import settings
from app.schemas.location_event import (
    LocationCaptureStatus,
    LocationEventCreate,
    LocationEventRecord,
    LocationEventType,
)
from app.schemas.worker_task import (
    TaskLocation,
    TaskPriority,
    TaskStatus,
    WorkerTask,
)
from app.services.field_work_service import FieldWorkService
from app.services.location_capture_service import LocationCaptureService


def make_task() -> WorkerTask:
    return WorkerTask(
        task_id="TASK-GPS",
        incident_id="INC-GPS",
        assigned_worker_id="worker-001",
        title="Inspect field location",
        description="Record an arrival position.",
        priority=TaskPriority.MEDIUM,
        status=TaskStatus.ACCEPTED,
        location=TaskLocation(
            latitude=28.6,
            longitude=77.2,
            address="Field location",
        ),
    )


class FakeTaskRepository:
    def __init__(self, task: WorkerTask):
        self.task = task

    async def get_for_worker(
        self, task_id: str, worker_id: str, for_update: bool = False
    ):
        if (
            task_id != self.task.task_id
            or worker_id != self.task.assigned_worker_id
        ):
            return None
        return self.task

    async def set_task_references(
        self,
        task_id: str,
        arrival_location_event_id: str | None = None,
        completion_location_event_id: str | None = None,
    ):
        if arrival_location_event_id is not None:
            self.task.arrival_location_event_id = arrival_location_event_id
        if completion_location_event_id is not None:
            self.task.completion_location_event_id = (
                completion_location_event_id
            )
        return self.task


class FakeLocationRepository:
    def __init__(self):
        self.records: list[LocationEventRecord] = []

    async def save(self, record: LocationEventRecord) -> LocationEventRecord:
        self.records.append(record)
        return record

    async def get(self, event_id: str) -> LocationEventRecord | None:
        return next(
            (record for record in self.records
             if record.location_event_id == event_id),
            None,
        )

    async def list_for_task(
        self, task_id: str
    ) -> list[LocationEventRecord]:
        return [record for record in self.records if record.task_id == task_id]

    async def latest_for_task(
        self, task_id: str
    ) -> list[LocationEventRecord]:
        records = [r for r in self.records if r.task_id == task_id]
        latest = []
        for event_type in LocationEventType:
            matches = [r for r in records if r.event_type == event_type]
            if matches:
                latest.append(matches[-1])
        return latest


class FakeUnitOfWork(AbstractAsyncContextManager):
    def __init__(self, task_repo, location_repo):
        self.tasks = task_repo
        self.locations = location_repo

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False


def make_factory(task: WorkerTask, locations: FakeLocationRepository):
    tasks = FakeTaskRepository(task)

    def factory():
        return FakeUnitOfWork(tasks, locations)

    return factory


def arrival_payload(accuracy: float) -> LocationEventCreate:
    return LocationEventCreate(
        event_type=LocationEventType.ARRIVAL,
        capture_status=LocationCaptureStatus.CAPTURED,
        latitude=28.6139,
        longitude=77.209,
        accuracy_meters=accuracy,
        captured_at_device=datetime.now(timezone.utc),
    )


@pytest.mark.asyncio
async def test_poor_quality_event_is_audited_but_not_referenced_for_progress(
    monkeypatch,
):
    monkeypatch.setattr(settings, "max_gps_accuracy_meters", 100.0)
    task = make_task()
    locations = FakeLocationRepository()
    service = LocationCaptureService(make_factory(task, locations))

    event = await service.capture(
        task.task_id, "worker-001", arrival_payload(103.0)
    )

    assert event.capture_status == LocationCaptureStatus.INACCURATE
    assert event.accuracy_meters == 103.0
    assert event.latitude is None
    assert event.longitude is None
    assert task.arrival_location_event_id is None
    assert len(locations.records) == 1


@pytest.mark.asyncio
async def test_accuracy_acceptance_uses_central_backend_setting(monkeypatch):
    monkeypatch.setattr(settings, "max_gps_accuracy_meters", 50.0)
    task = make_task()
    locations = FakeLocationRepository()
    service = LocationCaptureService(make_factory(task, locations))

    event = await service.capture(
        task.task_id, "worker-001", arrival_payload(75.0)
    )

    assert event.capture_status == LocationCaptureStatus.INACCURATE
    assert task.arrival_location_event_id is None


@pytest.mark.asyncio
async def test_acceptable_arrival_is_saved_once_and_retries_return_same_event(
    monkeypatch,
):
    monkeypatch.setattr(settings, "max_gps_accuracy_meters", 100.0)
    task = make_task()
    locations = FakeLocationRepository()
    service = LocationCaptureService(make_factory(task, locations))

    accepted = await service.capture(
        task.task_id, "worker-001", arrival_payload(12.0)
    )
    retry = await service.capture(
        task.task_id, "worker-001", arrival_payload(7.0)
    )

    assert accepted.capture_status == LocationCaptureStatus.CAPTURED
    assert task.arrival_location_event_id == accepted.location_event_id
    assert retry.location_event_id == accepted.location_event_id
    assert len(locations.records) == 1


@pytest.mark.asyncio
async def test_task_details_expose_latest_quality_and_configured_threshold(
    monkeypatch,
):
    monkeypatch.setattr(settings, "max_gps_accuracy_meters", 100.0)
    task = make_task()
    locations = FakeLocationRepository()
    service = LocationCaptureService(make_factory(task, locations))
    event = await service.capture(
        task.task_id, "worker-001", arrival_payload(103.0)
    )
    details_service = FieldWorkService(
        make_factory(task, locations),
        state_service=SimpleNamespace(),
    )

    details = await details_service.get_task(task.task_id, "worker-001")

    assert details.arrival_location_accepted is False
    assert details.gps_accuracy_threshold_meters == 100.0
    assert details.latest_arrival_location.location_event_id == (
        event.location_event_id
    )
    assert details.latest_arrival_location.capture_status == (
        LocationCaptureStatus.INACCURATE
    )
    assert details.latest_arrival_location.accuracy_meters == 103.0
    assert details.latest_arrival_location.accepted_for_progress is False
    assert "configured acceptance threshold" in (
        details.latest_arrival_location.rejection_reason
    )


@pytest.mark.asyncio
async def test_acceptable_fix_after_poor_audit_event_becomes_arrival_reference(
    monkeypatch,
):
    monkeypatch.setattr(settings, "max_gps_accuracy_meters", 100.0)
    task = make_task()
    locations = FakeLocationRepository()
    service = LocationCaptureService(make_factory(task, locations))

    poor = await service.capture(
        task.task_id, "worker-001", arrival_payload(103.0)
    )
    accepted = await service.capture(
        task.task_id, "worker-001", arrival_payload(25.0)
    )
    details_service = FieldWorkService(
        make_factory(task, locations),
        state_service=SimpleNamespace(),
    )
    details = await details_service.get_task(task.task_id, "worker-001")

    assert poor.capture_status == LocationCaptureStatus.INACCURATE
    assert accepted.capture_status == LocationCaptureStatus.CAPTURED
    assert task.arrival_location_event_id == accepted.location_event_id
    assert len(locations.records) == 2
    assert details.arrival_location_accepted is True
    assert details.accepted_arrival_location.location_event_id == (
        accepted.location_event_id
    )
    assert details.accepted_arrival_location.latitude == accepted.latitude
    assert details.accepted_arrival_location.longitude == accepted.longitude
    assert details.accepted_arrival_location.accepted_for_progress is True
    assert details.latest_arrival_location.location_event_id == (
        accepted.location_event_id
    )
    assert details.latest_arrival_location.accepted_for_progress is True


@pytest.mark.asyncio
async def test_details_keep_accepted_arrival_separate_from_later_audit_event(
    monkeypatch,
):
    monkeypatch.setattr(settings, "max_gps_accuracy_meters", 100.0)
    task = make_task()
    locations = FakeLocationRepository()
    service = LocationCaptureService(make_factory(task, locations))
    accepted = await service.capture(
        task.task_id, "worker-001", arrival_payload(25.0)
    )
    later_audit_event = LocationEventRecord(
        location_event_id="later-inaccurate-event",
        task_id=task.task_id,
        worker_id="worker-001",
        event_type=LocationEventType.ARRIVAL,
        capture_status=LocationCaptureStatus.INACCURATE,
        latitude=None,
        longitude=None,
        accuracy_meters=103.0,
        captured_at_device=datetime.now(timezone.utc),
        received_at_server=datetime.now(timezone.utc),
    )
    locations.records.append(later_audit_event)
    details_service = FieldWorkService(
        make_factory(task, locations),
        state_service=SimpleNamespace(),
    )

    details = await details_service.get_task(task.task_id, "worker-001")

    assert details.arrival_location_accepted is True
    assert details.accepted_arrival_location.location_event_id == (
        accepted.location_event_id
    )
    assert details.latest_arrival_location.location_event_id == (
        later_audit_event.location_event_id
    )
    assert details.latest_arrival_location.accepted_for_progress is False
