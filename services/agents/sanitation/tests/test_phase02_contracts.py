import pytest
from pydantic import ValidationError

from app.schemas.sanitation_request import SanitationRequest
from app.schemas.sanitation_response import SanitationResponse


VALID_REQUEST = {
    "contract_version": "1.0.0",
    "request_id": "12345678-1234-5678-1234-567812345678",
    "event_id": "EVENT-001",
    "complaint_id": "KAVACH-001",
    "description": "Overflowing public dustbin",
    "location": "Zone A",
    "priority": "high",
    "requested_at": "2026-10-26T12:00:00+05:30",
}

VALID_RESPONSE = {
    "contract_version": "1.0.0",
    "request_id": "12345678-1234-5678-1234-567812345678",
    "complaint_id": "KAVACH-001",
    "planning_status": "PRELIMINARY_PLAN",
}


def test_valid_request_is_accepted():
    request = SanitationRequest.model_validate(VALID_REQUEST)
    assert request.complaint_id == "KAVACH-001"


@pytest.mark.parametrize(
    "changes",
    [
        {"contract_version": "9.9.9"},
        {"priority": "urgent"},
        {"requested_at": "2026-10-26T12:00:00"},
        {"requested_at": "not-a-timestamp"},
    ],
)
def test_invalid_request_is_rejected(changes):
    with pytest.raises(ValidationError):
        SanitationRequest.model_validate({**VALID_REQUEST, **changes})


def test_valid_response_is_accepted():
    response = SanitationResponse.model_validate(VALID_RESPONSE)
    assert response.dispatch_eligible is False
    assert response.requires_human_review is True


@pytest.mark.parametrize(
    "changes",
    [
        {"contract_version": "9.9.9"},
        {"planning_status": "DISPATCHED"},
        {"dispatch_eligible": True},
        {"requires_human_review": False},
        {"resource_estimate": {"availability_confirmed": True}},
    ],
)
def test_unsafe_or_invalid_response_is_rejected(changes):
    with pytest.raises(ValidationError):
        SanitationResponse.model_validate({**VALID_RESPONSE, **changes})



def make_task(task_id, depends_on=None):
    return {
        "task_id": task_id,
        "task_code": f"CODE-{task_id}",
        "sequence": 1,
        "task_name": f"Task {task_id}",
        "description": f"Description for task {task_id}",
        "depends_on": depends_on or [],
    }


def make_response_with_tasks(tasks):
    return SanitationResponse.model_validate({
        **VALID_RESPONSE,
        "tasks": tasks,
    })


def test_duplicate_task_ids_are_rejected():
    tasks = [
        make_task("TASK-1"),
        make_task("TASK-1"),
    ]

    with pytest.raises(ValidationError, match="Task IDs must be unique"):
        make_response_with_tasks(tasks)


def test_unknown_task_dependencies_are_rejected():
    tasks = [
        make_task("TASK-1", ["TASK-MISSING"]),
    ]

    with pytest.raises(ValidationError, match="unknown dependencies"):
        make_response_with_tasks(tasks)


def test_circular_task_dependencies_are_rejected():
    tasks = [
        make_task("TASK-1", ["TASK-2"]),
        make_task("TASK-2", ["TASK-1"]),
    ]

    with pytest.raises(
        ValidationError,
        match="Circular task dependencies",
    ):
        make_response_with_tasks(tasks)
