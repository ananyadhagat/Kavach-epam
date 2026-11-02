import pytest

from app.schemas.worker_task import TaskStatus
from app.validators.task_transition_validator import (
    ALLOWED_TRANSITIONS,
    UNBLOCK_TRANSITIONS,
    InvalidTaskTransition,
    validate_transition,
)


@pytest.mark.parametrize(
    ("current", "new"),
    [
        (TaskStatus.ASSIGNED, TaskStatus.ACCEPTED),
        (TaskStatus.ASSIGNED, TaskStatus.REJECTED),
        (TaskStatus.ACCEPTED, TaskStatus.IN_PROGRESS),
        (TaskStatus.IN_PROGRESS, TaskStatus.PAUSED),
        (TaskStatus.PAUSED, TaskStatus.IN_PROGRESS),
        (TaskStatus.IN_PROGRESS, TaskStatus.COMPLETION_SUBMITTED),
        (TaskStatus.ACCEPTED, TaskStatus.BLOCKED),
        (TaskStatus.IN_PROGRESS, TaskStatus.BLOCKED),
        (TaskStatus.PAUSED, TaskStatus.BLOCKED),
    ],
)
def test_worker_transitions(current, new):
    validate_transition(current, new)


@pytest.mark.parametrize(
    ("current", "new"),
    [
        (TaskStatus.ASSIGNED, TaskStatus.IN_PROGRESS),
        (TaskStatus.ACCEPTED, TaskStatus.REJECTED),
        (TaskStatus.REJECTED, TaskStatus.IN_PROGRESS),
        # Completion only from active work.
        (TaskStatus.ACCEPTED, TaskStatus.COMPLETION_SUBMITTED),
        (TaskStatus.PAUSED, TaskStatus.COMPLETION_SUBMITTED),
        (TaskStatus.BLOCKED, TaskStatus.COMPLETION_SUBMITTED),
        # A worker can never unblock a task.
        (TaskStatus.BLOCKED, TaskStatus.ACCEPTED),
        (TaskStatus.BLOCKED, TaskStatus.IN_PROGRESS),
        (TaskStatus.BLOCKED, TaskStatus.PAUSED),
        # Never verified or closed here; submission is final.
        (TaskStatus.COMPLETION_SUBMITTED, TaskStatus.IN_PROGRESS),
    ],
)
def test_invalid_worker_transitions(current, new):
    with pytest.raises(InvalidTaskTransition):
        validate_transition(current, new)


@pytest.mark.parametrize(
    "previous", [TaskStatus.ACCEPTED, TaskStatus.IN_PROGRESS, TaskStatus.PAUSED]
)
def test_unblock_returns_to_previous_status(previous):
    validate_transition(TaskStatus.BLOCKED, previous, UNBLOCK_TRANSITIONS)


@pytest.mark.parametrize(
    ("current", "new"),
    [
        (TaskStatus.BLOCKED, TaskStatus.COMPLETION_SUBMITTED),
        (TaskStatus.IN_PROGRESS, TaskStatus.ACCEPTED),
        (TaskStatus.ACCEPTED, TaskStatus.IN_PROGRESS),
    ],
)
def test_unblock_table_only_leaves_blocked(current, new):
    with pytest.raises(InvalidTaskTransition):
        validate_transition(current, new, UNBLOCK_TRANSITIONS)


def test_no_verified_or_closed_status_exists():
    names = {status.value for status in TaskStatus}

    assert not names & {"VERIFIED", "CLOSED", "RESOLVED"}
    assert set(ALLOWED_TRANSITIONS) == set(TaskStatus)
