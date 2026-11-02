from app.schemas.worker_task import TaskStatus

# Transitions a worker's own actions may cause. A worker can accept or reject
# an ASSIGNED task. A worker can block a task but never unblock it.
ALLOWED_TRANSITIONS: dict[TaskStatus, set[TaskStatus]] = {
    TaskStatus.ASSIGNED: {
        TaskStatus.ACCEPTED,
        TaskStatus.REJECTED,
    },
    TaskStatus.REJECTED: set(),
    TaskStatus.ACCEPTED: {
        TaskStatus.IN_PROGRESS,
        TaskStatus.BLOCKED,
    },
    TaskStatus.IN_PROGRESS: {
        TaskStatus.PAUSED,
        TaskStatus.BLOCKED,
        TaskStatus.COMPLETION_SUBMITTED,
    },
    TaskStatus.PAUSED: {
        TaskStatus.IN_PROGRESS,
        TaskStatus.BLOCKED,
    },
    TaskStatus.BLOCKED: set(),
    TaskStatus.COMPLETION_SUBMITTED: set(),
}

# Used only when Dispatch or a Supervisor resolves a blocker: the task
# returns to the status it had when the blocker was reported.
UNBLOCK_TRANSITIONS: dict[TaskStatus, set[TaskStatus]] = {
    TaskStatus.BLOCKED: {
        TaskStatus.ACCEPTED,
        TaskStatus.IN_PROGRESS,
        TaskStatus.PAUSED,
    },
}


class InvalidTaskTransition(Exception):
    """Raised when a task status change violates the state machine."""


def validate_transition(
    current_status: TaskStatus,
    new_status: TaskStatus,
    transitions: dict[TaskStatus, set[TaskStatus]] = ALLOWED_TRANSITIONS,
) -> None:
    allowed = transitions.get(current_status, set())

    if new_status not in allowed:
        raise InvalidTaskTransition(
            f"Transition {current_status.value} -> "
            f"{new_status.value} is not allowed."
        )
