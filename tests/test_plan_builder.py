from app.schemas.sanitation import (
    SanitationPriority,
    SanitationRequest,
)
from app.services.sanitation_plan_builder import build_sanitation_plan


def make_request(description: str) -> SanitationRequest:
    return SanitationRequest(
        complaint_id="KAVACH-001",
        description=description,
        location="Main entrance",
        priority=SanitationPriority.HIGH,
        estimated_waste_kg=None,
    )


def test_known_issue_uses_policy_tasks():
    request = make_request("Overflowing public dustbin")
    plan = build_sanitation_plan(request, "overflowing_dustbin")

    assert plan.complaint_id == "KAVACH-001"
    assert len(plan.tasks) == 2
    assert plan.tasks[0].task_name == "Inspect overflowing dustbin"
    assert plan.requires_human_review is True


def test_policy_resources_and_checklists_are_preserved():
    request = make_request("Overflowing public dustbin")
    plan = build_sanitation_plan(request, "overflowing_dustbin")

    assert plan.tasks[0].required_resources == ["Protective gloves"]
    assert len(plan.tasks[0].checklist) > 0


def test_duration_is_not_invented():
    request = make_request("Overflowing public dustbin")
    plan = build_sanitation_plan(request, "overflowing_dustbin")

    assert all(
        task.estimated_duration_minutes is None
        for task in plan.tasks
    )


def test_unknown_issue_requires_human_review():
    request = make_request("Broken streetlight near the entrance")
    plan = build_sanitation_plan(request, None)

    assert plan.complaint_id == "KAVACH-001"
    assert len(plan.tasks) == 1
    assert plan.requires_human_review is True
    assert "no matching sanitation policy" in plan.summary.lower()


def test_plan_does_not_claim_work_is_completed():
    request = make_request("Overflowing public dustbin")
    plan = build_sanitation_plan(request, "overflowing_dustbin")

    assert "has been completed" not in plan.summary.lower()
    assert plan.requires_human_review is True
