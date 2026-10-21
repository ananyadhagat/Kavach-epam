import pytest

from app.config import settings
from app.schemas.worker_task import TaskStatus
from app.tests.conftest import (
    API,
    AUTH,
    OTHER_WORKER_ID,
    add_task,
    location_payload,
    location_records,
    make_task,
    post_action,
)


def arrival(client, task_id="TASK-001", **overrides):
    payload = location_payload(**{"event_type": "ARRIVAL", **overrides})
    return client.post(f"{API}/{task_id}/arrival", json=payload,
                       headers=AUTH)


def completion_location(client, task_id="TASK-001", **overrides):
    payload = location_payload(**{"event_type": "COMPLETION", **overrides})
    return client.post(f"{API}/{task_id}/completion-location", json=payload,
                       headers=AUTH)


def task_body(client, task_id="TASK-001"):
    return client.get(f"{API}/{task_id}", headers=AUTH).json()


@pytest.fixture
def accepted(client):
    post_action(client, "TASK-001", "accept")
    return client


@pytest.fixture
def in_progress(accepted):
    post_action(accepted, "TASK-001", "start")
    return accepted


def test_valid_arrival(accepted):
    response = arrival(accepted)

    assert response.status_code == 200
    event = response.json()["location_event"]
    assert event["event_type"] == "ARRIVAL"
    assert event["capture_status"] == "CAPTURED"
    assert event["latitude"] == 23.2599
    assert event["longitude"] == 77.4126
    assert event["accuracy_meters"] == 10.0
    assert event["task_id"] == "TASK-001"
    assert event["worker_id"] == "worker-001"
    assert event["received_at_server"]

    assert task_body(accepted)["arrival_location_event_id"] == (
        event["location_event_id"]
    )


def test_valid_completion_location(in_progress):
    response = completion_location(in_progress)

    assert response.status_code == 200
    event = response.json()["location_event"]
    assert event["event_type"] == "COMPLETION"
    assert task_body(in_progress)["completion_location_event_id"] == (
        event["location_event_id"]
    )


@pytest.mark.parametrize("latitude", [90.0001, -90.0001, 1000, -1000])
def test_invalid_latitude(accepted, latitude):
    response = arrival(accepted, latitude=latitude)

    assert response.status_code == 422
    assert location_records(accepted) == {}


@pytest.mark.parametrize("longitude", [180.0001, -180.0001, 999])
def test_invalid_longitude(accepted, longitude):
    response = arrival(accepted, longitude=longitude)

    assert response.status_code == 422
    assert location_records(accepted) == {}


@pytest.mark.parametrize(
    ("latitude", "longitude"),
    [(90, 180), (-90, -180), (0, 0)],
)
def test_boundary_coordinates_are_valid(accepted, latitude, longitude):
    assert arrival(accepted, latitude=latitude,
                   longitude=longitude).status_code == 200


@pytest.mark.parametrize(
    "overrides",
    [
        {"latitude": None},
        {"longitude": None},
        {"latitude": None, "longitude": None},
        {"latitude": "north"},
        {"longitude": [1, 2]},
        {"accuracy_meters": None},
    ],
    ids=["no-lat", "no-lon", "no-coords", "text-lat", "list-lon",
         "no-accuracy"],
)
def test_missing_or_malformed_coordinates(accepted, overrides):
    response = arrival(accepted, **overrides)

    assert response.status_code == 422
    assert location_records(accepted) == {}


@pytest.mark.parametrize("accuracy", [0, -1, 100_001])
def test_out_of_range_accuracy_rejected(accepted, accuracy):
    response = arrival(accepted, accuracy_meters=accuracy)

    assert response.status_code == 422


@pytest.mark.parametrize("accuracy", [0.5, 50, 100])
def test_accuracy_within_limit_is_captured(accepted, accuracy):
    event = arrival(accepted, accuracy_meters=accuracy).json()[
        "location_event"
    ]

    assert event["capture_status"] == "CAPTURED"
    assert event["latitude"] is not None


@pytest.mark.parametrize("accuracy", [100.01, 500, 100_000])
def test_accuracy_beyond_limit_is_marked_inaccurate(accepted, accuracy):
    response = arrival(accepted, accuracy_meters=accuracy)

    assert response.status_code == 200
    event = response.json()["location_event"]
    assert event["capture_status"] == "INACCURATE"
    # Coordinates are dropped when they cannot be trusted.
    assert event["latitude"] is None
    assert event["longitude"] is None
    assert event["accuracy_meters"] == accuracy


def test_accuracy_limit_follows_configuration(accepted, monkeypatch):
    monkeypatch.setattr(settings, "max_gps_accuracy_meters", 5.0)

    event = arrival(accepted, accuracy_meters=10).json()["location_event"]

    assert event["capture_status"] == "INACCURATE"


@pytest.mark.parametrize("status", ["UNAVAILABLE", "INACCURATE"])
def test_unavailable_gps_without_coordinates(accepted, status):
    response = arrival(accepted, capture_status=status, latitude=None,
                       longitude=None, accuracy_meters=None)

    assert response.status_code == 200
    assert response.json()["location_event"]["capture_status"] == status


def test_unavailable_gps_must_not_include_coordinates(accepted):
    response = arrival(accepted, capture_status="UNAVAILABLE")

    assert response.status_code == 422


@pytest.mark.parametrize("event_type", ["DEPARTURE", "", None, "arrival"])
def test_invalid_event_type(accepted, event_type):
    response = arrival(accepted, event_type=event_type)

    assert response.status_code == 422


def test_event_type_must_match_endpoint(in_progress):
    wrong_arrival = in_progress.post(
        f"{API}/TASK-001/arrival", json=location_payload("COMPLETION"),
        headers=AUTH,
    )
    wrong_completion = in_progress.post(
        f"{API}/TASK-001/completion-location",
        json=location_payload("ARRIVAL"), headers=AUTH,
    )

    assert wrong_arrival.status_code == 422
    assert wrong_arrival.json() == {"detail": "event_type must be ARRIVAL."}
    assert wrong_completion.status_code == 422
    assert location_records(in_progress) == {}


def test_extra_fields_rejected(accepted):
    response = arrival(accepted, worker_id="someone-else")

    assert response.status_code == 422


def test_nonexistent_task(client):
    assert arrival(client, task_id="NOPE").status_code == 404
    assert completion_location(client, task_id="NOPE").status_code == 404


def test_other_workers_task(client):
    add_task(client, make_task("OTHER-1", worker_id=OTHER_WORKER_ID,
                               status=TaskStatus.IN_PROGRESS))

    assert arrival(client, task_id="OTHER-1").status_code == 404
    assert completion_location(client, task_id="OTHER-1").status_code == 404
    assert location_records(client) == {}


def test_unauthenticated(accepted):
    response = accepted.post(f"{API}/TASK-001/arrival",
                             json=location_payload("ARRIVAL"))

    assert response.status_code == 401
    assert location_records(accepted) == {}


def test_repeated_arrival_keeps_history_and_latest_reference(accepted):
    # Policy: re-capture is allowed (e.g. after a poor GPS fix). Every event
    # is retained, and the task references the most recent one.
    first = arrival(accepted, accuracy_meters=500).json()["location_event"]
    second = arrival(accepted).json()["location_event"]

    assert first["location_event_id"] != second["location_event_id"]
    assert len(location_records(accepted)) == 2
    assert task_body(accepted)["arrival_location_event_id"] == (
        second["location_event_id"]
    )


def test_repeated_completion_location_keeps_latest(in_progress):
    completion_location(in_progress)
    second = completion_location(in_progress).json()["location_event"]

    assert task_body(in_progress)["completion_location_event_id"] == (
        second["location_event_id"]
    )


@pytest.mark.parametrize("setup", [[], ["reject"]])
def test_arrival_not_allowed_before_acceptance_or_after_reject(client, setup):
    for action in setup:
        post_action(client, "TASK-001", action)

    response = arrival(client)

    assert response.status_code == 409
    assert location_records(client) == {}


@pytest.mark.parametrize(
    "setup", [["accept", "start"], ["accept", "start", "pause"]]
)
def test_arrival_allowed_during_work(client, setup):
    for action in setup:
        post_action(client, "TASK-001", action)

    assert arrival(client).status_code == 200


@pytest.mark.parametrize("setup", [[], ["accept"], ["reject"]])
def test_completion_location_requires_active_work(client, setup):
    for action in setup:
        post_action(client, "TASK-001", action)

    response = completion_location(client)

    assert response.status_code == 409
    assert location_records(client) == {}


def test_completion_location_allowed_while_paused(in_progress):
    post_action(in_progress, "TASK-001", "pause")

    assert completion_location(in_progress).status_code == 200
