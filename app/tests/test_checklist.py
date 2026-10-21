import pytest

from app.schemas.worker_task import TaskStatus
from app.tests.conftest import (
    API,
    AUTH,
    OTHER_WORKER_ID,
    add_task,
    checklist_status,
    count_rows,
    make_task,
    post_action,
)


@pytest.fixture
def in_progress(client):
    post_action(client, "TASK-001", "accept")
    post_action(client, "TASK-001", "start")
    return client


def patch_step(client, step_id="STEP-001", body=None, task_id="TASK-001",
               headers=AUTH):
    return client.patch(
        f"{API}/{task_id}/checklist/{step_id}",
        json={"status": "COMPLETED"} if body is None else body,
        headers=headers,
    )


def checklist(client, task_id="TASK-001"):
    response = client.get(f"{API}/{task_id}/checklist", headers=AUTH)
    assert response.status_code == 200
    return {s["step_id"]: s for s in response.json()["steps"]}


def test_initial_checklist_is_pending(client):
    steps = checklist(client)

    assert set(steps) == {"STEP-001", "STEP-002", "STEP-003"}
    assert all(s["status"] == "PENDING" for s in steps.values())


@pytest.mark.parametrize("status", ["COMPLETED", "BLOCKED", "PENDING"])
def test_valid_update(in_progress, status):
    response = patch_step(
        in_progress, body={"status": status, "note": "Done carefully."}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["task_id"] == "TASK-001"
    assert body["step_id"] == "STEP-001"
    assert body["status"] == status
    assert body["note"] == "Done carefully."
    assert body["message"] == "Checklist updated successfully."

    stored = checklist(in_progress)["STEP-001"]
    assert stored["status"] == status
    assert stored["note"] == "Done carefully."
    assert checklist(in_progress)["STEP-002"]["status"] == "PENDING"


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"status": "DONE"},
        {"status": "completed"},
        {"status": None},
        {"status": "COMPLETED", "note": "x" * 501},
        {"status": "COMPLETED", "unexpected": True},
    ],
)
def test_invalid_payload(in_progress, body):
    response = patch_step(in_progress, body=body)

    assert response.status_code == 422
    assert checklist(in_progress)["STEP-001"]["status"] == "PENDING"


def test_missing_step(in_progress):
    response = patch_step(in_progress, step_id="STEP-999")

    assert response.status_code == 404
    assert response.json() == {"detail": "Checklist step not found."}


def test_step_from_different_task(in_progress):
    add_task(in_progress, make_task("MINE-2", steps=("OTHER-STEP",)))

    response = patch_step(in_progress, step_id="OTHER-STEP")

    assert response.status_code == 404
    assert count_rows(in_progress, "checklist_steps", task_id="TASK-001",
                      step_id="OTHER-STEP") == 0
    assert checklist_status(in_progress, "MINE-2", "OTHER-STEP") == "PENDING"


def test_other_workers_task(client):
    add_task(client, make_task("OTHER-1", worker_id=OTHER_WORKER_ID,
                               steps=("S1",), status=TaskStatus.IN_PROGRESS))

    response = patch_step(client, step_id="S1", task_id="OTHER-1")

    assert response.status_code == 404
    assert checklist_status(client, "OTHER-1", "S1") == "PENDING"

    assert client.get(
        f"{API}/OTHER-1/checklist", headers=AUTH
    ).status_code == 404


def test_unauthorized_update(in_progress):
    response = patch_step(
        in_progress, headers={"Authorization": "Bearer nope-nope"}
    )

    assert response.status_code == 401
    assert checklist(in_progress)["STEP-001"]["status"] == "PENDING"


@pytest.mark.parametrize(
    "setup", [[], ["accept"], ["accept", "start", "pause"], ["reject"]]
)
def test_updates_require_in_progress(client, setup):
    for action in setup:
        post_action(client, "TASK-001", action)

    response = patch_step(client)

    assert response.status_code == 409
    assert checklist(client)["STEP-001"]["status"] == "PENDING"


def test_nonexistent_task(client):
    assert patch_step(client, task_id="NOPE").status_code == 404
    assert client.get(f"{API}/NOPE/checklist", headers=AUTH).status_code == 404
