from datetime import datetime, timezone
import pytest
from pydantic import ValidationError

from app.schemas.duplicate_contract import DuplicateDecision, DuplicateResult
from app.schemas.incident_contract import IncidentRecord, LocationData
from app.schemas.sanitation_request import SanitationPlanRequest
from app.schemas.sanitation_response import (
    DurationEstimate,
    DurationStatus,
    EstimateStatus,
    PlanningStatus,
    ResourceEstimate,
    SanitationPlanResult,
    TemplateReference,
)
from app.schemas.sanitation_task import (
    DurationEstimateStatus,
    SanitationTask,
    SanitationTaskStatus,
    TaskDuration,
    TaskResourceDemand,
)
from app.schemas.supervisor_contract import (
    ActionPlan,
    RoutingInfo,
    SLAInfo,
    SupervisorDecision,
    SupervisorDecisionStatus,
)


def get_master_plan_sample_request_dict():
    """Exact JSON payload structure from Section 4.1 (Pages 5-6) of Master Plan."""
    return {
        "contract_version": "1.0.0",
        "event_id": "evt-sanitation-plan-request-001",
        "incident": {
            "incident_id": "INC-2026-000123",
            "complaint_id": "CMP-2026-000123",
            "incident_summary": "Waste overflowing near the main gate",
            "complaint_text": "There is garbage overflowing from the bin near the main gate.",
            "category": "WASTE_OVERFLOW",
            "incident_type": "BIN_OVERFLOW",
            "reported_at": "2026-10-21T11:55:00+05:30",
            "location": {
                "latitude": 23.2599,
                "longitude": 77.4126,
                "facility_id": "SITE-01",
                "location_id": "MAIN_GATE",
                "source": "USER_SELECTED_PIN",
                "accuracy_m": None,
            },
            "media": [
                {
                    "media_id": "MEDIA-123",
                    "media_type": "image",
                    "sha256": None,
                    "storage_ref": "private://authorized-reference",
                }
            ],
            "location_evidence_summary": {
                "status": "INCONCLUSIVE",
                "reason_codes": ["EXIF_GPS_MISSING"],
            },
            "quality": {
                "missing_information": [],
                "conflicting_information": [],
                "needs_clarification": False,
            },
        },
        "duplicate_result": {
            "processing_status": "COMPLETED",
            "decision": "NEW",
            "matched_incident_id": None,
            "retrieval": {
                "status": "COMPLETE",
            },
            "policy_version": "duplicate-policy-1",
        },
        "supervisor_decision": {
            "decision_id": "SUP-DEC-2026-000123",
            "evaluation_status": "COMPLETED",
            "decision_status": "APPROVED_TO_PROCEED",
            "department": "SANITATION",
            "priority": "MEDIUM",
            "duplicate_decision": "NEW",
            "linked_incident_id": None,
            "routing": {
                "status": "RESOLVED",
                "facility_id": "SITE-01",
                "location_id": "MAIN_GATE",
                "ward_id": "WARD-07",
                "queue_id": "SANITATION-WARD-07",
            },
            "sla": {
                "status": "CALCULATED",
                "policy_version": "sla-policy-1",
                "rule_id": "SANITATION_MEDIUM",
                "started_at": "2026-10-21T11:55:00+05:30",
                "response_due_at": "2026-10-21T13:55:00+05:30",
                "resolution_due_at": "2026-10-21T19:55:00+05:30",
            },
            "action_plan": {
                "template_id": "BIN_OVERFLOW_RESPONSE",
                "template_version": "1",
                "objective": "Resolve the bin overflow issue",
                "required_actions": [
                    "INSPECT_AREA",
                    "REMOVE_WASTE",
                    "CLEAN_AREA",
                    "CHECK_PATH_CLEAR",
                ],
                "constraints": [
                    "Escalate if a new safety hazard is found",
                ],
            },
            "approval": {
                "required": False,
                "status": "NOT_REQUIRED",
            },
            "policy_versions": {
                "department": "department-policy-1",
                "priority": "priority-policy-1",
                "approval": "approval-policy-1",
                "action_plan": "action-plan-policy-1",
            },
        },
    }


def test_master_plan_sample_request_parses_cleanly():
    payload = get_master_plan_sample_request_dict()
    request = SanitationPlanRequest.model_validate(payload)

    assert request.contract_version == "1.0.0"
    assert request.event_id == "evt-sanitation-plan-request-001"
    assert request.incident.incident_id == "INC-2026-000123"
    assert request.duplicate_result.decision == DuplicateDecision.NEW
    assert request.supervisor_decision.decision_status == SupervisorDecisionStatus.APPROVED_TO_PROCEED
    assert request.supervisor_decision.routing.queue_id == "SANITATION-WARD-07"


def test_unsupported_contract_version_rejected():
    payload = get_master_plan_sample_request_dict()
    payload["contract_version"] = "2.0.0"

    with pytest.raises(ValidationError):
        SanitationPlanRequest.model_validate(payload)


def test_extra_top_level_fields_forbidden():
    payload = get_master_plan_sample_request_dict()
    payload["unauthorized_injected_field"] = "bad_actor"

    with pytest.raises(ValidationError):
        SanitationPlanRequest.model_validate(payload)


def test_naive_timestamp_rejected():
    payload = get_master_plan_sample_request_dict()
    payload["incident"]["reported_at"] = "2026-10-21T11:55:00"  # No timezone offset

    with pytest.raises(ValidationError, match="timezone"):
        SanitationPlanRequest.model_validate(payload)


def test_response_contract_serialization_and_deserialization():
    now = datetime(2026, 10, 22, 15, 30, 0, tzinfo=timezone.utc)
    plan = SanitationPlanResult(
        contract_version="1.0.0",
        plan_id="SAN-PLAN-2026-000123",
        event_id="evt-sanitation-plan-request-001",
        incident_id="INC-2026-000123",
        complaint_id="CMP-2026-000123",
        supervisor_decision_id="SUP-DEC-2026-000123",
        planning_status=PlanningStatus.PRELIMINARY_PLAN,
        dispatch_eligible=False,
        hold_reason_codes=["QUANTITY_NOT_MEASURED"],
        department="SANITATION",
        priority="MEDIUM",
        routing=RoutingInfo(status="RESOLVED", facility_id="SITE-01"),
        template=TemplateReference(
            template_id="BIN_OVERFLOW_RESPONSE",
            template_version="1",
        ),
        objective="Prepare to clean overflowing bin",
        tasks=[
            SanitationTask(
                task_id="SAN-T001",
                sequence=1,
                task_code="INSPECT_AREA",
                title="Inspect bin area",
                description="Visual inspection",
                depends_on=[],
                estimated_duration=TaskDuration(
                    minutes=15.0,
                    status=DurationEstimateStatus.CALCULATED,
                    basis=["STANDARD_INSPECTION_DURATION"],
                ),
                required_resources=[
                    TaskResourceDemand(
                        resource_code="PPE_GENERAL",
                        quantity=1,
                        unit="SET",
                        basis="TEMPLATE_MINIMUM",
                    )
                ],
                completion_criteria=["Inspection recorded"],
                status=SanitationTaskStatus.NOT_STARTED,
            )
        ],
        resource_estimate=ResourceEstimate(
            status=EstimateStatus.PARTIAL,
            required_resources=["PPE_GENERAL"],
            availability_confirmed=False,
        ),
        duration_estimate=DurationEstimate(
            status=DurationStatus.NEEDS_MORE_DATA,
            total_minutes=None,
            method="DEPENDENCY_CRITICAL_PATH",
            basis=["QUANTITY_NOT_MEASURED"],
        ),
        safety_constraints=["Use PPE"],
        assumptions=["Waste not measured"],
        reason_codes=["TEMPLATE_RESOLVED"],
        policy_versions={"template": "sanitation-template-policy-1"},
        created_at=now,
    )

    data = plan.model_dump()
    reconstituted = SanitationPlanResult.model_validate(data)
    assert reconstituted.plan_id == "SAN-PLAN-2026-000123"
    assert reconstituted.dispatch_eligible is False
    assert reconstituted.resource_estimate.availability_confirmed is False
    assert reconstituted.tasks[0].status == SanitationTaskStatus.NOT_STARTED


def test_synthetic_fixtures_ingestion_and_schema_validation():
    """Verify that all locally authored synthetic fixtures pass schema validation."""
    import json
    from pathlib import Path

    fixtures_dir = Path("docs/contracts/fixtures")
    m01_path = fixtures_dir / "module01" / "synthetic_incident_record.json"
    m02_path = fixtures_dir / "module02" / "synthetic_duplicate_result.json"
    m03_path = fixtures_dir / "module03" / "synthetic_supervisor_decision.json"
    m05_path = fixtures_dir / "module05" / "synthetic_dispatch_work_package.json"

    assert m01_path.exists()
    assert m02_path.exists()
    assert m03_path.exists()
    assert m05_path.exists()

    with open(m01_path, "r", encoding="utf-8") as f:
        m01_data = json.load(f)
    with open(m02_path, "r", encoding="utf-8") as f:
        m02_data = json.load(f)
    with open(m03_path, "r", encoding="utf-8") as f:
        m03_data = json.load(f)
    with open(m05_path, "r", encoding="utf-8") as f:
        m05_data = json.load(f)

    # Validate individual contract models
    incident = IncidentRecord.model_validate(m01_data)
    duplicate = DuplicateResult.model_validate(m02_data)
    supervisor = SupervisorDecision.model_validate(m03_data)

    assert incident.incident_id == "INC-2026-000123"
    assert duplicate.decision == DuplicateDecision.NEW
    assert supervisor.decision_status == SupervisorDecisionStatus.APPROVED_TO_PROCEED

    # Assemble into full SanitationPlanRequest
    req = SanitationPlanRequest(
        contract_version="1.0.0",
        event_id="evt-synthetic-fixture-test",
        incident=incident,
        duplicate_result=duplicate,
        supervisor_decision=supervisor,
    )
    assert req.incident.incident_id == "INC-2026-000123"

    # Validate DispatchWorkPackage
    from app.schemas.dispatch_contract import DispatchWorkPackage
    work_pkg = DispatchWorkPackage.model_validate(m05_data)
    assert work_pkg.assigned_worker_id is None
    assert work_pkg.availability_confirmed is False
    assert work_pkg.assignment_status == "UNASSIGNED"


def test_missing_required_incident_id_rejected():
    payload = get_master_plan_sample_request_dict()
    del payload["incident"]["incident_id"]
    with pytest.raises(ValidationError):
        SanitationPlanRequest.model_validate(payload)


def test_unknown_supervisor_decision_status_rejected():
    payload = get_master_plan_sample_request_dict()
    payload["supervisor_decision"]["decision_status"] = "INVALID_NON_EXISTENT_STATUS"
    with pytest.raises(ValidationError):
        SanitationPlanRequest.model_validate(payload)


def test_unknown_duplicate_decision_rejected():
    payload = get_master_plan_sample_request_dict()
    payload["duplicate_result"]["decision"] = "DEFINITELY_UNKNOWN_DUPLICATE_DECISION"
    with pytest.raises(ValidationError):
        SanitationPlanRequest.model_validate(payload)


def test_incompatible_template_version_held_for_review():
    from app.services.context_builder import build_planning_context
    from app.services.template_resolver import resolve_template

    payload = get_master_plan_sample_request_dict()
    payload["supervisor_decision"]["action_plan"]["template_version"] = "999"
    req = SanitationPlanRequest.model_validate(payload)
    ctx = build_planning_context(req)
    res = resolve_template(ctx)
    assert res.is_held is True
    assert "TEMPLATE_NOT_FOUND_OR_DISABLED" in res.hold_reason_codes
    assert res.blocking_status == "NEEDS_REVIEW"


def test_conflicting_duplicate_decisions_handled_safely():
    """If Module 02 says DUPLICATE while Module 03 says NEW, the duplicate gate halts execution."""
    from app.services.context_builder import build_planning_context
    from app.services.template_resolver import resolve_template

    payload = get_master_plan_sample_request_dict()
    payload["duplicate_result"]["decision"] = "DUPLICATE"
    payload["supervisor_decision"]["duplicate_decision"] = "NEW"
    req = SanitationPlanRequest.model_validate(payload)
    ctx = build_planning_context(req)
    res = resolve_template(ctx)
    assert res.is_held is True
    assert "DUPLICATE_OF_EXISTING_INCIDENT" in res.hold_reason_codes
    assert res.blocking_status == "BLOCKED"


def test_exact_id_and_sla_propagation():
    """Verify that incident_id, complaint_id, supervisor_decision_id, and SLA timestamps propagate verbatim."""
    from app.services.sanitation_planning_service import planning_service

    payload = get_master_plan_sample_request_dict()
    req = SanitationPlanRequest.model_validate(payload)
    plan, _ = planning_service.create_plan(req)

    assert plan.incident_id == payload["incident"]["incident_id"]
    assert plan.complaint_id == payload["incident"]["complaint_id"]
    assert plan.supervisor_decision_id == payload["supervisor_decision"]["decision_id"]
    assert plan.event_id == payload["event_id"]
    assert plan.routing.facility_id == payload["supervisor_decision"]["routing"]["facility_id"]
    assert plan.routing.location_id == payload["supervisor_decision"]["routing"]["location_id"]
    assert plan.duration_estimate.sla_response_due_at is not None
    assert plan.duration_estimate.sla_resolution_due_at is not None

