from datetime import datetime
from typing import Any

from app.policies.duration_rules import calculate_task_duration
from app.schemas.sanitation_response import DurationEstimate, DurationStatus
from app.schemas.sanitation_task import DurationEstimateStatus, SanitationTask
from app.services.context_builder import PlanningContext


def calculate_critical_path_minutes(tasks: list[SanitationTask]) -> tuple[float | None, list[str]]:
    """Compute the total elapsed time using the dependency DAG's critical path.

    Returns:
        (total_minutes, missing_basis_reasons)
    """
    if not tasks:
        return 0.0, []

    task_map = {t.task_id: t for t in tasks}
    earliest_finish: dict[str, float] = {}
    missing_reasons: list[str] = []

    for task in tasks:
        dur = task.estimated_duration
        if dur.status != DurationEstimateStatus.CALCULATED or dur.minutes is None:
            for b in dur.basis:
                if b not in missing_reasons:
                    missing_reasons.append(b)

    if missing_reasons:
        return None, missing_reasons

    # All tasks have numeric durations, compute critical path
    for task in tasks:
        task_minutes = task.estimated_duration.minutes or 0.0
        dep_finish_times = [
            earliest_finish.get(dep_id, 0.0)
            for dep_id in task.depends_on
            if dep_id in task_map
        ]
        max_dep = max(dep_finish_times) if dep_finish_times else 0.0
        earliest_finish[task.task_id] = max_dep + task_minutes

    total_critical_path = max(earliest_finish.values()) if earliest_finish else 0.0
    return round(total_critical_path, 1), []


def estimate_plan_duration(
    tasks: list[SanitationTask],
    context: PlanningContext,
) -> DurationEstimate:
    """Calculate per-task duration and overall critical-path duration for the plan."""
    # 1. Compute per-task duration
    for task in tasks:
        task.estimated_duration = calculate_task_duration(
            task_code=task.task_code,
            estimated_waste_kg=context.estimated_waste_kg,
            affected_area_sqm=context.affected_area_sqm,
        )

    # 2. Critical path computation
    total_minutes, missing_reasons = calculate_critical_path_minutes(tasks)

    sla_started = None
    sla_resp = None
    sla_resol = None
    if context.sla:
        sla_resp = context.sla.get("response_due_at")
        sla_resol = context.sla.get("resolution_due_at")
        if isinstance(sla_resp, str):
            sla_resp = datetime.fromisoformat(sla_resp)
        if isinstance(sla_resol, str):
            sla_resol = datetime.fromisoformat(sla_resol)

    if total_minutes is not None:
        status = DurationStatus.CALCULATED
        basis = ["ALL_TASK_PRODUCTIVITY_RATES_AND_QUANTITIES_VALIDATED"]
    else:
        status = DurationStatus.NEEDS_MORE_DATA
        basis = missing_reasons or ["TASK_DURATION_INPUTS_INCOMPLETE"]

    return DurationEstimate(
        status=status,
        total_minutes=total_minutes,
        range_minutes=None,
        method="DEPENDENCY_CRITICAL_PATH",
        basis=basis,
        sla_response_due_at=sla_resp,
        sla_resolution_due_at=sla_resol,
    )
