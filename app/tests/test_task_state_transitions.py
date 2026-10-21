import pytest

from app.schemas.worker_task import TaskStatus
from app.validators.task_transition_validator import (
    InvalidTaskTransition,
    validate_transition,
)


def test_assigned_to_accepted():
    validate_transition(TaskStatus.ASSIGNED, TaskStatus.ACCEPTED)


def test_assigned_to_rejected():
    validate_transition(TaskStatus.ASSIGNED, TaskStatus.REJECTED)


def test_accepted_to_in_progress():
    validate_transition(TaskStatus.ACCEPTED, TaskStatus.IN_PROGRESS)


def test_in_progress_to_paused():
    validate_transition(TaskStatus.IN_PROGRESS, TaskStatus.PAUSED)


def test_paused_to_in_progress():
    validate_transition(TaskStatus.PAUSED, TaskStatus.IN_PROGRESS)


def test_in_progress_to_completion_submitted():
    validate_transition(
        TaskStatus.IN_PROGRESS,
        TaskStatus.COMPLETION_SUBMITTED,
    )


def test_invalid_assigned_to_in_progress():
    with pytest.raises(InvalidTaskTransition):
        validate_transition(
            TaskStatus.ASSIGNED,
            TaskStatus.IN_PROGRESS,
        )


def test_rejected_task_cannot_restart():
    with pytest.raises(InvalidTaskTransition):
        validate_transition(
            TaskStatus.REJECTED,
            TaskStatus.IN_PROGRESS,
        )