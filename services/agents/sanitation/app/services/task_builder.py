from app.policies.template_registry import SanitationTemplate, TaskRule
from app.schemas.sanitation_task import SanitationTask, SanitationTaskStatus
from app.services.context_builder import PlanningContext


def evaluate_task_condition(
    predicate_name: str | None,
    context: PlanningContext,
) -> bool | None:
    """Evaluate tri-state condition predicate: returns True, False, or None (unknown)."""
    if predicate_name is None:
        return True

    if predicate_name == "check_path_obstruction":
        # Returns True if obstructed, False if confirmed clear, None if unknown
        return context.path_obstructed

    if predicate_name == "check_hazard":
        return context.hazard_detected

    return None


def build_tasks_from_template(
    template: SanitationTemplate,
    context: PlanningContext,
) -> list[SanitationTask]:
    """Deterministically expand template task rules into ordered SanitationTask objects."""
    selected_rules: list[TaskRule] = []

    for rule in template.tasks:
        if rule.required:
            selected_rules.append(rule)
        else:
            cond_val = evaluate_task_condition(rule.condition_predicate_name, context)
            if cond_val is True:
                selected_rules.append(rule)
            elif cond_val is None:
                # Tri-state fact: None is not False.
                if rule.unknown_behavior in ("INSPECT", "REVIEW"):
                    selected_rules.append(rule)
                # If OMIT, skip

    # Sort by sequence
    selected_rules.sort(key=lambda r: r.sequence)

    # Assign stable task IDs: SAN-T001, SAN-T002, ...
    code_to_task_id: dict[str, str] = {}
    for idx, rule in enumerate(selected_rules, start=1):
        task_id = f"SAN-T{idx:03d}"
        code_to_task_id[rule.task_code] = task_id

    tasks: list[SanitationTask] = []
    for idx, rule in enumerate(selected_rules, start=1):
        task_id = code_to_task_id[rule.task_code]

        # Map dependency codes to generated task_ids
        depends_on = [
            code_to_task_id[dep_code]
            for dep_code in rule.depends_on_codes
            if dep_code in code_to_task_id
        ]

        task = SanitationTask(
            task_id=task_id,
            sequence=idx,
            task_code=rule.task_code,
            title=rule.title,
            description=rule.description,
            depends_on=depends_on,
            completion_criteria=list(rule.completion_criteria),
            status=SanitationTaskStatus.NOT_STARTED,
        )
        tasks.append(task)

    return tasks
