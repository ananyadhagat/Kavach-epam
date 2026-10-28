from typing import Any
from app.policies.resource_rules import (
    RESOURCE_POLICY_VERSION,
    calculate_task_resource_demand,
    compute_worker_demand,
)
from app.policies.template_registry import SanitationTemplate
from app.schemas.sanitation_response import EstimateStatus, ResourceEstimate
from app.schemas.sanitation_task import SanitationTask
from app.services.context_builder import PlanningContext


def estimate_resources(tasks: list[Any]) -> dict[str, Any]:
    """Legacy helper for backward-compatibility with unit tests."""
    resources = set()
    for task in tasks:
        req = getattr(task, "required_resources", [])
        for r in req:
            if isinstance(r, str):
                if r.strip():
                    resources.add(r.strip())
            else:
                code = getattr(r, "resource_code", None)
                if code:
                    resources.add(code.strip())

    sorted_res = sorted(resources)
    return {
        "required_resources": sorted_res,
        "resource_count": len(sorted_res),
        "worker_count": None,
        "availability_confirmed": False,
        "requires_human_review": True,
        "estimation_basis": "Derived from sanitation task policies.",
    }


def estimate_plan_resources(
    tasks: list[SanitationTask],
    template: SanitationTemplate,
    context: PlanningContext,
) -> ResourceEstimate:
    """Deterministically calculate resource demand per task and aggregate for the plan."""
    rule_lookup = {r.task_code: r for r in template.tasks}

    all_resources_set: set[str] = set()
    total_demands = 0
    quantified_demands = 0

    for task in tasks:
        rule = rule_lookup.get(task.task_code)
        resource_codes = rule.default_resource_codes if rule else []

        task_demands = []
        for r_code in resource_codes:
            demand = calculate_task_resource_demand(
                resource_code=r_code,
                task_code=task.task_code,
                estimated_waste_kg=context.estimated_waste_kg,
                affected_area_sqm=context.affected_area_sqm,
            )
            task_demands.append(demand)
            all_resources_set.add(demand.resource_code)
            total_demands += 1
            if demand.quantity is not None:
                quantified_demands += 1

        task.required_resources = task_demands

    # Determine aggregate estimate status
    if total_demands == 0:
        status = EstimateStatus.COMPLETE
    elif quantified_demands == total_demands:
        status = EstimateStatus.COMPLETE
    elif quantified_demands > 0:
        status = EstimateStatus.PARTIAL
    else:
        status = EstimateStatus.NEEDS_MORE_DATA

    worker_demand = compute_worker_demand(context.priority, len(tasks))

    return ResourceEstimate(
        status=status,
        required_resources=sorted(all_resources_set),
        estimated_worker_demand=worker_demand,
        availability_confirmed=False,
        resource_policy_version=RESOURCE_POLICY_VERSION,
    )
