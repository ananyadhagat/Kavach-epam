import pytest
from pydantic import ValidationError

from app.schemas.sanitation import SanitationPlan, SanitationTask


def make_task(task_id: str, depends_on: list[str]) -> SanitationTask:
    return SanitationTask(
        task_id=task_id,
        task_name=f"Task {task_id}",
        description="Test task",
        depends_on=depends_on,
    )


def test_plan_rejects_circular_dependencies():
    tasks = [
        make_task("SAN-001", ["SAN-002"]),
        make_task("SAN-002", ["SAN-001"]),
    ]

    with pytest.raises(
        ValidationError,
        match="Circular task dependencies are not allowed",
    ):
        SanitationPlan(
            complaint_id="TEST-001",
            summary="Test circular dependency",
            tasks=tasks,
        )


def test_plan_accepts_valid_dependency_chain():
    tasks = [
        make_task("SAN-001", []),
        make_task("SAN-002", ["SAN-001"]),
        make_task("SAN-003", ["SAN-002"]),
    ]

    plan = SanitationPlan(
        complaint_id="TEST-002",
        summary="Valid dependency chain",
        tasks=tasks,
    )

    assert len(plan.tasks) == 3


def test_plan_accepts_independent_tasks():
    tasks = [
        make_task("SAN-001", []),
        make_task("SAN-002", []),
    ]

    plan = SanitationPlan(
        complaint_id="TEST-003",
        summary="Independent tasks",
        tasks=tasks,
    )

    assert len(plan.tasks) == 2
