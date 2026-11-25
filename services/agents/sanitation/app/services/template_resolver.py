from dataclasses import dataclass
from typing import Optional

from app.policies.template_registry import SanitationTemplate
from app.repositories.template_repository import TemplateRepository, template_repo
from app.schemas.duplicate_contract import DuplicateDecision
from app.schemas.supervisor_contract import SupervisorDecisionStatus
from app.services.context_builder import PlanningContext


@dataclass
class TemplateResolutionResult:
    """Result of template resolution and upstream gate checks."""

    template: Optional[SanitationTemplate] = None
    is_held: bool = False
    hold_reason_codes: list[str] = None
    blocking_status: Optional[str] = None

    def __post_init__(self):
        if self.hold_reason_codes is None:
            self.hold_reason_codes = []


def resolve_template(
    context: PlanningContext,
    repository: TemplateRepository = template_repo,
) -> TemplateResolutionResult:
    """Evaluate upstream decision gates and resolve the authorized sanitation template.

    Gate sequence (per spec Section 4 Required Input Gates):
      1. Supervisor evaluation_status must be COMPLETED.
      2. Supervisor decision_status must be APPROVED_TO_PROCEED.
      3. Duplicate processing_status must be COMPLETED.
      4. Duplicate retrieval status must be COMPLETE.
      5. Duplicate decision must be NEW.
      6. Routing must be RESOLVED.
      7. Template ID must be present.
      8. Template must exist and be enabled.
      9. Taxonomy compatibility (category, incident_type, department, priority).
      10. Supervisor required_actions cross-check against template task codes.
    """
    # Gate 1: Supervisor Evaluation Gate
    # If evaluation_status is not COMPLETED, do not build an operational plan.
    if context.supervisor_evaluation_status != "COMPLETED":
        return TemplateResolutionResult(
            is_held=True,
            hold_reason_codes=["SUPERVISOR_EVALUATION_INCOMPLETE"],
            blocking_status="BLOCKED",
        )

    # Gate 2: Supervisor Decision Gate
    if context.supervisor_decision_status != SupervisorDecisionStatus.APPROVED_TO_PROCEED.value:
        if context.supervisor_decision_status == SupervisorDecisionStatus.PENDING_APPROVAL.value:
            return TemplateResolutionResult(
                is_held=True,
                hold_reason_codes=["SUPERVISOR_PENDING_APPROVAL", "SUPERVISOR_NOT_APPROVED"],
                blocking_status="BLOCKED",
            )
        return TemplateResolutionResult(
            is_held=True,
            hold_reason_codes=["SUPERVISOR_NOT_APPROVED"],
            blocking_status="NEEDS_REVIEW",
        )

    # Gate 3: Duplicate Processing Status Gate
    if context.duplicate_processing_status != "COMPLETED":
        return TemplateResolutionResult(
            is_held=True,
            hold_reason_codes=["DUPLICATE_PROCESSING_INCOMPLETE", "UPSTREAM_DEPENDENCY_NOT_READY"],
            blocking_status="BLOCKED",
        )

    # Gate 4: Duplicate Retrieval Status Gate
    # Incomplete retrieval means we cannot assume the incident is new.
    if context.duplicate_retrieval_status != "COMPLETE":
        return TemplateResolutionResult(
            is_held=True,
            hold_reason_codes=["DUPLICATE_RETRIEVAL_INCOMPLETE", "CANNOT_ASSUME_NEW_INCIDENT"],
            blocking_status="BLOCKED",
        )

    # Gate 5: Duplicate Decision Gate
    if context.duplicate_decision == DuplicateDecision.REVIEW_REQUIRED.value:
        return TemplateResolutionResult(
            is_held=True,
            hold_reason_codes=["DUPLICATE_REVIEW_HOLD"],
            blocking_status="NEEDS_REVIEW",
        )
    elif context.duplicate_decision == DuplicateDecision.DUPLICATE.value:
        return TemplateResolutionResult(
            is_held=True,
            hold_reason_codes=["DUPLICATE_OF_EXISTING_INCIDENT"],
            blocking_status="BLOCKED",
        )
    elif context.duplicate_decision != DuplicateDecision.NEW.value:
        return TemplateResolutionResult(
            is_held=True,
            hold_reason_codes=["DUPLICATE_RESULT_UNRELIABLE"],
            blocking_status="NEEDS_REVIEW",
        )

    # Gate 6: Routing Gate
    # Routing must be RESOLVED before a dispatch-eligible plan can be produced.
    if context.routing_status != "RESOLVED":
        return TemplateResolutionResult(
            is_held=True,
            hold_reason_codes=["ROUTING_UNRESOLVED"],
            blocking_status="NEEDS_REVIEW",
        )

    # Gate 7: Supervisor Template ID Presence
    template_id = context.action_plan_template_id
    template_version = context.action_plan_template_version or "1"

    if not template_id:
        return TemplateResolutionResult(
            is_held=True,
            hold_reason_codes=["TEMPLATE_NOT_FOUND_OR_DISABLED"],
            blocking_status="NEEDS_REVIEW",
        )

    # Gate 8: Registry Lookup — template must exist and be enabled
    template = repository.get(template_id, template_version)
    if template is None or not template.enabled:
        return TemplateResolutionResult(
            is_held=True,
            hold_reason_codes=["TEMPLATE_NOT_FOUND_OR_DISABLED"],
            blocking_status="NEEDS_REVIEW",
        )

    # Gate 9: Taxonomy and Compatibility Verification
    # Do not derive a new category from complaint_text — only use upstream facts!
    if context.category not in template.allowed_categories:
        return TemplateResolutionResult(
            is_held=True,
            hold_reason_codes=["TEMPLATE_POLICY_CONFLICT", "TEMPLATE_CATEGORY_MISMATCH"],
            blocking_status="NEEDS_REVIEW",
        )

    if context.incident_type not in template.allowed_incident_types:
        return TemplateResolutionResult(
            is_held=True,
            hold_reason_codes=["TEMPLATE_POLICY_CONFLICT", "TEMPLATE_TYPE_MISMATCH"],
            blocking_status="NEEDS_REVIEW",
        )

    if context.department not in template.allowed_departments:
        return TemplateResolutionResult(
            is_held=True,
            hold_reason_codes=["TEMPLATE_POLICY_CONFLICT", "TEMPLATE_DEPARTMENT_MISMATCH"],
            blocking_status="NEEDS_REVIEW",
        )

    # Priority restriction check (per spec §3.3 — validate priority restrictions)
    if context.priority not in template.allowed_priorities:
        return TemplateResolutionResult(
            is_held=True,
            hold_reason_codes=["TEMPLATE_POLICY_CONFLICT", "TEMPLATE_PRIORITY_MISMATCH"],
            blocking_status="NEEDS_REVIEW",
        )

    # Gate 10: Supervisor required_actions cross-check against template task codes.
    # If the Supervisor authorized a required action that this template does not contain,
    # that is a contract inconsistency that must be held for review.
    template_task_codes = {rule.task_code for rule in template.tasks}
    unsatisfied_actions = [
        action for action in context.supervisor_required_actions
        if action not in template_task_codes
    ]
    if unsatisfied_actions:
        return TemplateResolutionResult(
            is_held=True,
            hold_reason_codes=[
                "TEMPLATE_POLICY_CONFLICT",
                "SUPERVISOR_REQUIRED_ACTIONS_NOT_IN_TEMPLATE",
            ],
            blocking_status="NEEDS_REVIEW",
        )

    return TemplateResolutionResult(
        template=template,
        is_held=False,
        hold_reason_codes=[],
    )
