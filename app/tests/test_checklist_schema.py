"""DB-free unit tests for checklist schemas.

The update rules that depend on stored state (task must be IN_PROGRESS,
step must exist for the task, worker ownership) live in FieldWorkService
and are covered by the database-backed tests in test_checklist.py.
"""

import pytest
from pydantic import ValidationError

from app.schemas.checklist import (
    ChecklistStatus,
    ChecklistStepRecord,
    ChecklistStepUpdate,
)
from app.schemas.worker_task import ChecklistDefinition


@pytest.mark.parametrize("status", ["PENDING", "COMPLETED", "BLOCKED"])
def test_update_accepts_every_checklist_status(status):
    update = ChecklistStepUpdate(status=status)

    assert update.status == ChecklistStatus(status)
    assert update.note is None


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"status": "SKIPPED"},
        {"status": "completed"},
        {"status": None},
        {"status": "COMPLETED", "note": "x" * 501},
        {"status": "COMPLETED", "step_id": "STEP-001"},
    ],
    ids=["missing-status", "unknown-status", "lowercase-status",
         "null-status", "note-too-long", "extra-field"],
)
def test_update_rejects_invalid_payload(body):
    with pytest.raises(ValidationError):
        ChecklistStepUpdate(**body)


def test_update_note_length_boundary():
    update = ChecklistStepUpdate(status="BLOCKED", note="x" * 500)

    assert update.note == "x" * 500


def test_record_defaults_to_pending():
    record = ChecklistStepRecord(step_id="S1", task_id="T1")

    assert record.status == ChecklistStatus.PENDING
    assert record.note is None
    assert record.updated_at.tzinfo is not None


def test_record_rejects_long_note_and_extra_fields():
    with pytest.raises(ValidationError):
        ChecklistStepRecord(step_id="S1", task_id="T1", note="x" * 501)

    with pytest.raises(ValidationError):
        ChecklistStepRecord(step_id="S1", task_id="T1", required=True)


def test_definition_is_required_by_default():
    assert ChecklistDefinition(step_id="S1", title="Inspect").required is True


@pytest.mark.parametrize(
    "body",
    [
        {"step_id": "", "title": "Inspect"},
        {"step_id": "S" * 101, "title": "Inspect"},
        {"step_id": "S1", "title": ""},
        {"step_id": "S1", "title": "T" * 251},
        {"step_id": "S1", "title": "Inspect", "status": "PENDING"},
    ],
    ids=["empty-id", "long-id", "empty-title", "long-title", "extra-field"],
)
def test_definition_rejects_invalid_values(body):
    with pytest.raises(ValidationError):
        ChecklistDefinition(**body)
