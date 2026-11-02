"""Start prerequisites: stored BEFORE evidence and a captured arrival.

The validator tests need no database. The API tests use the `client`
fixture, which requires the PostgreSQL test database.
"""

import pytest

from app.schemas.evidence import EvidenceRecord, EvidenceType
from app.schemas.location_event import (
    LocationCaptureStatus,
    LocationEventRecord,
    LocationEventType,
)
from app.tests.conftest import (
    API,
    AUTH,
    add_task,
    capture_arrival,
    make_image,
    make_task,
    post_action,
    task_status,
    upload,
)
from app.validators.start_validator import (
    StartPrerequisiteError,
    validate_start_prerequisites,
)


def evidence(evidence_type=EvidenceType.BEFORE, task_id="TASK-1",
             worker_id="worker-001", number=1) -> EvidenceRecord:
    return EvidenceRecord(
        evidence_id=f"00000000-0000-0000-0000-{number:012d}",
        task_id=task_id,
        worker_id=worker_id,
        evidence_type=evidence_type,
        storage_key=f"{number:032x}.png",
        original_filename="photo.png",
        mime_type="image/png",
        size_bytes=100,
        sha256=f"{number:064x}",
    )


def arrival(capture_status=LocationCaptureStatus.CAPTURED, task_id="TASK-1",
            worker_id="worker-001",
            event_type=LocationEventType.ARRIVAL) -> LocationEventRecord:
    captured = capture_status == LocationCaptureStatus.CAPTURED
    return LocationEventRecord(
        location_event_id="00000000-0000-0000-0000-0000000000aa",
        task_id=task_id,
        worker_id=worker_id,
        event_type=event_type,
        capture_status=capture_status,
        latitude=1.0 if captured else None,
        longitude=2.0 if captured else None,
        accuracy_meters=10.0 if captured else None,
    )


@pytest.fixture
def task():
    return make_task("TASK-1")


# ---------------------------------------------------------------------------
# Validator (no database)
# ---------------------------------------------------------------------------

def test_no_evidence_is_rejected(task):
    # A photo that was only selected locally, is still pending upload or
    # failed upload has no server record, so the list is empty.
    with pytest.raises(StartPrerequisiteError, match="BEFORE image"):
        validate_start_prerequisites(task, [], arrival())


def test_after_evidence_alone_is_rejected(task):
    with pytest.raises(StartPrerequisiteError, match="BEFORE image"):
        validate_start_prerequisites(task, [evidence(EvidenceType.AFTER)],
                                     arrival())


def test_before_evidence_of_another_task_is_rejected(task):
    with pytest.raises(StartPrerequisiteError, match="BEFORE image"):
        validate_start_prerequisites(task, [evidence(task_id="OTHER")],
                                     arrival())


def test_before_evidence_of_another_worker_is_rejected(task):
    with pytest.raises(StartPrerequisiteError, match="BEFORE image"):
        validate_start_prerequisites(
            task, [evidence(worker_id="worker-002")], arrival()
        )


def test_stored_before_and_captured_arrival_are_accepted(task):
    validate_start_prerequisites(task, [evidence()], arrival())


def test_one_valid_record_among_others_is_enough(task):
    validate_start_prerequisites(task, [
        evidence(EvidenceType.AFTER, number=1),
        evidence(task_id="OTHER", number=2),
        evidence(number=3),
    ], arrival())


def test_missing_arrival_is_rejected(task):
    with pytest.raises(StartPrerequisiteError, match="arrival location"):
        validate_start_prerequisites(task, [evidence()], None)


@pytest.mark.parametrize(
    "event",
    [
        # No exception policy for unavailable GPS has been agreed.
        arrival(LocationCaptureStatus.UNAVAILABLE),
        arrival(LocationCaptureStatus.INACCURATE),
        arrival(task_id="OTHER"),
        arrival(worker_id="worker-002"),
        arrival(event_type=LocationEventType.COMPLETION),
    ],
    ids=["unavailable", "inaccurate", "other-task", "other-worker",
         "completion-event"],
)
def test_unusable_arrival_is_rejected(task, event):
    with pytest.raises(StartPrerequisiteError, match="arrival location"):
        validate_start_prerequisites(task, [evidence()], event)


# ---------------------------------------------------------------------------
# API (requires the PostgreSQL test database)
# ---------------------------------------------------------------------------

def start(client, task_id="TASK-001"):
    # Calls the endpoint directly; post_action would add the prerequisites.
    return client.post(f"{API}/{task_id}/start", headers=AUTH)


def test_start_without_before_evidence_is_rejected(client):
    assert capture_arrival(client, "TASK-001").status_code == 200

    response = start(client)

    assert response.status_code == 422
    assert "BEFORE image" in response.json()["detail"]
    assert task_status(client, "TASK-001") == "ACCEPTED"


def test_start_without_arrival_is_rejected(client):
    assert upload(client, "TASK-001", "BEFORE").status_code == 200

    response = start(client)

    assert response.status_code == 422
    assert "arrival location" in response.json()["detail"]
    assert task_status(client, "TASK-001") == "ACCEPTED"


@pytest.mark.parametrize(
    "overrides",
    [
        {"capture_status": "UNAVAILABLE", "latitude": None,
         "longitude": None, "accuracy_meters": None},
        {"accuracy_meters": 5000.0},  # stored as INACCURATE
    ],
    ids=["unavailable", "inaccurate"],
)
def test_start_with_uncaptured_arrival_is_rejected(client, overrides):
    assert upload(client, "TASK-001", "BEFORE").status_code == 200
    assert capture_arrival(client, "TASK-001", **overrides).status_code == 200

    response = start(client)

    assert response.status_code == 422
    assert "arrival location" in response.json()["detail"]


def test_start_after_rejected_upload_is_rejected(client):
    capture_arrival(client, "TASK-001")
    assert upload(client, "TASK-001", content=b"not an image").status_code == 422

    assert start(client).status_code == 422
    assert task_status(client, "TASK-001") == "ACCEPTED"


def test_after_evidence_cannot_stand_in_for_before(client):
    capture_arrival(client, "TASK-001")
    # AFTER evidence is refused before work starts, so it can never
    # satisfy the BEFORE prerequisite.
    assert upload(client, "TASK-001", "AFTER").status_code == 409

    assert start(client).status_code == 422
    assert task_status(client, "TASK-001") == "ACCEPTED"


def test_before_evidence_of_another_task_does_not_count(client):
    add_task(client, make_task("MINE-2"))
    assert upload(client, "MINE-2", "BEFORE").status_code == 200
    capture_arrival(client, "TASK-001")

    assert start(client).status_code == 422
    assert task_status(client, "TASK-001") == "ACCEPTED"


def test_start_with_both_prerequisites_is_allowed(client):
    before = upload(client, "TASK-001", "BEFORE",
                    content=make_image("JPEG"), content_type="image/jpeg")
    assert before.status_code == 200
    assert capture_arrival(client, "TASK-001").status_code == 200

    response = start(client)

    assert response.status_code == 200
    assert response.json()["task"]["status"] == "IN_PROGRESS"


def test_resume_does_not_repeat_the_check(client):
    post_action(client, "TASK-001", "start")
    post_action(client, "TASK-001", "pause")

    assert start(client).status_code == 200
    assert task_status(client, "TASK-001") == "IN_PROGRESS"
