from datetime import datetime, timezone
from typing import Any
import uuid

from app.policies.duration_rules import DURATION_POLICY_VERSION
from app.policies.resource_rules import RESOURCE_POLICY_VERSION
from app.policies.safety_rules import SAFETY_POLICY_VERSION, get_default_safety_constraints
from app.repositories.audit_repository import PlanAuditRecord, audit_repo
from app.repositories.idempotency_repository import idempotency_repo
from app.repositories.plan_repository import plan_repo
from app.repositories.template_repository import template_repo
from app.schemas.sanitation_request import SanitationPlanRequest
from app.schemas.sanitation_response import (
    DurationEstimate,
    EstimateStatus,
    DurationStatus,
    PlanningStatus,
    ResourceEstimate,
    SanitationPlanResult,
    TemplateReference,
)
from app.schemas.supervisor_contract import RoutingInfo
from app.services.checklist_builder import build_plan_checklist
from app.services.context_builder import build_planning_context
from app.services.dispatch_eligibility import evaluate_dispatch_eligibility
from app.services.plan_validator import validate_plan_result
from app.services.template_resolver import resolve_template


class SanitationPlanningService:
    """Deterministic, policy-driven planning service for KAVACH Module 04."""

    def __init__(
        self,
        template_repository=template_repo,
        plan_repository=plan_repo,
        idempotency_repository=idempotency_repo,
        audit_repository=audit_repo,
    ):
        self.template_repo = template_repository
        self.plan_repo = plan_repository
        self.idempotency_repo = idempotency_repository
        self.audit_repo = audit_repository

    def create_plan(
        self,
        request: SanitationPlanRequest,
        idempotency_key: str | None = None,
    ) -> tuple[SanitationPlanResult, bool]:
        """Execute the deterministic sanitation planning pipeline.

        Returns:
            (SanitationPlanResult, is_replay: bool)
        """
        effective_key = idempotency_key or request.event_id

        # Wrap plan computation in result factory for idempotency
        def plan_factory() -> SanitationPlanResult:
            return self._compute_plan(request)

        result, is_replay = self.idempotency_repo.check_or_record(
            key=effective_key,
            payload_dict=request.model_dump(),
            result_factory=plan_factory,
        )

        if not is_replay:
            # Persist to plan repository
            self.plan_repo.save(result)

            # Persist to audit repository
            self.audit_repo.record_audit(
                PlanAuditRecord(
                    plan_id=result.plan_id,
                    incident_id=result.incident_id,
                    event_id=result.event_id,
                    supervisor_decision_id=result.supervisor_decision_id,
                    contract_version=result.contract_version,
                    planning_status=result.planning_status.value,
                    dispatch_eligible=result.dispatch_eligible,
                    template_version=result.template.template_version if result.template else None,
                    policy_versions=result.policy_versions,
                    reason_codes=result.reason_codes,
                    hold_reason_codes=result.hold_reason_codes,
                )
            )

        return result, is_replay

    def _compute_plan(self, request: SanitationPlanRequest) -> SanitationPlanResult:
        context = build_planning_context(request)
        created_at = datetime.now(timezone.utc)
        base_plan_id = f"SAN-PLAN-{context.incident_id.replace('INC-', '')}"
        if request.replan_context:
            existing = self.plan_repo.get_by_incident_id(context.incident_id)
            replan_num = len(existing) + 1 if existing else 1
            plan_id = f"{base_plan_id}-R{replan_num}"
        else:
            plan_id = base_plan_id

        # Upstream gates and template resolution
        resolution = resolve_template(context, self.template_repo)

        # Gate failure / Hold handling
        if resolution.is_held or resolution.template is None:
            planning_status_val = (
                PlanningStatus(resolution.blocking_status)
                if resolution.blocking_status in PlanningStatus.__members__
                else PlanningStatus.NEEDS_REVIEW
            )

            result = SanitationPlanResult(
                contract_version=request.contract_version,
                plan_id=plan_id,
                event_id=request.event_id,
                incident_id=context.incident_id,
                complaint_id=context.complaint_id,
                supervisor_decision_id=request.supervisor_decision.decision_id,
                planning_status=planning_status_val,
                dispatch_eligible=False,
                hold_reason_codes=resolution.hold_reason_codes,
                department=context.department,
                priority=context.priority,
                routing=request.supervisor_decision.routing,
                template=None,
                objective=context.action_plan_objective,
                tasks=[],
                resource_estimate=ResourceEstimate(
                    status=EstimateStatus.NEEDS_MORE_DATA,
                    required_resources=[],
                    availability_confirmed=False,
                    resource_policy_version=RESOURCE_POLICY_VERSION,
                ),
                duration_estimate=DurationEstimate(
                    status=DurationStatus.NEEDS_MORE_DATA,
                    total_minutes=None,
                    method="DEPENDENCY_CRITICAL_PATH",
                    basis=list(resolution.hold_reason_codes),
                    sla_response_due_at=request.supervisor_decision.sla.response_due_at if request.supervisor_decision.sla else None,
                    sla_resolution_due_at=request.supervisor_decision.sla.resolution_due_at if request.supervisor_decision.sla else None,
                ),
                safety_constraints=get_default_safety_constraints(
                    context.category,
                    context.incident_type,
                    context.hazard_detected,
                ),
                assumptions=["Operational planning held at decision gate."],
                reason_codes=list(resolution.hold_reason_codes),
                policy_versions={
                    "resource": RESOURCE_POLICY_VERSION,
                    "duration": DURATION_POLICY_VERSION,
                    "safety": SAFETY_POLICY_VERSION,
                },
                created_at=created_at,
                previous_plan_id=request.replan_context.previous_plan_id if request.replan_context else None,
                replan_reason=request.replan_context.replan_reason if request.replan_context else None,
            )
            return validate_plan_result(result)

        template = resolution.template

        # Deterministic task, resource, and duration building
        tasks, resource_est, duration_est = build_plan_checklist(template, context)

        # Assess completeness of estimates
        hold_reasons: list[str] = []
        assumptions: list[str] = [
            "Resource availability is not checked by Module 04",
        ]

        if context.estimated_waste_kg is None:
            hold_reasons.append("QUANTITY_NOT_MEASURED")
            assumptions.append("Waste quantity has not been measured")

        if duration_est.status != DurationStatus.CALCULATED:
            for b in duration_est.basis:
                if b not in hold_reasons:
                    hold_reasons.append(b)

        # Planning Status Determination
        if hold_reasons or duration_est.status == DurationStatus.NEEDS_MORE_DATA or resource_est.status != EstimateStatus.COMPLETE:
            planning_status = PlanningStatus.PRELIMINARY_PLAN
        else:
            planning_status = PlanningStatus.PLAN_READY

        # Dispatch eligibility check
        dispatch_eligible = evaluate_dispatch_eligibility(
            planning_status=planning_status,
            context=context,
            template_enabled=template.enabled,
            hold_reason_codes=hold_reasons,
        )

        reason_codes = ["TEMPLATE_RESOLVED", "PLAN_VALIDATED"]
        if planning_status == PlanningStatus.PRELIMINARY_PLAN:
            reason_codes.append("ESTIMATES_PRELIMINARY")
        elif planning_status == PlanningStatus.PLAN_READY:
            reason_codes.append("PLAN_READY_FOR_DISPATCH")

        # Compile safety constraints
        combined_safety = list(template.safety_constraints)
        for constraint in context.supervisor_constraints:
            if constraint not in combined_safety:
                combined_safety.append(constraint)

        template_ref = TemplateReference(
            template_id=template.template_id,
            template_version=template.template_version,
            policy_version=template.policy_version,
        )

        policy_versions = {
            "template": template.policy_version,
            "resource": RESOURCE_POLICY_VERSION,
            "duration": DURATION_POLICY_VERSION,
            "safety": SAFETY_POLICY_VERSION,
        }

        result = SanitationPlanResult(
            contract_version=request.contract_version,
            plan_id=plan_id,
            event_id=request.event_id,
            incident_id=context.incident_id,
            complaint_id=context.complaint_id,
            supervisor_decision_id=request.supervisor_decision.decision_id,
            planning_status=planning_status,
            dispatch_eligible=dispatch_eligible,
            hold_reason_codes=hold_reasons,
            department=context.department,
            priority=context.priority,
            routing=request.supervisor_decision.routing,
            template=template_ref,
            objective=context.action_plan_objective or template.objective,
            tasks=tasks,
            resource_estimate=resource_est,
            duration_estimate=duration_est,
            safety_constraints=combined_safety,
            assumptions=assumptions,
            reason_codes=reason_codes,
            policy_versions=policy_versions,
            created_at=created_at,
            previous_plan_id=request.replan_context.previous_plan_id if request.replan_context else None,
            replan_reason=request.replan_context.replan_reason if request.replan_context else None,
        )

        return validate_plan_result(result)


# Singleton service instance
planning_service = SanitationPlanningService()
