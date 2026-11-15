import re

from app.schemas.sanitation import SanitationPlan


FORBIDDEN_CLAIMS = [
    r"\bworkers have been assigned\b",
    r"\bworker has been assigned\b",
    r"\bteam has been dispatched\b",
    r"\bcleaning has been completed\b",
    r"\bwork has been completed\b",
    r"\bissue has been resolved\b",
    r"\bcomplaint has been resolved\b",
    r"\balready cleaned\b",
]


def validate_sanitation_safety(plan: SanitationPlan) -> SanitationPlan:
    """Reject plans that claim unverified operational actions are complete."""
    plan_text = " ".join(
        [
            plan.summary,
            *(task.task_name for task in plan.tasks),
            *(task.description for task in plan.tasks),
            *(item for task in plan.tasks for item in task.checklist),
            *plan.safety_notes,
        ]
    ).lower()

    for pattern in FORBIDDEN_CLAIMS:
        if re.search(pattern, plan_text):
            raise ValueError(
                "Safety validation failed: the plan claims an "
                "operational action has already occurred."
            )

    return plan
