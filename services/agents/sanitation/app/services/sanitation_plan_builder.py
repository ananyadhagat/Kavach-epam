from app.policies.sanitation_rules import get_sanitation_rule
from app.schemas.sanitation import (
    SanitationPlan,
    SanitationRequest,
    SanitationTask,
)


def build_sanitation_plan(
    request: SanitationRequest,
    issue_type: str | None,
) -> SanitationPlan:
    """Build a proposed plan with explicit task ordering."""
    policy = get_sanitation_rule(issue_type) if issue_type else None

    if policy is None:
        return SanitationPlan(
            complaint_id=request.complaint_id,
            summary=(
                "The complaint requires human review because "
                "no matching sanitation policy was found."
            ),
            tasks=[
                SanitationTask(
                    task_id="SAN-001",
                    task_name="Review complaint and inspect location",
                    description=(
                        "Verify the reported condition and determine "
                        "the appropriate response."
                    ),
                    estimated_duration_minutes=None,
                    required_resources=[],
                    checklist=[
                        "Confirm the reported condition",
                        "Identify immediate safety hazards",
                        "Determine whether specialist assistance is needed",
                    ],
                    depends_on=[],
                    completion_criteria=[
                        "Reported condition has been inspected",
                        "Required follow-up actions have been documented",
                    ],
                )
            ],
            safety_notes=[
                "Do not assume an issue category when no policy matches.",
                "Avoid unidentified potentially hazardous materials.",
                "Obtain human review before operational work.",
            ],
            requires_human_review=True,
        )

    tasks = []

    for index, task in enumerate(policy["default_tasks"], start=1):
        dependencies = [f"SAN-{index - 1:03d}"] if index > 1 else []

        tasks.append(
            SanitationTask(
                task_id=f"SAN-{index:03d}",
                task_name=task["task_name"],
                description=(
                    f"Proposed task based on the {issue_type} policy. "
                    "This task has not been performed."
                ),
                estimated_duration_minutes=None,
                required_resources=task.get("required_resources", []),
                checklist=task.get("checklist", []),
                depends_on=dependencies,
                completion_criteria=[
                    f"Completion of '{task['task_name']}' is verified "
                    "by an authorized reviewer."
                ],
            )
        )

    return SanitationPlan(
        complaint_id=request.complaint_id,
        summary=(
            f"Proposed sanitation plan for {policy['category']}. "
            "Tasks are based on the configured policy."
        ),
        tasks=tasks,
        safety_notes=policy["safety_notes"],
        requires_human_review=True,
    )
