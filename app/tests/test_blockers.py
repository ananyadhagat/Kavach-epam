"""Task-level blocker reporting and Dispatch/Supervisor unblocking.

All tests here use the `client` fixture and need the PostgreSQL test
database. Reason codes are test placeholders; no agreed list exists yet.
"""

import pytest

from app.config import settings
from app.schemas.worker_task import ChecklistDefinition, TaskStatus
from app.tests.conftest import (
    API,
    AUTH,
    OPERATOR_AUTH,
    OPERATOR_ID,
    OTHER_WORKER_ID,
    add_task,
    checklist_status,
    complete_checklist,
    count_rows,
    db_call,
    location_payload,
    make_image,
    make_task,
    post_action,
    task_status,
    upload,
)

OPERATOR = "/api/v1/operator"
CODES = ("TEST_ACCESS", "TEST_EQUIPMENT", "OTHER")


@pytest.fixture
def codes(monkeypatch):
    monkeypatch.setattr(settings, "blocker_reason_codes", CODES)
    return CODES


@pytest.fixture
def in_progress(client, codes):
    assert post_action(client, "TASK-001", "start").status_code == 200
    return client


def report(client, task_id="TASK-001", reason_code="TEST_ACCESS",
           description="Gate locked by security.", **extra):
    return client.post(f"{API}/{task_id}/blockers",
                       json={"reason_code": reason_code,
                             "description": description, **extra},
                       headers=AUTH)


def unblock(client, task_id="TASK-001", note="Access arranged."):
    body = {} if note is None else {"resolution_note": note}
    return client.post(f"{OPERATOR}/tasks/{task_id}/unblock", json=body,
                       headers=OPERATOR_AUTH)


def history(client, task_id="TASK-001") -> list[dict]:
    response = client.get(f"{API}/{task_id}/blockers", headers=AUTH)
    assert response.status_code == 200, response.text
    return response.json()["blockers"]


# ---------------------------------------------------------------------------
# Reason codes
# ---------------------------------------------------------------------------

def test_reports_refused_until_reason_codes_are_configured(client):
    # The default configuration has no codes: there is no agreed list.
    post_action(client, "TASK-001", "start")

    response = report(client)

    assert response.status_code == 503
    assert "BLOCKER_REASON_CODES" in response.json()["detail"]
    assert task_status(client, "TASK-001") == "IN_PROGRESS"
    assert count_rows(client, "task_blockers") == 0


def test_unknown_reason_code_is_rejected(in_progress):
    response = report(in_progress, reason_code="TEST_UNKNOWN")

    assert response.status_code == 422
    assert task_status(in_progress, "TASK-001") == "IN_PROGRESS"


@pytest.mark.parametrize(
    "body",
    [
        {"reason_code": "test_access", "description": "x"},
        {"reason_code": "TEST_ACCESS", "description": "   "},
        {"reason_code": "TEST_ACCESS"},
        {"description": "x"},
        {"reason_code": "TEST_ACCESS", "description": "x" * 501},
        {"reason_code": "TEST_ACCESS", "description": "x", "status": "OPEN"},
    ],
    ids=["lowercase-code", "blank-description", "no-description", "no-code",
         "long-description", "extra-field"],
)
def test_invalid_report_payload_is_rejected(in_progress, body):
    response = in_progress.post(f"{API}/TASK-001/blockers", json=body,
                                headers=AUTH)

    assert response.status_code == 422
    assert count_rows(in_progress, "task_blockers") == 0


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("setup", [[], ["start"], ["start", "pause"]],
                         ids=["accepted", "in-progress", "paused"])
def test_blocker_moves_task_to_blocked(client, codes, setup):
    for action in setup:
        assert post_action(client, "TASK-001", action).status_code == 200
    previous = task_status(client, "TASK-001")

    response = report(client)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["task"]["status"] == "BLOCKED"
    blocker = body["blocker"]
    assert blocker["status"] == "OPEN"
    assert blocker["previous_status"] == previous
    assert blocker["reason_code"] == "TEST_ACCESS"
    assert blocker["worker_id"] == "worker-001"
    assert blocker["resolved_at"] is None
    assert task_status(client, "TASK-001") == "BLOCKED"


def test_other_reason_code_is_persisted_and_returned_in_history(in_progress):
    description = "The work area has an unlisted safety issue."

    response = report(
        in_progress,
        reason_code="OTHER",
        description=description,
    )

    assert response.status_code == 200, response.text
    blocker = response.json()["blocker"]
    assert blocker["reason_code"] == "OTHER"
    assert blocker["description"] == description

    refreshed_history = history(in_progress)
    assert refreshed_history[-1]["reason_code"] == "OTHER"
    assert refreshed_history[-1]["description"] == description


def test_blocker_on_a_step_marks_the_step_blocked(in_progress):
    complete_checklist(in_progress, "TASK-001")

    response = report(in_progress, step_id="STEP-002",
                      description="Bin area flooded.")

    assert response.status_code == 200, response.text
    assert response.json()["blocker"]["step_id"] == "STEP-002"
    assert checklist_status(in_progress, "TASK-001", "STEP-002") == "BLOCKED"
    steps = in_progress.get(f"{API}/TASK-001/checklist",
                            headers=AUTH).json()["steps"]
    step = next(s for s in steps if s["step_id"] == "STEP-002")
    assert step["note"] == "Bin area flooded."
    assert step["completed_at"] is None


def test_blocker_on_unknown_step_is_rejected(in_progress):
    response = report(in_progress, step_id="STEP-999")

    assert response.status_code == 404
    assert task_status(in_progress, "TASK-001") == "IN_PROGRESS"
    assert count_rows(in_progress, "task_blockers") == 0


def test_second_report_while_blocked_is_refused(in_progress):
    assert report(in_progress).status_code == 200

    response = report(in_progress, reason_code="TEST_EQUIPMENT")

    assert response.status_code == 409
    assert len(history(in_progress)) == 1


@pytest.mark.parametrize("status", ["ASSIGNED", "REJECTED"])
def test_blocker_not_allowed_outside_execution(client, codes, status):
    from app.tests.conftest import set_status

    set_status(client, "TASK-001", status)

    assert report(client).status_code == 409


def test_blocker_on_another_workers_task_is_hidden(client, codes):
    add_task(client, make_task("OTHER-1", worker_id=OTHER_WORKER_ID))

    assert report(client, "OTHER-1").status_code == 404
    assert client.get(f"{API}/OTHER-1/blockers",
                      headers=AUTH).status_code == 404
    assert task_status(client, "OTHER-1") == "ACCEPTED"


# ---------------------------------------------------------------------------
# A blocked task cannot progress or be completed
# ---------------------------------------------------------------------------

def test_blocked_task_cannot_be_worked_on_or_completed(in_progress):
    before = upload(in_progress, "TASK-001", "BEFORE").json()["evidence"]
    assert report(in_progress).status_code == 200

    assert upload(in_progress, "TASK-001", "AFTER",
                  content=make_image(color="black")).status_code == 409
    assert in_progress.patch(f"{API}/TASK-001/checklist/STEP-001",
                             json={"status": "PENDING"},
                             headers=AUTH).status_code == 409
    assert in_progress.post(f"{API}/TASK-001/completion-location",
                            json=location_payload("COMPLETION"),
                            headers=AUTH).status_code == 409
    claim = {"evidence_ids": [before["evidence_id"],
                              "00000000-0000-0000-0000-000000000099"]}
    completion = in_progress.post(f"{API}/TASK-001/completion", json=claim,
                                  headers={**AUTH, "Idempotency-Key": "k"})
    # Refused on the task status, before the claim itself is examined.
    assert completion.status_code == 409
    assert count_rows(in_progress, "completion_submissions") == 0
    assert task_status(in_progress, "TASK-001") == "BLOCKED"


@pytest.mark.parametrize("action", ["start", "pause", "resume"])
def test_worker_cannot_unblock_with_task_actions(in_progress, action):
    assert report(in_progress).status_code == 200

    response = post_action(in_progress, "TASK-001", action)

    assert response.status_code == 409
    assert task_status(in_progress, "TASK-001") == "BLOCKED"


def test_worker_token_cannot_use_unblock(in_progress):
    assert report(in_progress).status_code == 200

    response = in_progress.post(f"{OPERATOR}/tasks/TASK-001/unblock",
                                json={}, headers=AUTH)

    assert response.status_code == 401
    assert task_status(in_progress, "TASK-001") == "BLOCKED"


# ---------------------------------------------------------------------------
# Dispatch/Supervisor handling
# ---------------------------------------------------------------------------

def test_open_blockers_are_listed_for_dispatch(in_progress):
    blocker = report(in_progress).json()["blocker"]

    response = in_progress.get(f"{OPERATOR}/blockers", headers=OPERATOR_AUTH)

    assert response.status_code == 200
    assert [b["blocker_id"] for b in response.json()["blockers"]] == [
        blocker["blocker_id"]
    ]


@pytest.mark.parametrize("setup", [[], ["start"], ["start", "pause"]],
                         ids=["accepted", "in-progress", "paused"])
def test_unblock_restores_previous_status(client, codes, setup):
    for action in setup:
        post_action(client, "TASK-001", action)
    previous = task_status(client, "TASK-001")
    assert report(client).status_code == 200

    response = unblock(client)

    assert response.status_code == 200, response.text
    assert response.json()["task"]["status"] == previous
    blocker = response.json()["blocker"]
    assert blocker["status"] == "RESOLVED"
    assert blocker["resolved_by"] == OPERATOR_ID
    assert blocker["resolution_note"] == "Access arranged."
    assert blocker["resolved_at"] is not None
    assert task_status(client, "TASK-001") == previous
    assert in_progress_blockers(client) == []


def in_progress_blockers(client):
    return client.get(f"{OPERATOR}/blockers",
                      headers=OPERATOR_AUTH).json()["blockers"]


def test_unblock_without_note_is_allowed(in_progress):
    assert report(in_progress).status_code == 200

    response = unblock(in_progress, note=None)

    assert response.status_code == 200
    assert response.json()["blocker"]["resolution_note"] is None


def test_blocker_history_is_preserved(in_progress):
    first = report(in_progress, reason_code="TEST_ACCESS").json()["blocker"]
    assert unblock(in_progress).status_code == 200
    second = report(in_progress,
                    reason_code="TEST_EQUIPMENT").json()["blocker"]

    records = history(in_progress)

    assert [r["blocker_id"] for r in records] == [first["blocker_id"],
                                                 second["blocker_id"]]
    assert [r["status"] for r in records] == ["RESOLVED", "OPEN"]
    assert records[0]["reason_code"] == "TEST_ACCESS"
    assert records[0]["description"] == first["description"]


def test_unblock_requires_a_blocked_task(client, codes):
    assert unblock(client).status_code == 409
    assert task_status(client, "TASK-001") == "ACCEPTED"


def test_unblock_unknown_task(client, codes):
    assert unblock(client, "MISSING").status_code == 404


# ---------------------------------------------------------------------------
# Legacy checklist blocker does not gate evidence or completion
# ---------------------------------------------------------------------------

def test_blocked_step_does_not_gate_after_or_completion(in_progress):
    client = in_progress
    before = upload(client, "TASK-001", "BEFORE").json()["evidence"]
    old_after = upload(client, "TASK-001", "AFTER",
                       content=make_image(color="black")).json()["evidence"]

    assert report(client, step_id="STEP-002").status_code == 200
    assert unblock(client).status_code == 200
    assert task_status(client, "TASK-001") == "IN_PROGRESS"
    assert checklist_status(client, "TASK-001", "STEP-002") == "BLOCKED"

    after = upload(client, "TASK-001", "AFTER",
                   content=make_image(color="gray"))
    assert after.status_code == 200, after.text
    assert checklist_status(client, "TASK-001", "STEP-002") == "BLOCKED"

    location = client.post(f"{API}/TASK-001/completion-location",
                           json=location_payload("COMPLETION"), headers=AUTH)
    claim = {
        "evidence_ids": [before["evidence_id"], old_after["evidence_id"]],
        "completion_location_event_id":
            location.json()["location_event"]["location_event_id"],
    }
    response = client.post(f"{API}/TASK-001/completion", json=claim,
                           headers={**AUTH, "Idempotency-Key": "k1"})

    assert response.status_code == 200, response.text
    assert response.json()["submission"]["status"] == "COMPLETION_SUBMITTED"
    assert task_status(client, "TASK-001") == "COMPLETION_SUBMITTED"


# ---------------------------------------------------------------------------
# Checklist step owners
# ---------------------------------------------------------------------------

def add_task_with_step_owner(client):
    task = make_task("CREW-1", steps=())
    task.checklist = [
        ChecklistDefinition(step_id="MINE", title="Mine"),
        ChecklistDefinition(step_id="THEIRS", title="Theirs",
                            assigned_worker_id=OTHER_WORKER_ID),
    ]

    async def operation(uow):
        await uow.tasks.add_worker("worker-001", "Worker 1")
        await uow.tasks.add_worker(OTHER_WORKER_ID, "Worker 2")
        return await uow.tasks.add_task(task)

    return db_call(client, operation)


def test_step_owners_are_exposed(client):
    add_task_with_step_owner(client)

    task = client.get(f"{API}/CREW-1", headers=AUTH).json()

    assert {s["step_id"]: s["assigned_worker_id"] for s in task["checklist"]} == {
        "MINE": "worker-001", "THEIRS": OTHER_WORKER_ID,
    }


def test_worker_can_update_only_their_own_steps(client):
    add_task_with_step_owner(client)
    assert post_action(client, "CREW-1", "start").status_code == 200

    mine = client.patch(f"{API}/CREW-1/checklist/MINE",
                        json={"status": "COMPLETED"}, headers=AUTH)
    theirs = client.patch(f"{API}/CREW-1/checklist/THEIRS",
                          json={"status": "COMPLETED"}, headers=AUTH)

    assert mine.status_code == 200
    assert theirs.status_code == 403
    assert checklist_status(client, "CREW-1", "THEIRS") == "PENDING"


def test_worker_cannot_block_another_workers_step(client, codes):
    add_task_with_step_owner(client)

    response = report(client, "CREW-1", step_id="THEIRS")

    assert response.status_code == 403
    assert task_status(client, "CREW-1") == "ACCEPTED"
    assert checklist_status(client, "CREW-1", "THEIRS") == "PENDING"


def test_no_verified_or_closed_status_reachable(in_progress):
    # Field Worker only ever submits; verification is downstream.
    assert {s.value for s in TaskStatus}.isdisjoint({"VERIFIED", "CLOSED"})
