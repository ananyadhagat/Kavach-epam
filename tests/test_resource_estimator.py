from app.schemas.sanitation import SanitationTask
from app.services.resource_estimator import estimate_resources


def test_resource_estimator_collects_unique_resources():
    tasks = [
        SanitationTask(
            task_name="Inspect dustbin",
            description="Proposed inspection",
            required_resources=["Protective gloves"],
        ),
        SanitationTask(
            task_name="Collect waste",
            description="Proposed collection",
            required_resources=[
                "Protective gloves",
                "Waste collection bags",
            ],
        ),
    ]

    result = estimate_resources(tasks)

    assert result["required_resources"] == [
        "Protective gloves",
        "Waste collection bags",
    ]
    assert result["resource_count"] == 2


def test_resource_estimator_does_not_invent_worker_counts():
    result = estimate_resources([])

    assert result["worker_count"] is None
    assert result["availability_confirmed"] is False
    assert result["requires_human_review"] is True


def test_resource_estimator_handles_empty_resource_lists():
    tasks = [
        SanitationTask(
            task_name="Inspect area",
            description="Proposed inspection",
            required_resources=[],
        ),
    ]

    result = estimate_resources(tasks)

    assert result["required_resources"] == []
    assert result["resource_count"] == 0
