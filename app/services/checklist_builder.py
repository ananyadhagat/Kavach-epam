from app.policies.template_registry import SanitationTemplate
from app.schemas.sanitation_response import DurationEstimate, ResourceEstimate
from app.schemas.sanitation_task import SanitationTask
from app.services.context_builder import PlanningContext
from app.services.duration_estimator import estimate_plan_duration
from app.services.resource_estimator import estimate_plan_resources
from app.services.task_builder import build_tasks_from_template


def build_plan_checklist(
    template: SanitationTemplate,
    context: PlanningContext,
) -> tuple[list[SanitationTask], ResourceEstimate, DurationEstimate]:
    """Assemble ordered tasks, calculate resource demands and durations."""
    tasks = build_tasks_from_template(template, context)
    resource_est = estimate_plan_resources(tasks, template, context)
    duration_est = estimate_plan_duration(tasks, context)
    return tasks, resource_est, duration_est
