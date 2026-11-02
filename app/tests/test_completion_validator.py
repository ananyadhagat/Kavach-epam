"""DB-free unit tests for completion claim validation."""

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.schemas.completion import CompletionClaim
from app.schemas.evidence import EvidenceRecord, EvidenceType
from app.schemas.location_event import (
    LocationCaptureStatus,
    LocationEventRecord,
    LocationEventType,
)
from app.tests.conftest import WORKER_ID, make_task
from app.validators.completion_validator import (
    CompletionValidationError,
    validate_completion,
)

TASK_ID = "TASK-1"
BEFORE_ID = "00000000-0000-0000-0000-000000000001"
AFTER_ID = "00000000-0000-0000-0000-000000000002"
ARRIVAL_ID = "00000000-0000-0000-0000-0000000000bb"

UPLOADED_AT = datetime(2026, 10, 1, 10, 5, tzinfo=timezone.utc)


def evidence(evidence_id, evidence_type, task_id=TASK_ID,
             worker_id=WORKER_ID, uploaded_at=UPLOADED_AT) -> EvidenceRecord:
    number = int(evidence_id[-12:])
    return EvidenceRecord(
        evidence_id=evidence_id,
        task_id=task_id,
        worker_id=worker_id,
        evidence_type=evidence_type,
        storage_key=f"{number:032x}.png",
        original_filename="photo.png",
        mime_type="image/png",
        size_bytes=100,
        sha256=f"{number:064x}",
        uploaded_at=uploaded_at,
    )


def location(event_type=LocationEventType.COMPLETION,
             capture_status=LocationCaptureStatus.CAPTURED,
             task_id=TASK_ID, worker_id=WORKER_ID) -> LocationEventRecord:
    captured = capture_status == LocationCaptureStatus.CAPTURED
    return LocationEventRecord(
        location_event_id="00000000-0000-0000-0000-0000000000aa",
        task_id=task_id,
        worker_id=worker_id,
        event_type=event_type,
        capture_status=capture_status,
        latitude=23.2599 if captured else None,
        longitude=77.4126 if captured else None,
        accuracy_meters=10.0 if captured else None,
    )


def started_task(**kwargs):
    """A task as it is after a valid start: arrival already recorded."""
    task = make_task(TASK_ID, **kwargs)
    task.arrival_location_event_id = ARRIVAL_ID
    return task


def validate(task=None, **overrides):
    """Calls validate_completion with a valid claim, then applies overrides."""
    arguments = {
        "task": task or started_task(steps=("S1", "S2"),
                                     optional_steps=("O1",)),
        "evidence_records": [evidence(BEFORE_ID, EvidenceType.BEFORE),
                             evidence(AFTER_ID, EvidenceType.AFTER)],
        "completion_location": location(),
        "submitted_evidence_ids": [BEFORE_ID, AFTER_ID],
    }
    arguments.update(overrides)
    validate_completion(**arguments)


def no_checklist(**overrides):
    validate(task=started_task(steps=()), **overrides)


# ---------------------------------------------------------------------------
# Valid claims
# ---------------------------------------------------------------------------

def test_valid_claim_is_accepted():
    validate()


def test_extra_task_evidence_need_not_be_submitted():
    records = [evidence(BEFORE_ID, EvidenceType.BEFORE),
               evidence(AFTER_ID, EvidenceType.AFTER),
               evidence("00000000-0000-0000-0000-000000000003",
                        EvidenceType.AFTER)]
    validate(evidence_records=records)


# ---------------------------------------------------------------------------
# Checklist data does not gate worker completion.
# ---------------------------------------------------------------------------

def test_required_steps_do_not_gate_completion_validation():
    validate(task=started_task(steps=("S1", "S2")))


def test_task_without_checklist_still_requires_before_and_after():
    second_before = "00000000-0000-0000-0000-000000000003"
    records = [evidence(BEFORE_ID, EvidenceType.BEFORE),
               evidence(second_before, EvidenceType.BEFORE)]

    with pytest.raises(CompletionValidationError,
                       match="An AFTER image is required"):
        no_checklist(evidence_records=records,
                     submitted_evidence_ids=[BEFORE_ID, second_before])


def test_task_without_checklist_still_requires_completion_location():
    with pytest.raises(CompletionValidationError,
                       match="captured completion location is required"):
        no_checklist(completion_location=None)


# ---------------------------------------------------------------------------
# Evidence
# ---------------------------------------------------------------------------

def test_evidence_not_in_task_records_is_rejected():
    missing = "00000000-0000-0000-0000-000000000099"

    with pytest.raises(CompletionValidationError,
                       match=f"Evidence {missing} does not belong"):
        validate(submitted_evidence_ids=[BEFORE_ID, missing])


def test_evidence_of_another_task_is_rejected():
    records = [evidence(BEFORE_ID, EvidenceType.BEFORE),
               evidence(AFTER_ID, EvidenceType.AFTER, task_id="OTHER")]

    with pytest.raises(CompletionValidationError,
                       match="Task/evidence mismatch"):
        validate(evidence_records=records)


def test_evidence_of_another_worker_is_rejected():
    records = [evidence(BEFORE_ID, EvidenceType.BEFORE),
               evidence(AFTER_ID, EvidenceType.AFTER, worker_id="worker-002")]

    with pytest.raises(CompletionValidationError,
                       match="Worker/evidence mismatch"):
        validate(evidence_records=records)


def test_before_image_is_required():
    second_after = "00000000-0000-0000-0000-000000000003"
    records = [evidence(AFTER_ID, EvidenceType.AFTER),
               evidence(second_after, EvidenceType.AFTER)]

    with pytest.raises(CompletionValidationError,
                       match="A BEFORE image is required"):
        validate(evidence_records=records,
                 submitted_evidence_ids=[AFTER_ID, second_after])


def test_after_image_is_required():
    second_before = "00000000-0000-0000-0000-000000000003"
    records = [evidence(BEFORE_ID, EvidenceType.BEFORE),
               evidence(second_before, EvidenceType.BEFORE)]

    with pytest.raises(CompletionValidationError,
                       match="An AFTER image is required"):
        validate(evidence_records=records,
                 submitted_evidence_ids=[BEFORE_ID, second_before])


def test_unsubmitted_task_evidence_does_not_count():
    # The task has an AFTER image, but the claim does not reference it.
    second_before = "00000000-0000-0000-0000-000000000003"
    records = [evidence(BEFORE_ID, EvidenceType.BEFORE),
               evidence(second_before, EvidenceType.BEFORE),
               evidence(AFTER_ID, EvidenceType.AFTER)]

    with pytest.raises(CompletionValidationError,
                       match="An AFTER image is required"):
        validate(evidence_records=records,
                 submitted_evidence_ids=[BEFORE_ID, second_before])


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# Location
# ---------------------------------------------------------------------------

def test_arrival_is_required():
    with pytest.raises(CompletionValidationError,
                       match="Arrival location is required"):
        validate(task=make_task(TASK_ID, steps=("S1", "S2"),
                                optional_steps=("O1",)))


def test_completion_location_is_required():
    with pytest.raises(CompletionValidationError,
                       match="captured completion location is required"):
        validate(completion_location=None)


@pytest.mark.parametrize(
    ("event", "message"),
    [
        (location(task_id="OTHER"), "Completion location task mismatch"),
        (location(worker_id="worker-002"),
         "Completion location worker mismatch"),
        (location(event_type=LocationEventType.ARRIVAL),
         "A COMPLETION location event is required"),
        (location(capture_status=LocationCaptureStatus.INACCURATE),
         "Completion location is marked inaccurate"),
        # No exception policy for unavailable GPS has been agreed.
        (location(capture_status=LocationCaptureStatus.UNAVAILABLE),
         "Completion location is unavailable"),
    ],
    ids=["other-task", "other-worker", "arrival-event", "inaccurate",
         "unavailable"],
)
def test_invalid_completion_location_is_rejected(event, message):
    with pytest.raises(CompletionValidationError, match=message):
        validate(completion_location=event)


# ---------------------------------------------------------------------------
# CompletionClaim schema
# ---------------------------------------------------------------------------

def claim(**overrides) -> dict:
    body = {"evidence_ids": [BEFORE_ID, AFTER_ID]}
    body.update(overrides)
    return body


def test_claim_schema_accepts_valid_claim():
    parsed = CompletionClaim(**claim(notes="Done."))

    assert parsed.completion_location_event_id is None
    assert parsed.notes == "Done."


@pytest.mark.parametrize(
    "body",
    [
        claim(evidence_ids=[BEFORE_ID]),
        claim(evidence_ids=[BEFORE_ID, BEFORE_ID]),
        claim(notes="x" * 2001),
        claim(verified=True),
        claim(evidence_ids="not-a-list"),
    ],
    ids=["one-evidence", "duplicate-evidence", "notes-too-long",
         "extra-field", "wrong-type"],
)
def test_claim_schema_rejects_invalid_claim(body):
    with pytest.raises(ValidationError):
        CompletionClaim(**body)


def test_claim_schema_has_no_checklist_reference_field():
    assert CompletionClaim(**claim()).evidence_ids == [BEFORE_ID, AFTER_ID]


def test_claim_schema_notes_length_boundary():
    assert CompletionClaim(**claim(notes="x" * 2000)).notes == "x" * 2000


def test_submission_status_is_completion_submitted():
    from app.schemas.completion import CompletionSubmission

    submission = CompletionSubmission(
        submission_id="s", task_id="t", worker_id="w",
        checklist_step_ids=[], evidence_ids=[BEFORE_ID, AFTER_ID],
    )

    assert submission.status == "COMPLETION_SUBMITTED"
