# src/kavach/services/supervisor/output_validator.py
from __future__ import annotations

from datetime import datetime
from typing import Optional, Sequence
from uuid import uuid4

from kavach.schemas.supervisor import (
    ApprovalStatus,
    AuditLogRecord,
    DecisionStatus,
    GeminiSupervisorSuggestion,
    PriorityLevel,
    RoutingDirective,
    SupervisorDecisionRecord,
    SupervisorEvaluationResponse,
    SupervisorIncidentInput,
    most_severe,
)
from kavach.services.supervisor.reference_data import (
    CURRENT_POLICY_VERSION,
    DEFAULT_UNRECOGNIZED_PRIORITY,
    DEPARTMENT_ROSTER,
    SLA_POLICY_BY_PRIORITY,
    WARD_ROUTE_MAP,
    evaluate_approval_rules,
)

DEFAULT_ACTOR = "supervisor_agent"


def build_needs_review_response(
    incident: SupervisorIncidentInput,
    reason_codes: Sequence[str],
    rationale: str,
    *,
    department: Optional[str] = None,
    ward_or_route: Optional[str] = None,
    floor_priority: Optional[PriorityLevel] = None,
    actor: str = DEFAULT_ACTOR,
) -> SupervisorEvaluationResponse:
    """Safe NEEDS_REVIEW decision: null deadlines, dispatch_eligible=False, priority always P1-P4."""
    reasons = list(reason_codes) or ["VALIDATION_FAILED"]

    priority = incident.resolved_priority
    if priority is None:
        priority = DEFAULT_UNRECOGNIZED_PRIORITY
        if "PRIORITY_DEFAULTED_FOR_REVIEW" not in reasons:
            reasons.append("PRIORITY_DEFAULTED_FOR_REVIEW")
    if floor_priority is not None:
        priority = most_severe(priority, floor_priority)

    decision_id = uuid4()
    decision = SupervisorDecisionRecord(
        decision_id=decision_id,
        incident_id=incident.incident_id,
        duplicate_check_id=incident.duplicate_check_id,
        department=department if department in DEPARTMENT_ROSTER else None,
        priority=priority,
        ward_or_route=ward_or_route if ward_or_route in WARD_ROUTE_MAP else None,
        response_deadline=None,
        resolution_deadline=None,
        decision_status=DecisionStatus.NEEDS_REVIEW,
        approval_status=ApprovalStatus.NOT_APPLICABLE,
        policy_version=CURRENT_POLICY_VERSION,
    )
    routing = RoutingDirective(next_process="8.0_PLATFORM_REVIEW", dispatch_eligible=False)
    audit = AuditLogRecord(
        entity_id=decision_id,
        actor=actor,
        action="SUPERVISOR_EVALUATION_NEEDS_REVIEW",
        reason_codes=reasons,
        rationale=rationale,
    )
    return SupervisorEvaluationResponse(supervisor_decision=decision, routing=routing, audit=audit)


def validate_and_finalize_decision(
    incident: SupervisorIncidentInput,
    suggestion: Optional[GeminiSupervisorSuggestion],
    *,
    extra_reason_codes: Sequence[str] = (),
    actor: str = DEFAULT_ACTOR,
    llm_failure_note: Optional[str] = None,
) -> SupervisorEvaluationResponse:
    """
    Deterministic validation of the LLM suggestion:
    - priority = most severe of (Agent 1 severity, Gemini suggestion); never lowered
    - department and ward must exist in the roster / ward map
    - SLA deadlines computed from the final priority
    - approval rules decide APPROVED_TO_PROCEED vs PENDING_APPROVAL
    """
    extra = list(extra_reason_codes)

    if suggestion is None:
        note = f" ({llm_failure_note})" if llm_failure_note else ""
        return build_needs_review_response(
            incident,
            ["LLM_EVALUATION_FAILED", *extra],
            f"Gemini evaluation failed or timed out{note}; routed to human review.",
            actor=actor,
        )

    base_priority = incident.resolved_priority
    if base_priority is None:
        return build_needs_review_response(
            incident,
            ["UNRECOGNIZED_PRIORITY_OR_SEVERITY", *extra],
            f"Incident severity '{incident.severity}' could not be mapped to P1-P4.",
            actor=actor,
        )

    final_priority = base_priority
    priority_reasons: list[str] = []
    escalated = False

    if suggestion.suggested_priority != base_priority:
        higher = most_severe(final_priority, suggestion.suggested_priority)
        if higher != final_priority:
            final_priority = higher
            escalated = True
            priority_reasons.append("PRIORITY_ESCALATED_BY_SUPERVISOR")

    dept_code = suggestion.department.strip().upper()
    ward_code = suggestion.ward_or_route.strip().upper()
    validation_errors: list[str] = []

    if dept_code not in DEPARTMENT_ROSTER:
        validation_errors.append("INVALID_DEPARTMENT_FROM_LLM")
    else:
        dept_spec = DEPARTMENT_ROSTER[dept_code]
        cat_norm = incident.category.strip().upper()
        type_norm = incident.incident_type.strip().upper()
        if (
            cat_norm not in dept_spec.supported_categories
            and type_norm not in dept_spec.supported_incident_types
        ):
            validation_errors.append("DEPARTMENT_TAXONOMY_CONFLICT")
        elif dept_spec.downstream_process is None:
            validation_errors.append("NO_DOMAIN_AGENT_FOR_DEPARTMENT")

    if ward_code not in WARD_ROUTE_MAP:
        validation_errors.append("INVALID_WARD_FROM_LLM")

    if validation_errors:
        return build_needs_review_response(
            incident,
            [*validation_errors, *priority_reasons, *extra],
            (
                f"Supervisor validation failed ({', '.join(validation_errors)}) "
                f"for suggested department='{dept_code}', ward='{ward_code}'."
            ),
            department=dept_code,
            ward_or_route=ward_code,
            floor_priority=final_priority,
            actor=actor,
        )

    sla_spec = SLA_POLICY_BY_PRIORITY[final_priority]
    response_deadline: datetime = incident.reported_at + sla_spec.response_delta
    resolution_deadline: datetime = incident.reported_at + sla_spec.resolution_delta

    needs_approval, approval_reasons = evaluate_approval_rules(incident, final_priority)
    if escalated:
        needs_approval = True
        approval_reasons.append("APPROVAL_RULE_PRIORITY_ESCALATED")

    combined = list(
        dict.fromkeys([*suggestion.reason_codes, *priority_reasons, *approval_reasons, *extra])
    )

    if needs_approval:
        decision_status = DecisionStatus.PENDING_APPROVAL
        approval_status = ApprovalStatus.PENDING
        next_process = "HUMAN_SUPERVISOR_APPROVAL_AND_8.0_NOTIFY"
        dispatch_eligible = False
        action = "SUPERVISOR_EVALUATION_PENDING_APPROVAL"
    else:
        decision_status = DecisionStatus.APPROVED_TO_PROCEED
        approval_status = ApprovalStatus.NOT_REQUIRED
        next_process = DEPARTMENT_ROSTER[dept_code].downstream_process or "4.0_SANITATION_PLANNING"
        dispatch_eligible = True
        if "ROUTINE_AUTO_APPROVED" not in combined:
            combined.append("ROUTINE_AUTO_APPROVED")
        action = "SUPERVISOR_EVALUATION_APPROVED"

    decision_id = uuid4()
    decision = SupervisorDecisionRecord(
        decision_id=decision_id,
        incident_id=incident.incident_id,
        duplicate_check_id=incident.duplicate_check_id,
        department=dept_code,
        priority=final_priority,
        ward_or_route=ward_code,
        response_deadline=response_deadline,
        resolution_deadline=resolution_deadline,
        decision_status=decision_status,
        approval_status=approval_status,
        policy_version=CURRENT_POLICY_VERSION,
    )
    routing = RoutingDirective(next_process=next_process, dispatch_eligible=dispatch_eligible)
    audit = AuditLogRecord(
        entity_id=decision_id,
        actor=actor,
        action=action,
        reason_codes=combined,
        rationale=suggestion.rationale.strip(),
    )
    return SupervisorEvaluationResponse(supervisor_decision=decision, routing=routing, audit=audit)
