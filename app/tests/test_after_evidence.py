"""AFTER evidence state rules and checklist-independent completion."""

import pytest

from app.schemas.worker_task import TaskStatus
from app.tests.conftest import (
    API,
    AUTH,
    add_task,
    count_rows,
    location_payload,
    make_image,
    make_task,
    post_action,
    task_status,
    upload,
)


def after(client, task_id="TASK-001", color="black"):
    return upload(client, task_id, "AFTER", content=make_image(color=color))


def after_count(client, task_id="TASK-001") -> int:
    return count_rows(client, "evidence", task_id=task_id,
                      evidence_type="AFTER")


def evidence_id(response) -> str:
    assert response.status_code == 200, response.text
    return response.json()["evidence"]["evidence_id"]


def completion_location_id(client, task_id="TASK-001") -> str:
    response = client.post(
        f"{API}/{task_id}/completion-location",
        json=location_payload("COMPLETION"),
        headers=AUTH,
    )
    assert response.status_code == 200, response.text
    return response.json()["location_event"]["location_event_id"]


def submit(client, task_id, evidence_ids, location_id):
    return client.post(
        f"{API}/{task_id}/completion",
        json={
            "evidence_ids": evidence_ids,
            "completion_location_event_id": location_id,
        },
        headers={**AUTH, "Idempotency-Key": "checklist-free"},
    )


@pytest.fixture
def in_progress(client):
    assert post_action(client, "TASK-001", "start").status_code == 200
    return client


def test_after_rejected_while_accepted(client):
    response = after(client)

    assert response.status_code == 409
    assert after_count(client) == 0


def test_after_rejected_while_paused(in_progress):
    assert post_action(in_progress, "TASK-001", "pause").status_code == 200

    response = after(in_progress)

    assert response.status_code == 409
    assert after_count(in_progress) == 0


def test_pending_required_checklist_steps_do_not_block_after(in_progress):
    response = after(in_progress)

    assert response.status_code == 200, response.text
    assert response.json()["evidence"]["evidence_type"] == "AFTER"
    assert after_count(in_progress) == 1


def test_required_checklist_steps_do_not_block_completion(client):
    add_task(client, make_task("NO-STEP-REQUIREMENT", steps=("R1", "R2")))
    before_id = evidence_id(upload(client, "NO-STEP-REQUIREMENT", "BEFORE"))
    assert post_action(client, "NO-STEP-REQUIREMENT", "start").status_code == 200
    after_id = evidence_id(after(client, "NO-STEP-REQUIREMENT"))

    response = submit(
        client,
        "NO-STEP-REQUIREMENT",
        [before_id, after_id],
        completion_location_id(client, "NO-STEP-REQUIREMENT"),
    )

    assert response.status_code == 200, response.text
    assert response.json()["submission"]["checklist_step_ids"] == []
    assert task_status(client, "NO-STEP-REQUIREMENT") == "COMPLETION_SUBMITTED"


def test_task_without_checklist_still_needs_before_to_start(client):
    add_task(client, make_task("NOCHK-1", steps=()))

    response = client.post(f"{API}/NOCHK-1/start", headers=AUTH)

    assert response.status_code == 422
    assert task_status(client, "NOCHK-1") == "ACCEPTED"


def test_duplicate_after_image_cannot_bypass_status_gate(in_progress):
    assert after(in_progress, color="black").status_code == 200
    assert post_action(in_progress, "TASK-001", "pause").status_code == 200

    response = after(in_progress, color="black")

    assert response.status_code == 409
    assert after_count(in_progress) == 1


def test_after_duplicate_reuses_backend_history_record(in_progress):
    content = make_image("WEBP", color="navy")
    first = upload(
        in_progress,
        "TASK-001",
        "AFTER",
        content=content,
        content_type="image/webp",
        filename="after-work.webp",
    )
    retry = upload(
        in_progress,
        "TASK-001",
        "AFTER",
        content=content,
        content_type="image/webp",
        filename="after-work-retry.webp",
    )

    assert first.status_code == 200, first.text
    assert retry.status_code == 200, retry.text
    assert retry.json()["duplicate"] is True
    assert retry.json()["evidence"]["evidence_id"] == (
        first.json()["evidence"]["evidence_id"]
    )

    history = in_progress.get(f"{API}/TASK-001/evidence", headers=AUTH)
    assert history.status_code == 200
    after_records = [
        item
        for item in history.json()["evidence"]
        if item["evidence_type"] == "AFTER"
    ]
    assert len(after_records) == 1
    assert after_records[0]["original_filename"] == "after-work.webp"
    assert after_records[0]["mime_type"] == "image/webp"
    assert after_records[0]["size_bytes"] == len(content)
    assert after_records[0]["status"] == "STORED"
    assert after_records[0]["uploaded_at"]


def test_reopening_legacy_checklist_does_not_invalidate_after_evidence(client):
    before_id = evidence_id(upload(client, "TASK-001", "BEFORE"))
    assert post_action(client, "TASK-001", "start").status_code == 200
    after_id = evidence_id(after(client, color="black"))

    update = client.patch(
        f"{API}/TASK-001/checklist/STEP-001",
        json={"status": "PENDING"},
        headers=AUTH,
    )
    assert update.status_code == 200

    response = submit(
        client,
        "TASK-001",
        [before_id, after_id],
        completion_location_id(client),
    )

    assert response.status_code == 200, response.text
    assert response.json()["submission"]["evidence_ids"] == [before_id, after_id]
    assert task_status(client, "TASK-001") == "COMPLETION_SUBMITTED"


def test_after_upload_to_another_workers_task_is_hidden(client):
    from app.tests.conftest import OTHER_WORKER_ID

    add_task(client, make_task("OTHER-1", worker_id=OTHER_WORKER_ID,
                               steps=(), status=TaskStatus.IN_PROGRESS))

    response = after(client, "OTHER-1")

    assert response.status_code == 404
    assert after_count(client, "OTHER-1") == 0
