import pytest

from app.config import settings
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
    assert submission["checklist_step_ids"] == claim["checklist_step_ids"]
    assert submission["evidence_ids"] == claim["evidence_ids"]
    assert submission["completion_location_event_id"] == (
        claim["completion_location_event_id"]
    )
    assert submission["notes"] == "All done."
    # A claim is not a verification result.
    assert submission["status"] == "SUBMITTED_FOR_VERIFICATION"

    task = task_body(client)
    assert task["status"] == "COMPLETION_SUBMITTED"
    assert task["completion_submission_id"] == submission["submission_id"]


def test_completion_location_is_optional(client):
    claim = prepare_for_completion(client, with_completion_location=False)

    response = submit(client, claim)

    assert response.status_code == 200
    assert response.json()["submission"]["completion_location_event_id"] is None


@pytest.mark.parametrize(
    "mutate",
    [
        lambda c: c.update(evidence_ids=c["evidence_ids"][:1]),
        lambda c: c.update(evidence_ids=[c["evidence_ids"][0]] * 2),
        lambda c: c.update(checklist_step_ids=[]),
        lambda c: c.update(
            checklist_step_ids=c["checklist_step_ids"] + ["STEP-001"]
        ),
        lambda c: c.update(notes="x" * 2001),
        lambda c: c.update(verified=True),
        lambda c: c.update(evidence_ids="not-a-list"),
    ],
    ids=["one-evidence", "duplicate-evidence", "no-steps", "duplicate-steps",
         "notes-too-long", "extra-field", "wrong-type"],
)
def test_invalid_claim_schema(ready, mutate):
    client, claim = ready
    mutate(claim)

    response = submit(client, claim)

    assert response.status_code == 422
    assert_not_submitted(client)


@pytest.mark.parametrize("field", ["checklist_step_ids", "evidence_ids"])
def test_missing_required_fields(ready, field):
    client, claim = ready
    del claim[field]

    assert submit(client, claim).status_code == 422
    assert_not_submitted(client)


def test_empty_body(ready):
    client, _ = ready

    assert submit(client, {}).status_code == 422
    assert_not_submitted(client)


def test_incomplete_checklist(client):
    claim = prepare_for_completion(client)
    client.patch(f"{API}/TASK-001/checklist/STEP-002",
                 json={"status": "BLOCKED"}, headers=AUTH)

    response = submit(client, claim)

    assert response.status_code == 422
    assert "STEP-002 is not completed" in response.json()["detail"]
    assert_not_submitted(client)


def test_required_step_omitted_from_claim(ready):
    client, claim = ready
    claim["checklist_step_ids"] = ["STEP-001", "STEP-002"]

    response = submit(client, claim)

    assert response.status_code == 422
    assert "STEP-003" in response.json()["detail"]
    assert_not_submitted(client)


def test_unknown_step_in_claim(ready):
    client, claim = ready
    claim["checklist_step_ids"].append("STEP-999")

    response = submit(client, claim)

    assert response.status_code == 422
    assert "STEP-999" in response.json()["detail"]
    assert_not_submitted(client)


def test_optional_steps_need_not_be_completed(client):
    add_task(client, make_task("OPT-1", steps=("R1",),
                               optional_steps=("O1",)))
    claim = prepare_for_completion(client, "OPT-1",
                                   with_completion_location=False)
    client.patch(f"{API}/OPT-1/checklist/O1", json={"status": "PENDING"},
                 headers=AUTH)
    claim["checklist_step_ids"] = ["R1"]

    response = submit(client, claim, url=f"{API}/OPT-1/completion")

    assert response.status_code == 200, response.text


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
    post_action(client, "MINE-2", "accept")
    foreign = upload(client, "MINE-2", "AFTER",
                     content=make_image("PNG", color="purple"))
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
    post_action(client, "MINE-2", "accept")
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


def test_arrival_required_by_configuration(ready, monkeypatch):
    client, claim = ready
    monkeypatch.setattr(settings, "require_arrival_location", True)

    response = submit(client, claim)

    assert response.status_code == 422
    assert "Arrival location is required" in response.json()["detail"]
    assert_not_submitted(client)

    client.post(f"{API}/TASK-001/arrival",
                json=location_payload("ARRIVAL"), headers=AUTH)

    assert submit(client, claim).status_code == 200


def test_arrival_not_required_by_default(ready):
    client, claim = ready

    assert task_body(client)["arrival_location_event_id"] is None
    assert submit(client, claim).status_code == 200


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
