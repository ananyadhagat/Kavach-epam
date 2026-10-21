import pytest

from app.tests.conftest import (
    API,
    AUTH,
    OTHER_WORKER_ID,
    add_task,
    make_task,
    post_action,
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
    assert body["status"] == "ASSIGNED"
    assert [s["step_id"] for s in body["checklist"]] == [
        "STEP-001", "STEP-002", "STEP-003",
    ]


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


@pytest.mark.parametrize(
    "action", ["accept", "reject", "start", "resume", "pause"]
)
def test_actions_on_other_workers_task_are_rejected(client, action):
    add_task(client, make_task("OTHER-1", worker_id=OTHER_WORKER_ID))

    response = post_action(client, "OTHER-1", action)

    assert response.status_code == 404
    assert task_status(client, "OTHER-1") == "ASSIGNED"


def test_accept_task(client):
    response = post_action(client, "TASK-001", "accept")

    assert response.status_code == 200
    assert response.json()["message"] == "Task accepted."
    assert response.json()["task"]["status"] == "ACCEPTED"
    assert status_of(client) == "ACCEPTED"


def test_reject_task(client):
    response = post_action(client, "TASK-001", "reject")

    assert response.status_code == 200
    assert response.json()["task"]["status"] == "REJECTED"
    assert status_of(client) == "REJECTED"


def test_reject_requires_reject_action(client):
    response = client.post(
        f"{API}/TASK-001/reject", json={"action": "ACCEPT"}, headers=AUTH
    )

    assert response.status_code == 422
    assert status_of(client) == "ASSIGNED"


def test_reject_requires_body(client):
    response = client.post(f"{API}/TASK-001/reject", headers=AUTH)

    assert response.status_code == 422
    assert status_of(client) == "ASSIGNED"


def test_start_accepted_task(client):
    post_action(client, "TASK-001", "accept")

    response = post_action(client, "TASK-001", "start")

    assert response.status_code == 200
    assert response.json()["task"]["status"] == "IN_PROGRESS"
    assert status_of(client) == "IN_PROGRESS"


def test_pause_in_progress_task(client):
    post_action(client, "TASK-001", "accept")
    post_action(client, "TASK-001", "start")

    response = post_action(client, "TASK-001", "pause")

    assert response.status_code == 200
    assert response.json()["task"]["status"] == "PAUSED"
    assert status_of(client) == "PAUSED"


def test_resume_paused_task(client):
    for action in ("accept", "start", "pause"):
        post_action(client, "TASK-001", action)

    response = post_action(client, "TASK-001", "resume")

    assert response.status_code == 200
    assert response.json()["message"] == "Task resumed."
    assert response.json()["task"]["status"] == "IN_PROGRESS"
    assert status_of(client) == "IN_PROGRESS"


def test_start_also_resumes_paused_task(client):
    # Existing behaviour of /start is preserved.
    for action in ("accept", "start", "pause"):
        post_action(client, "TASK-001", action)

    response = post_action(client, "TASK-001", "start")

    assert response.status_code == 200
    assert status_of(client) == "IN_PROGRESS"


def test_resume_does_not_start_an_accepted_task(client):
    post_action(client, "TASK-001", "accept")

    response = post_action(client, "TASK-001", "resume")

    assert response.status_code == 409
    assert "PAUSED" in response.json()["detail"]
    assert status_of(client) == "ACCEPTED"


def test_updated_at_changes_on_transition(client):
    before = client.get(f"{API}/TASK-001", headers=AUTH).json()["updated_at"]

    after = post_action(client, "TASK-001", "accept").json()["task"]

    assert after["updated_at"] > before


@pytest.mark.parametrize(
    ("setup", "action", "expected_status"),
    [
        ([], "start", "ASSIGNED"),
        ([], "pause", "ASSIGNED"),
        ([], "resume", "ASSIGNED"),
        (["accept"], "accept", "ACCEPTED"),
        (["accept"], "reject", "ACCEPTED"),
        (["accept"], "pause", "ACCEPTED"),
        (["accept", "start"], "start", "IN_PROGRESS"),
        (["accept", "start"], "accept", "IN_PROGRESS"),
        (["accept", "start"], "reject", "IN_PROGRESS"),
        (["accept", "start"], "resume", "IN_PROGRESS"),
        (["accept", "start", "pause"], "pause", "PAUSED"),
        (["accept", "start", "pause"], "reject", "PAUSED"),
        (["reject"], "accept", "REJECTED"),
        (["reject"], "start", "REJECTED"),
        (["reject"], "reject", "REJECTED"),
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


@pytest.mark.parametrize(
    "action", ["accept", "reject", "start", "resume", "pause"]
)
def test_actions_on_missing_task_return_404(client, action):
    response = post_action(client, "MISSING", action)

    assert response.status_code == 404
