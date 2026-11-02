import pytest

from app.schemas.worker_task import TaskStatus
from app.tests.conftest import (
    API,
    AUTH,
    OTHER_WORKER_ID,
    add_task,
    idempotency_records,
    location_payload,
    make_image,
    make_task,
    post_action,
    prepare_for_completion,
    task_status,
    upload,
)

URL = f"{API}/TASK-001/completion"


def submit(client, claim, key="key-001", headers=None, url=URL):
    request_headers = dict(AUTH if headers is None else headers)

    if key is not None:
        request_headers["Idempotency-Key"] = key

    return client.post(url, json=claim, headers=request_headers)


def task_body(client, task_id="TASK-001"):
    return client.get(f"{API}/{task_id}", headers=AUTH).json()


def assert_not_submitted(client):
    task = task_body(client)
    assert task["status"] == "IN_PROGRESS"
    assert task["completion_submission_id"] is None
    assert idempotency_records(client) == {}


@pytest.fixture
def ready(client):
    return client, prepare_for_completion(client)


def test_valid_completion_claim(ready):
    client, claim = ready
    claim["notes"] = "All done."

    response = submit(client, claim)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["message"] == (
        "Completion claim recorded for independent verification."
    )
    submission = body["submission"]
    assert submission["task_id"] == "TASK-001"
    assert submission["worker_id"] == "worker-001"
    assert submission["checklist_step_ids"] == []
    assert submission["evidence_ids"] == claim["evidence_ids"]
    assert submission["completion_location_event_id"] == (
        claim["completion_location_event_id"]
    )
    assert submission["notes"] == "All done."
    # A claim is not a verification result.
    assert submission["status"] == "COMPLETION_SUBMITTED"

    task = task_body(client)
    assert task["status"] == "COMPLETION_SUBMITTED"
    assert task["completion_submission_id"] == submission["submission_id"]


def test_completion_location_is_required(client):
    claim = prepare_for_completion(client, with_completion_location=False)

    response = submit(client, claim)

    assert response.status_code == 422
    assert "completion location is required" in response.json()["detail"]
    assert_not_submitted(client)


def test_unavailable_completion_location_is_rejected(client):
    claim = prepare_for_completion(client, with_completion_location=False)
    unavailable = client.post(
        f"{API}/TASK-001/completion-location",
        json=location_payload("COMPLETION", capture_status="UNAVAILABLE",
                              latitude=None, longitude=None,
                              accuracy_meters=None),
        headers=AUTH,
    )
    claim["completion_location_event_id"] = (
        unavailable.json()["location_event"]["location_event_id"]
    )

    response = submit(client, claim)

    # No exception policy for unavailable GPS has been agreed.
    assert response.status_code == 422
    assert "unavailable" in response.json()["detail"]
    assert_not_submitted(client)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda c: c.update(evidence_ids=c["evidence_ids"][:1]),
        lambda c: c.update(evidence_ids=[c["evidence_ids"][0]] * 2),
        lambda c: c.update(checklist_step_ids=["STEP-001"]),
        lambda c: c.update(notes="x" * 2001),
        lambda c: c.update(verified=True),
        lambda c: c.update(evidence_ids="not-a-list"),
    ],
    ids=["one-evidence", "duplicate-evidence", "legacy-checklist-field",
         "notes-too-long", "extra-field", "wrong-type"],
)
def test_invalid_claim_schema(ready, mutate):
    client, claim = ready
    mutate(claim)

    response = submit(client, claim)

    assert response.status_code == 422
    assert_not_submitted(client)


def test_missing_evidence_ids(ready):
    client, claim = ready
    del claim["evidence_ids"]

    assert submit(client, claim).status_code == 422
    assert_not_submitted(client)


def test_empty_body(ready):
    client, _ = ready

    assert submit(client, {}).status_code == 422
    assert_not_submitted(client)


def test_required_steps_do_not_block_completion(client):
    add_task(client, make_task("NO-STEP-REQUIREMENT", steps=("R1", "R2")))
    claim = prepare_for_completion(client, "NO-STEP-REQUIREMENT")

    response = submit(
        client,
        claim,
        url=f"{API}/NO-STEP-REQUIREMENT/completion",
    )

    assert response.status_code == 200, response.text
    assert response.json()["submission"]["checklist_step_ids"] == []


def test_missing_after_evidence(client):
    claim = prepare_for_completion(client)
    extra_before = upload(client, "TASK-001", "BEFORE",
                          content=make_image("PNG", color="blue"))
    claim["evidence_ids"] = [claim["evidence_ids"][0],
                             extra_before.json()["evidence"]["evidence_id"]]

    response = submit(client, claim)

    assert response.status_code == 422
    assert response.json() == {"detail": "An AFTER image is required."}
    assert_not_submitted(client)


def test_missing_before_evidence(client):
    claim = prepare_for_completion(client)
    extra_after = upload(client, "TASK-001", "AFTER",
                         content=make_image("PNG", color="green"))
    claim["evidence_ids"] = [claim["evidence_ids"][1],
                             extra_after.json()["evidence"]["evidence_id"]]

    response = submit(client, claim)

    assert response.status_code == 422
    assert response.json() == {"detail": "A BEFORE image is required."}


def test_unknown_evidence_id(ready):
    client, claim = ready
    claim["evidence_ids"][0] = "does-not-exist"

    response = submit(client, claim)

    assert response.status_code == 422
    assert "does not belong to this task" in response.json()["detail"]
    assert_not_submitted(client)


def test_evidence_from_another_task(client):
    add_task(client, make_task("MINE-2"))
    post_action(client, "MINE-2", "start")
    foreign = upload(client, "MINE-2", "AFTER",
                     content=make_image("PNG", color="purple"))
    assert foreign.status_code == 200, foreign.text
    claim = prepare_for_completion(client)
    claim["evidence_ids"][1] = foreign.json()["evidence"]["evidence_id"]

    response = submit(client, claim)

    assert response.status_code == 422
    assert_not_submitted(client)


def test_arrival_event_cannot_be_used_as_completion_location(ready):
    client, claim = ready
    arrival = client.post(f"{API}/TASK-001/arrival",
                          json=location_payload("ARRIVAL"), headers=AUTH)
    claim["completion_location_event_id"] = (
        arrival.json()["location_event"]["location_event_id"]
    )

    response = submit(client, claim)

    assert response.status_code == 422
    assert "COMPLETION location event" in response.json()["detail"]
    assert_not_submitted(client)


def test_inaccurate_completion_location_rejected(ready):
    client, claim = ready
    event = client.post(f"{API}/TASK-001/completion-location",
                        json=location_payload("COMPLETION",
                                              accuracy_meters=1000),
                        headers=AUTH).json()["location_event"]
    claim["completion_location_event_id"] = event["location_event_id"]

    response = submit(client, claim)

    assert response.status_code == 422
    assert "inaccurate" in response.json()["detail"]
    assert_not_submitted(client)


def test_nonexistent_completion_location(ready):
    client, claim = ready
    claim["completion_location_event_id"] = "missing-location"

    response = submit(client, claim)

    assert response.status_code == 422
    assert_not_submitted(client)


def test_completion_location_from_another_task(client):
    add_task(client, make_task("MINE-2"))
    post_action(client, "MINE-2", "start")
    foreign = client.post(f"{API}/MINE-2/completion-location",
                          json=location_payload("COMPLETION"), headers=AUTH)
    claim = prepare_for_completion(client)
    claim["completion_location_event_id"] = (
        foreign.json()["location_event"]["location_event_id"]
    )

    response = submit(client, claim)

    assert response.status_code == 422
    assert "task mismatch" in response.json()["detail"]
    assert_not_submitted(client)


def test_missing_idempotency_key(ready):
    client, claim = ready

    response = submit(client, claim, key=None)

    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["header", "Idempotency-Key"]
    assert_not_submitted(client)


@pytest.mark.parametrize("key", ["   ", "k" * 201])
def test_invalid_idempotency_key(ready, key):
    client, claim = ready

    response = submit(client, claim, key=key)

    assert response.status_code == 422
    assert response.json() == {"detail": "Invalid Idempotency-Key."}
    assert_not_submitted(client)


def test_same_key_same_payload_is_replayed(ready):
    client, claim = ready

    first = submit(client, claim)
    second = submit(client, claim)

    assert first.status_code == second.status_code == 200
    assert first.json()["submission"] == second.json()["submission"]
    assert len(idempotency_records(client)) == 1
    assert task_body(client)["completion_submission_id"] == (
        first.json()["submission"]["submission_id"]
    )


def test_same_key_different_payload_conflicts(ready):
    client, claim = ready
    first = submit(client, claim)

    changed = dict(claim, notes="Different notes")
    second = submit(client, changed)

    assert second.status_code == 409
    assert second.json() == {
        "detail": "Idempotency-Key was already used with a different request."
    }
    assert len(idempotency_records(client)) == 1
    stored = next(iter(idempotency_records(client).values()))
    assert stored.submission_id == first.json()["submission"]["submission_id"]
    assert stored.notes is None


def test_new_key_after_submission_does_not_duplicate(ready):
    client, claim = ready
    submit(client, claim, key="key-A")

    response = submit(client, claim, key="key-B")

    assert response.status_code == 409
    assert len(idempotency_records(client)) == 1


def test_failed_attempt_does_not_consume_key(client):
    claim = prepare_for_completion(client)
    good_evidence = list(claim["evidence_ids"])
    claim["evidence_ids"][0] = "bogus"

    assert submit(client, claim).status_code == 422
    assert_not_submitted(client)

    claim["evidence_ids"] = good_evidence
    assert submit(client, claim).status_code == 200


def test_nonexistent_task(ready):
    client, claim = ready

    response = submit(client, claim, url=f"{API}/NOPE/completion")

    assert response.status_code == 404


def test_other_workers_task(ready):
    client, claim = ready
    add_task(client, make_task("OTHER-1", worker_id=OTHER_WORKER_ID,
                               status=TaskStatus.IN_PROGRESS))

    response = submit(client, claim, url=f"{API}/OTHER-1/completion")

    assert response.status_code == 404
    assert task_status(client, "OTHER-1") == "IN_PROGRESS"


def test_unauthorized_submission(ready):
    client, claim = ready

    response = submit(client, claim,
                      headers={"Authorization": "Bearer wrong-token"})

    assert response.status_code == 401
    assert_not_submitted(client)


def test_paused_task_cannot_submit(ready):
    client, claim = ready
    post_action(client, "TASK-001", "pause")

    response = submit(client, claim)

    assert response.status_code == 409
    assert task_body(client)["status"] == "PAUSED"
    assert idempotency_records(client) == {}


def test_arrival_is_recorded_before_work_starts(ready):
    client, claim = ready

    assert task_body(client)["arrival_location_event_id"] is not None
    assert submit(client, claim).status_code == 200


def test_completion_requires_arrival(client):
    # e.g. a task started before arrival became a start prerequisite
    add_task(client, make_task("LEGACY-1", status=TaskStatus.IN_PROGRESS))
    before = upload(client, "LEGACY-1", "BEFORE")
    after = upload(client, "LEGACY-1", "AFTER")
    location = client.post(f"{API}/LEGACY-1/completion-location",
                           json=location_payload("COMPLETION"), headers=AUTH)
    claim = {
        "evidence_ids": [before.json()["evidence"]["evidence_id"],
                         after.json()["evidence"]["evidence_id"]],
        "completion_location_event_id":
            location.json()["location_event"]["location_event_id"],
    }

    response = submit(client, claim, url=f"{API}/LEGACY-1/completion")

    assert response.status_code == 422
    assert "Arrival location is required" in response.json()["detail"]
    assert task_status(client, "LEGACY-1") == "IN_PROGRESS"


def test_task_is_locked_after_submission(ready):
    client, claim = ready
    submit(client, claim)

    assert post_action(client, "TASK-001", "pause").status_code == 409
    assert client.patch(f"{API}/TASK-001/checklist/STEP-001",
                        json={"status": "PENDING"},
                        headers=AUTH).status_code == 409
    assert upload(client, "TASK-001", "AFTER",
                  content=make_image("PNG", color="red")).status_code == 409
    assert client.post(f"{API}/TASK-001/completion-location",
                       json=location_payload("COMPLETION"),
                       headers=AUTH).status_code == 409
    assert task_body(client)["status"] == "COMPLETION_SUBMITTED"
