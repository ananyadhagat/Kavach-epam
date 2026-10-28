from datetime import datetime, timezone
import pytest
from pydantic import ValidationError

from app.policies.duration_rules import calculate_task_duration
from app.policies.resource_rules import calculate_task_resource_demand, compute_worker_demand
from app.policies.safety_rules import check_forbidden_operational_claims
from app.policies.template_registry import SAN_TEMPLATES, SanitationTemplate, TaskRule
from app.repositories.audit_repository import InMemoryAuditRepository, PlanAuditRecord
from app.repositories.idempotency_repository import (
    IdempotencyConflictError,
    InMemoryIdempotencyRepository,
)
from app.repositories.plan_repository import InMemoryPlanRepository
from app.repositories.template_repository import InMemoryTemplateRepository
from app.schemas.duplicate_contract import DuplicateDecision, DuplicateResult
from app.schemas.incident_contract import IncidentRecord, LocationData
from app.schemas.sanitation_request import SanitationPlanRequest
from app.schemas.sanitation_response import (
    DurationStatus,
    EstimateStatus,
    PlanningStatus,
    SanitationPlanResult,
)
from app.schemas.sanitation_task import (
    DurationEstimateStatus,
    SanitationTask,
    SanitationTaskStatus,
)
from app.schemas.supervisor_contract import (
    ActionPlan,
    RoutingInfo,
    SLAInfo,
    SupervisorDecision,
    SupervisorDecisionStatus,
)
from app.services.checklist_builder import build_plan_checklist
from app.services.context_builder import build_planning_context
from app.services.dispatch_eligibility import evaluate_dispatch_eligibility
from app.services.duration_estimator import calculate_critical_path_minutes
from app.services.plan_validator import PlanValidationError, validate_plan_result
from app.services.sanitation_planning_service import SanitationPlanningService
from app.services.task_builder import build_tasks_from_template
from app.services.template_resolver import resolve_template


def sample_request(
    decision_status=SupervisorDecisionStatus.APPROVED_TO_PROCEED,
    duplicate_decision=DuplicateDecision.NEW,
    template_id="BIN_OVERFLOW_RESPONSE",
    category="WASTE_OVERFLOW",
    incident_type="BIN_OVERFLOW",
    department="SANITATION",
    estimated_waste_kg=50.0,
    event_id="evt-unit-001",
    path_obstructed=None,
):
    fixed_time = datetime(2026, 10, 21, 11, 55, 0, tzinfo=timezone.utc)
    sla_time = datetime(2026, 10, 21, 19, 55, 0, tzinfo=timezone.utc)
    return SanitationPlanRequest(
        contract_version="1.0.0",
        event_id=event_id,
        incident=IncidentRecord(
            incident_id="INC-UNIT-001",
            complaint_id="CMP-UNIT-001",
            category=category,
            incident_type=incident_type,
            reported_at=fixed_time,
            location=LocationData(facility_id="SITE-01", location_id="GATE"),
            estimated_waste_kg=estimated_waste_kg,
            path_obstructed=path_obstructed,
        ),
        duplicate_result=DuplicateResult(
            decision=duplicate_decision,
        ),
        supervisor_decision=SupervisorDecision(
            decision_id="SUP-UNIT-001",
            decision_status=decision_status,
            department=department,
            priority="HIGH",
            routing=RoutingInfo(status="RESOLVED", facility_id="SITE-01", location_id="GATE"),
            sla=SLAInfo(
                started_at=fixed_time,
                resolution_due_at=sla_time,
            ),
            action_plan=ActionPlan(
                template_id=template_id,
                template_version="1",
                objective="Test objective",
            ),
        ),
    )


# 1. Decision Gates
def test_supervisor_pending_approval_held():
    req = sample_request(decision_status=SupervisorDecisionStatus.PENDING_APPROVAL)
    ctx = build_planning_context(req)
    res = resolve_template(ctx)
    assert res.is_held is True
    assert "SUPERVISOR_NOT_APPROVED" in res.hold_reason_codes


def test_supervisor_needs_review_held():
    req = sample_request(decision_status=SupervisorDecisionStatus.NEEDS_REVIEW)
    ctx = build_planning_context(req)
    res = resolve_template(ctx)
    assert res.is_held is True
    assert "SUPERVISOR_NOT_APPROVED" in res.hold_reason_codes


def test_duplicate_review_required_held():
    req = sample_request(duplicate_decision=DuplicateDecision.REVIEW_REQUIRED)
    ctx = build_planning_context(req)
    res = resolve_template(ctx)
    assert res.is_held is True
    assert "DUPLICATE_REVIEW_HOLD" in res.hold_reason_codes


def test_duplicate_existing_incident_held():
    req = sample_request(duplicate_decision=DuplicateDecision.DUPLICATE)
    ctx = build_planning_context(req)
    res = resolve_template(ctx)
    assert res.is_held is True
    assert "DUPLICATE_OF_EXISTING_INCIDENT" in res.hold_reason_codes


# 2. Template Resolution
def test_template_resolution_mismatched_category():
    req = sample_request(category="PARKS_AND_REC")
    ctx = build_planning_context(req)
    res = resolve_template(ctx)
    assert res.is_held is True
    assert "TEMPLATE_POLICY_CONFLICT" in res.hold_reason_codes


def test_template_resolution_disabled():
    repo = InMemoryTemplateRepository()
    disabled_tmpl = SanitationTemplate(
        template_id="DISABLED_TMPL",
        template_version="1",
        enabled=False,
        title="Disabled",
        objective="None",
        allowed_categories=["WASTE_OVERFLOW"],
        allowed_incident_types=["BIN_OVERFLOW"],
    )
    repo.register(disabled_tmpl)
    req = sample_request(template_id="DISABLED_TMPL")
    ctx = build_planning_context(req)
    res = resolve_template(ctx, repository=repo)
    assert res.is_held is True
    assert "TEMPLATE_NOT_FOUND_OR_DISABLED" in res.hold_reason_codes


# 3. Tri-state facts & conditional task building
def test_tri_state_unknown_fact_triggers_inspection_task():
    # When path_obstructed is None (unknown), CHECK_PATH_CLEAR is included with unknown_behavior="INSPECT"
    req_unknown = sample_request(path_obstructed=None)
    ctx_unknown = build_planning_context(req_unknown)
    tasks_unknown = build_tasks_from_template(SAN_TEMPLATES[("BIN_OVERFLOW_RESPONSE", "1")], ctx_unknown)
    task_codes = [t.task_code for t in tasks_unknown]
    assert "CHECK_PATH_CLEAR" in task_codes


def test_tri_state_false_fact_omits_task_if_not_obstructed():
    # When path_obstructed is explicitly False, CHECK_PATH_CLEAR condition predicate is False
    req_clear = sample_request(path_obstructed=False)
    ctx_clear = build_planning_context(req_clear)
    tasks = build_tasks_from_template(SAN_TEMPLATES[("BIN_OVERFLOW_RESPONSE", "1")], ctx_clear)
    task_codes = [t.task_code for t in tasks]
    assert "CHECK_PATH_CLEAR" not in task_codes


# 4. Resource Estimation
def test_resource_estimation_quantified():
    demand = calculate_task_resource_demand("WASTE_CONTAINERS", "REMOVE_WASTE", estimated_waste_kg=50.0)
    assert demand.quantity == 2  # ceil(50 / 25)
    assert demand.unit == "BAG"
    assert "CALCULATED_FROM_ESTIMATED_WASTE_KG" in demand.basis


def test_resource_estimation_missing_quantity_is_none():
    demand = calculate_task_resource_demand("WASTE_CONTAINERS", "REMOVE_WASTE", estimated_waste_kg=None)
    assert demand.quantity is None
    assert demand.basis == "QUANTITY_DEPENDENT"


def test_crew_worker_demand_rules():
    crew_high = compute_worker_demand("HIGH", 4)
    assert crew_high.count == 2
    assert "LEAD_SANITATION_WORKER" in crew_high.roles

    crew_low = compute_worker_demand("LOW", 2)
    assert crew_low.count == 1


# 5. Duration Estimation and Critical Path DAG
def test_task_duration_formula():
    dur = calculate_task_duration("REMOVE_WASTE", estimated_waste_kg=150.0)
    # setup=10.0, prod=150 kg/h -> (150/150)*60 = 60m + 10m setup = 70.0 min
    assert dur.status == DurationEstimateStatus.CALCULATED
    assert dur.minutes == 70.0


def test_task_duration_missing_quantity():
    dur = calculate_task_duration("REMOVE_WASTE", estimated_waste_kg=None)
    assert dur.status == DurationEstimateStatus.NEEDS_MORE_DATA
    assert dur.minutes is None
    assert "WASTE_QUANTITY_NOT_MEASURED" in dur.basis


def test_critical_path_calculation():
    # T1 (15m) -> T2 (30m) -> T3 (10m)
    t1 = SanitationTask(
        task_id="T1", sequence=1, task_code="INSPECT", title="T1", description="desc",
        depends_on=[],
        estimated_duration={"minutes": 15.0, "status": "CALCULATED", "basis": []},
    )
    t2 = SanitationTask(
        task_id="T2", sequence=2, task_code="REMOVE", title="T2", description="desc",
        depends_on=["T1"],
        estimated_duration={"minutes": 30.0, "status": "CALCULATED", "basis": []},
    )
    t3 = SanitationTask(
        task_id="T3", sequence=3, task_code="CLEAN", title="T3", description="desc",
        depends_on=["T2"],
        estimated_duration={"minutes": 10.0, "status": "CALCULATED", "basis": []},
    )
    total, missing = calculate_critical_path_minutes([t1, t2, t3])
    assert total == 55.0  # 15 + 30 + 10
    assert missing == []


# 6. Safety validation
def test_safety_claim_validation():
    violations = check_forbidden_operational_claims("The cleaning has been completed by the team.")
    assert len(violations) > 0


# 7. In-Memory Repositories and Idempotency
def test_in_memory_idempotency_same_payload_returns_cached():
    service = SanitationPlanningService(
        template_repository=InMemoryTemplateRepository(),
        plan_repository=InMemoryPlanRepository(),
        idempotency_repository=InMemoryIdempotencyRepository(),
        audit_repository=InMemoryAuditRepository(),
    )
    req1 = sample_request(event_id="evt-idem-01")
    plan1, is_replay1 = service.create_plan(req1)
    assert not is_replay1

    # Second identical call
    plan2, is_replay2 = service.create_plan(req1)
    assert is_replay2
    assert plan1.plan_id == plan2.plan_id


def test_in_memory_idempotency_different_payload_raises_conflict():
    service = SanitationPlanningService(
        template_repository=InMemoryTemplateRepository(),
        plan_repository=InMemoryPlanRepository(),
        idempotency_repository=InMemoryIdempotencyRepository(),
        audit_repository=InMemoryAuditRepository(),
    )
    req1 = sample_request(event_id="evt-idem-02", estimated_waste_kg=50.0)
    service.create_plan(req1)

    # Same key, changed payload
    req2 = sample_request(event_id="evt-idem-02", estimated_waste_kg=200.0)
    with pytest.raises(IdempotencyConflictError) as exc_info:
        service.create_plan(req2)
    assert exc_info.value.reason_code == "IDEMPOTENCY_KEY_REUSED_WITH_DIFFERENT_INPUT"


# 8. Dispatch Eligibility Invariants
def test_dispatch_eligibility_false_for_preliminary_plan():
    # If waste quantity is missing, status becomes PRELIMINARY_PLAN and dispatch_eligible must be False
    service = SanitationPlanningService(
        template_repository=InMemoryTemplateRepository(),
        plan_repository=InMemoryPlanRepository(),
        idempotency_repository=InMemoryIdempotencyRepository(),
        audit_repository=InMemoryAuditRepository(),
    )
    req = sample_request(event_id="evt-prelim-01", estimated_waste_kg=None)
    plan, _ = service.create_plan(req)
    assert plan.planning_status == PlanningStatus.PRELIMINARY_PLAN
    assert plan.dispatch_eligible is False
    assert "QUANTITY_NOT_MEASURED" in plan.hold_reason_codes


def test_sla_timestamps_preserved():
    service = SanitationPlanningService(
        template_repository=InMemoryTemplateRepository(),
        plan_repository=InMemoryPlanRepository(),
        idempotency_repository=InMemoryIdempotencyRepository(),
        audit_repository=InMemoryAuditRepository(),
    )
    req = sample_request(event_id="evt-sla-01")
    plan, _ = service.create_plan(req)
    assert plan.duration_estimate.sla_resolution_due_at == req.supervisor_decision.sla.resolution_due_at


# 9. Additional Upstream Input Gates
def test_supervisor_evaluation_incomplete_gate():
    req = sample_request()
    req.supervisor_decision.evaluation_status = "PENDING"
    ctx = build_planning_context(req)
    res = resolve_template(ctx)
    assert res.is_held is True
    assert "SUPERVISOR_EVALUATION_INCOMPLETE" in res.hold_reason_codes
    assert res.blocking_status == "BLOCKED"


def test_duplicate_processing_incomplete_gate():
    req = sample_request()
    req.duplicate_result.processing_status = "PENDING"
    ctx = build_planning_context(req)
    res = resolve_template(ctx)
    assert res.is_held is True
    assert "DUPLICATE_PROCESSING_INCOMPLETE" in res.hold_reason_codes
    assert res.blocking_status == "BLOCKED"


def test_duplicate_retrieval_incomplete_gate():
    req = sample_request()
    req.duplicate_result.retrieval.status = "PARTIAL"
    ctx = build_planning_context(req)
    res = resolve_template(ctx)
    assert res.is_held is True
    assert "DUPLICATE_RETRIEVAL_INCOMPLETE" in res.hold_reason_codes
    assert "CANNOT_ASSUME_NEW_INCIDENT" in res.hold_reason_codes
    assert res.blocking_status == "BLOCKED"


def test_routing_unresolved_gate():
    req = sample_request()
    req.supervisor_decision.routing.status = "PENDING"
    ctx = build_planning_context(req)
    res = resolve_template(ctx)
    assert res.is_held is True
    assert "ROUTING_UNRESOLVED" in res.hold_reason_codes
    assert res.blocking_status == "NEEDS_REVIEW"


def test_template_priority_restriction_mismatch():
    custom_template = SanitationTemplate(
        template_id="CUSTOM_RESTRICTED_PRIORITY",
        template_version="1",
        title="Restricted Priority Sanitation",
        objective="Only for CRITICAL incidents",
        allowed_categories=["WASTE_OVERFLOW"],
        allowed_incident_types=["BIN_OVERFLOW"],
        allowed_departments=["SANITATION"],
        allowed_priorities=["CRITICAL"],
        tasks=[
            TaskRule(
                task_code="INSPECT_AREA",
                sequence=1,
                title="Inspect",
                description="Inspect",
                required=True,
            )
        ],
    )
    repo = InMemoryTemplateRepository({("CUSTOM_RESTRICTED_PRIORITY", "1"): custom_template})
    req = sample_request(template_id="CUSTOM_RESTRICTED_PRIORITY")
    req.supervisor_decision.priority = "MEDIUM"
    ctx = build_planning_context(req)
    res = resolve_template(ctx, repository=repo)
    assert res.is_held is True
    assert "TEMPLATE_PRIORITY_MISMATCH" in res.hold_reason_codes


def test_supervisor_required_actions_cross_check():
    req = sample_request()
    req.supervisor_decision.action_plan.required_actions = [
        "INSPECT_AREA",
        "UNAPPROVED_ACTION_NOT_IN_TEMPLATE",
    ]
    ctx = build_planning_context(req)
    res = resolve_template(ctx)
    assert res.is_held is True
    assert "SUPERVISOR_REQUIRED_ACTIONS_NOT_IN_TEMPLATE" in res.hold_reason_codes
    assert res.blocking_status == "NEEDS_REVIEW"


# 10. In-Memory Process Durability Limitations
def test_in_memory_state_lost_on_fresh_repository_instance():
    """Verify that in-memory repositories do not share or persist state across instances (restart simulation)."""
    repo1 = InMemoryPlanRepository()
    req = sample_request()
    service1 = SanitationPlanningService(plan_repository=repo1)
    plan, _ = service1.create_plan(req)
    assert repo1.get_by_id(plan.plan_id) is not None

    # Fresh repository instance (simulating application restart)
    repo2 = InMemoryPlanRepository()
    assert repo2.get_by_id(plan.plan_id) is None
    assert len(repo2.list_all()) == 0


# 11. Concurrency and Thread-Safety Test
def test_concurrent_identical_requests():
    import concurrent.futures

    service = SanitationPlanningService(
        template_repository=InMemoryTemplateRepository(),
        plan_repository=InMemoryPlanRepository(),
        idempotency_repository=InMemoryIdempotencyRepository(),
        audit_repository=InMemoryAuditRepository(),
    )
    req = sample_request(event_id="evt-concurrent-01")

    results = []

    def make_call():
        return service.create_plan(req)

    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(make_call) for _ in range(5)]
        for f in concurrent.futures.as_completed(futures):
            results.append(f.result())

    # All threads must return the identical plan ID
    plan_ids = {r[0].plan_id for r in results}
    assert len(plan_ids) == 1

    # Exactly one call should be original (is_replay=False), all others replays (is_replay=True)
    replays = [r[1] for r in results]
    assert replays.count(False) == 1
    assert replays.count(True) == 4

    # The plan repository must contain exactly one plan
    assert len(service.plan_repo.list_all()) == 1


# 12. Downstream Boundaries Invariants
def test_dispatch_work_package_enforces_module04_boundaries():
    from app.schemas.dispatch_contract import DispatchWorkPackage

    # Worker assignment prohibited by schema type (must be None)
    with pytest.raises(ValidationError) as exc_info:
        DispatchWorkPackage(
            plan_id="SAN-PLAN-1",
            incident_id="INC-1",
            complaint_id="CMP-1",
            assigned_worker_id="WORKER-999",  # VIOLATION
        )
    assert "assigned_worker_id" in str(exc_info.value)

    # Availability confirmed prohibited (must be False)
    with pytest.raises(ValidationError) as exc_info:
        DispatchWorkPackage(
            plan_id="SAN-PLAN-1",
            incident_id="INC-1",
            complaint_id="CMP-1",
            availability_confirmed=True,  # VIOLATION
        )
    assert "availability_confirmed" in str(exc_info.value)

    # Assignment status must be UNASSIGNED
    with pytest.raises(ValidationError) as exc_info:
        DispatchWorkPackage(
            plan_id="SAN-PLAN-1",
            incident_id="INC-1",
            complaint_id="CMP-1",
            assignment_status="ASSIGNED",  # VIOLATION
        )
    assert "assignment_status" in str(exc_info.value)

