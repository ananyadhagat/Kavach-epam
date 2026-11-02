import pytest

from app.config import settings
from app.schemas.worker_task import TaskStatus
from app.tests.conftest import (
    API,
    AUTH,
    OTHER_WORKER_ID,
    add_task,
    make_task,
    post_action,
    set_status,
    task_status,
)


def status_of(client, task_id: str = "TASK-001") -> str:
    return client.get(f"{API}/{task_id}", headers=AUTH).json()["status"]


def test_list_tasks_only_returns_own_tasks(client):
    add_task(client, make_task("MINE-2"))
    add_task(client, make_task("OTHER-1", worker_id=OTHER_WORKER_ID))

    response = client.get(API, headers=AUTH)

    assert response.status_code == 200
    ids = {task["task_id"] for task in response.json()["tasks"]}
    assert ids == {"TASK-001", "MINE-2"}
    assert all(
        t["assigned_worker_id"] == "worker-001"
        for t in response.json()["tasks"]
    )


def test_get_assigned_task(client):
    response = client.get(f"{API}/TASK-001", headers=AUTH)

    assert response.status_code == 200
    body = response.json()
    assert body["task_id"] == "TASK-001"
    # This fixture starts in the accepted state for the execution workflow.
    assert body["status"] == "ACCEPTED"
    assert body["gps_accuracy_threshold_meters"] == (
        settings.max_gps_accuracy_meters
    )
    assert body["arrival_location_accepted"] is False
    assert body["completion_location_accepted"] is False
    assert body["accepted_arrival_location"] is None
    assert body["latest_arrival_location"] is None
    assert body["latest_completion_location"] is None
    assert [s["step_id"] for s in body["checklist"]] == [
        "STEP-001", "STEP-002", "STEP-003",
    ]
    assert {s["assigned_worker_id"] for s in body["checklist"]} == {
        "worker-001",
    }


def test_get_nonexistent_task(client):
    response = client.get(f"{API}/NOPE", headers=AUTH)

    assert response.status_code == 404
    assert response.json() == {"detail": "Task not found."}


def test_get_other_workers_task_is_hidden(client):
    add_task(client, make_task("OTHER-1", worker_id=OTHER_WORKER_ID))

    response = client.get(f"{API}/OTHER-1", headers=AUTH)

    # 404 rather than 403 so task IDs of other workers are not revealed.
    assert response.status_code == 404
    assert response.json() == {"detail": "Task not found."}


@pytest.mark.parametrize("action", ["start", "resume", "pause"])
def test_actions_on_other_workers_task_are_rejected(client, action):
    add_task(client, make_task("OTHER-1", worker_id=OTHER_WORKER_ID))

    response = post_action(client, "OTHER-1", action)

    assert response.status_code == 404
    assert task_status(client, "OTHER-1") == "ACCEPTED"


def test_worker_accepts_own_assigned_task(client):
    set_status(client, "TASK-001", "ASSIGNED")

    response = client.post(f"{API}/TASK-001/accept", headers=AUTH)

    assert response.status_code == 200
    assert response.json()["task"]["status"] == "ACCEPTED"
    assert status_of(client) == "ACCEPTED"


def test_worker_accepts_assigned_task_only_once(client):
    set_status(client, "TASK-001", "ASSIGNED")
    assert client.post(f"{API}/TASK-001/accept", headers=AUTH).status_code == 200

    response = client.post(f"{API}/TASK-001/accept", headers=AUTH)

    assert response.status_code == 409
    assert status_of(client) == "ACCEPTED"


def test_worker_cannot_accept_another_workers_task(client):
    add_task(client, make_task("OTHER-1", worker_id=OTHER_WORKER_ID,
                               status=TaskStatus.ASSIGNED))

    response = client.post(f"{API}/OTHER-1/accept", headers=AUTH)

    assert response.status_code == 404


def test_worker_rejects_assigned_task_with_persisted_reason(client):
    set_status(client, "TASK-001", "ASSIGNED")

    response = client.post(
        f"{API}/TASK-001/reject",
        json={"reason": "Unsafe work area"},
        headers=AUTH,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["task"]["status"] == "REJECTED"
    assert body["rejection"]["task_id"] == "TASK-001"
    assert body["rejection"]["worker_id"] == "worker-001"
    assert body["rejection"]["reason"] == "Unsafe work area"
    assert body["rejection"]["rejected_at"]
    assert status_of(client) == "REJECTED"


@pytest.mark.parametrize("reason", ["", " ", "x" * 501])
def test_rejection_requires_valid_reason(client, reason):
    set_status(client, "TASK-001", "ASSIGNED")

    response = client.post(
        f"{API}/TASK-001/reject",
        json={"reason": reason},
        headers=AUTH,
    )

    assert response.status_code == 422
    assert status_of(client) == "ASSIGNED"


def test_worker_cannot_reject_another_workers_task(client):
    add_task(client, make_task(
        "OTHER-1",
        worker_id=OTHER_WORKER_ID,
        status=TaskStatus.ASSIGNED,
    ))

    response = client.post(
        f"{API}/OTHER-1/reject",
        json={"reason": "Not assigned to me"},
        headers=AUTH,
    )

    assert response.status_code == 404


def test_start_accepted_task(client):

    response = post_action(client, "TASK-001", "start")

    assert response.status_code == 200
    assert response.json()["task"]["status"] == "IN_PROGRESS"
    assert status_of(client) == "IN_PROGRESS"


def test_pause_in_progress_task(client):
    post_action(client, "TASK-001", "start")

    response = post_action(client, "TASK-001", "pause")

    assert response.status_code == 200
    assert response.json()["task"]["status"] == "PAUSED"
    assert status_of(client) == "PAUSED"


def test_resume_paused_task(client):
    for action in ("start", "pause"):
        post_action(client, "TASK-001", action)

    response = post_action(client, "TASK-001", "resume")

    assert response.status_code == 200
    assert response.json()["message"] == "Task resumed."
    assert response.json()["task"]["status"] == "IN_PROGRESS"
    assert status_of(client) == "IN_PROGRESS"


def test_start_also_resumes_paused_task(client):
    # Existing behaviour of /start is preserved.
    for action in ("start", "pause"):
        post_action(client, "TASK-001", action)

    response = post_action(client, "TASK-001", "start")

    assert response.status_code == 200
    assert status_of(client) == "IN_PROGRESS"


def test_resume_does_not_start_an_accepted_task(client):

    response = post_action(client, "TASK-001", "resume")

    assert response.status_code == 409
    assert "PAUSED" in response.json()["detail"]
    assert status_of(client) == "ACCEPTED"


def test_updated_at_changes_on_transition(client):
    before = client.get(f"{API}/TASK-001", headers=AUTH).json()["updated_at"]

    after = post_action(client, "TASK-001", "start").json()["task"]

    assert after["updated_at"] > before


@pytest.mark.parametrize(
    ("setup", "action", "expected_status"),
    [
        ([], "pause", "ACCEPTED"),
        ([], "resume", "ACCEPTED"),
        (["start"], "start", "IN_PROGRESS"),
        (["start"], "resume", "IN_PROGRESS"),
        (["start", "pause"], "pause", "PAUSED"),
    ],
)
def test_invalid_transitions_return_409(client, setup, action,
                                        expected_status):
    for step in setup:
        assert post_action(client, "TASK-001", step).status_code == 200

    response = post_action(client, "TASK-001", action)

    assert response.status_code == 409, response.text
    assert response.json()["detail"]
    assert status_of(client) == expected_status


@pytest.mark.parametrize("status", ["ASSIGNED", "REJECTED", "BLOCKED"])
@pytest.mark.parametrize("action", ["start", "pause", "resume"])
def test_no_worker_action_leaves_non_executable_states(client, status,
                                                       action):
    # Legacy ASSIGNED/REJECTED rows stay inert, and only Dispatch or a
    # Supervisor can move a task out of BLOCKED.
    set_status(client, "TASK-001", status)

    response = post_action(client, "TASK-001", action)

    assert response.status_code == 409, response.text
    assert status_of(client) == status


@pytest.mark.parametrize("action", ["start", "resume", "pause"])
def test_actions_on_missing_task_return_404(client, action):
    response = post_action(client, "MISSING", action)

    assert response.status_code == 404
