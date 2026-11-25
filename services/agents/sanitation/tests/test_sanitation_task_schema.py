import pytest
from pydantic import ValidationError

from app.schemas.sanitation import SanitationPlan, SanitationTask


def test_task_accepts_dependencies_and_completion_criteria():
    task = SanitationTask(
        task_id="TASK-2",
        task_name="Collect waste",
        description="Proposed waste collection",
        depends_on=["TASK-1"],
        completion_criteria=["Waste collection is inspected"],
    )

    assert task.depends_on == ["TASK-1"]
    assert task.completion_criteria == [
        "Waste collection is inspected"
    ]


def test_task_cannot_depend_on_itself():
    with pytest.raises(ValidationError):
        SanitationTask(
            task_id="TASK-1",
            task_name="Inspect area",
            description="Inspect the reported area",
            depends_on=["TASK-1"],
        )


def test_plan_rejects_duplicate_task_ids():
    first = SanitationTask(
        task_id="TASK-1",
        task_name="Inspect",
        description="Inspect area",
    )
    second = SanitationTask(
        task_id="TASK-1",
        task_name="Collect",
        description="Collect waste",
    )

    with pytest.raises(ValidationError, match="Task IDs must be unique"):
        SanitationPlan(
            complaint_id="KAVACH-201",
            summary="Test plan",
            tasks=[first, second],
        )


def test_plan_rejects_unknown_dependencies():
    task = SanitationTask(
        task_id="TASK-2",
        task_name="Collect waste",
        description="Proposed collection",
        depends_on=["TASK-99"],
    )

    with pytest.raises(ValidationError, match="unknown dependencies"):
        SanitationPlan(
            complaint_id="KAVACH-201",
            summary="Test plan",
            tasks=[task],
        )


def test_legacy_task_without_task_id_remains_valid():
    task = SanitationTask(
        task_name="Inspect area",
        description="Inspect the reported area",
    )

    assert task.task_id == ""
    assert task.depends_on == []
