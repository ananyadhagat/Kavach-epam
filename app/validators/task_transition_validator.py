from app.schemas.worker_task import TaskStatus


ALLOWED_TRANSITIONS: dict[TaskStatus, set[TaskStatus]] = {
    TaskStatus.ASSIGNED: {
        TaskStatus.ACCEPTED,
        TaskStatus.REJECTED,
    },
    TaskStatus.ACCEPTED: {
        TaskStatus.IN_PROGRESS,
    },
    TaskStatus.IN_PROGRESS: {
        TaskStatus.PAUSED,
        TaskStatus.COMPLETION_SUBMITTED,
    },
    TaskStatus.PAUSED: {
        TaskStatus.IN_PROGRESS,
    },
    TaskStatus.REJECTED: set(),
    TaskStatus.COMPLETION_SUBMITTED: set(),
}


class InvalidTaskTransition(Exception):
    """Raised when a task status change violates the state machine."""


def validate_transition(
    current_status: TaskStatus,
    new_status: TaskStatus,
) -> None:
    allowed = ALLOWED_TRANSITIONS.get(current_status, set())

    if new_status not in allowed:
        raise InvalidTaskTransition(
            f"Transition {current_status.value} -> "
            f"{new_status.value} is not allowed."
        )