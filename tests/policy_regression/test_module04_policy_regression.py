from datetime import datetime, timezone
import pytest

from app.policies.template_registry import SAN_TEMPLATES
from app.repositories.idempotency_repository import InMemoryIdempotencyRepository
from app.repositories.plan_repository import InMemoryPlanRepository
from app.repositories.template_repository import InMemoryTemplateRepository
from app.schemas.duplicate_contract import DuplicateDecision, DuplicateResult
from app.schemas.incident_contract import IncidentRecord, LocationData
from app.schemas.sanitation_request import ReplanContext, SanitationPlanRequest
from app.schemas.supervisor_contract import (
    ActionPlan,
    RoutingInfo,
    SupervisorDecision,
    SupervisorDecisionStatus,
)
from app.services.sanitation_planning_service import SanitationPlanningService


@pytest.mark.parametrize(
    "template_id,category,incident_type",
    [
        ("BIN_OVERFLOW_RESPONSE", "WASTE_OVERFLOW", "BIN_OVERFLOW"),
        ("GARBAGE_PILE_REMOVAL", "WASTE_OVERFLOW", "GARBAGE_PILE"),
        ("PUBLIC_TOILET_CLEANING", "FACILITY_CLEANING", "DIRTY_PUBLIC_TOILET"),
        ("SPILL_RESPONSE", "HAZARD_OR_SPILL", "WASTE_SPILL"),
    ],
)
def test_all_approved_templates_expand_correctly(template_id, category, incident_type):
    service = SanitationPlanningService(
        template_repository=InMemoryTemplateRepository(),
        plan_repository=InMemoryPlanRepository(),
        idempotency_repository=InMemoryIdempotencyRepository(),
    )

    now = datetime(2026, 10, 22, 10, 0, 0, tzinfo=timezone.utc)
    req = SanitationPlanRequest(
        contract_version="1.0.0",
        event_id=f"evt-policy-{template_id}",
        incident=IncidentRecord(
            incident_id=f"INC-{template_id}",
            complaint_id=f"CMP-{template_id}",
            category=category,
            incident_type=incident_type,
            reported_at=now,
            location=LocationData(facility_id="SITE-01", location_id="LOC-01"),
            estimated_waste_kg=100.0,
            affected_area_sqm=25.0,
        ),
        duplicate_result=DuplicateResult(
            decision=DuplicateDecision.NEW,
        ),
        supervisor_decision=SupervisorDecision(
            decision_id=f"SUP-{template_id}",
            decision_status=SupervisorDecisionStatus.APPROVED_TO_PROCEED,
            department="SANITATION",
            priority="HIGH",
            routing=RoutingInfo(status="RESOLVED", facility_id="SITE-01", location_id="LOC-01"),
            action_plan=ActionPlan(
                template_id=template_id,
                template_version="1",
                objective=f"Resolve {incident_type}",
            ),
        ),
    )

    plan, _ = service.create_plan(req)

    assert plan.planning_status.value in ("PLAN_READY", "PRELIMINARY_PLAN")
    assert plan.template.template_id == template_id
    assert len(plan.tasks) >= 3
    assert all(t.status.value == "NOT_STARTED" for t in plan.tasks)
    assert len(plan.safety_constraints) > 0

    # Verify dependency IDs all point to existing tasks
    task_ids = {t.task_id for t in plan.tasks}
    for t in plan.tasks:
        for dep in t.depends_on:
            assert dep in task_ids


def test_replan_linkage_preserves_previous_plan():
    service = SanitationPlanningService(
        template_repository=InMemoryTemplateRepository(),
        plan_repository=InMemoryPlanRepository(),
        idempotency_repository=InMemoryIdempotencyRepository(),
    )

    now = datetime(2026, 10, 22, 10, 0, 0, tzinfo=timezone.utc)
    req1 = SanitationPlanRequest(
        contract_version="1.0.0",
        event_id="evt-replan-01",
        incident=IncidentRecord(
            incident_id="INC-REPLAN-100",
            complaint_id="CMP-REPLAN-100",
            category="WASTE_OVERFLOW",
            incident_type="BIN_OVERFLOW",
            reported_at=now,
        ),
        duplicate_result=DuplicateResult(decision=DuplicateDecision.NEW),
        supervisor_decision=SupervisorDecision(
            decision_id="SUP-REPLAN-01",
            decision_status=SupervisorDecisionStatus.APPROVED_TO_PROCEED,
            action_plan=ActionPlan(template_id="BIN_OVERFLOW_RESPONSE", template_version="1"),
        ),
    )
    plan1, _ = service.create_plan(req1)
    assert plan1.previous_plan_id is None

    # Now a replan request arrives referencing plan1
    req2 = SanitationPlanRequest(
        contract_version="1.0.0",
        event_id="evt-replan-02",
        incident=IncidentRecord(
            incident_id="INC-REPLAN-100",
            complaint_id="CMP-REPLAN-100",
            category="WASTE_OVERFLOW",
            incident_type="BIN_OVERFLOW",
            reported_at=now,
            estimated_waste_kg=250.0,  # Revised measurements
        ),
        duplicate_result=DuplicateResult(decision=DuplicateDecision.NEW),
        supervisor_decision=SupervisorDecision(
            decision_id="SUP-REPLAN-02",
            decision_status=SupervisorDecisionStatus.APPROVED_TO_PROCEED,
            action_plan=ActionPlan(template_id="BIN_OVERFLOW_RESPONSE", template_version="1"),
        ),
        replan_context=ReplanContext(
            previous_plan_id=plan1.plan_id,
            replan_reason="Worker reported larger waste volume than initial complaint",
        ),
    )
    plan2, _ = service.create_plan(req2)
    assert plan2.previous_plan_id == plan1.plan_id
    assert plan2.replan_reason == "Worker reported larger waste volume than initial complaint"
