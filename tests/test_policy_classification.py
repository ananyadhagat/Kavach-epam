from datetime import datetime, timezone
import pytest

from app.policies.template_registry import SAN_TEMPLATES
from app.repositories.template_repository import InMemoryTemplateRepository
from app.schemas.duplicate_contract import DuplicateDecision, DuplicateResult
from app.schemas.incident_contract import IncidentRecord
from app.schemas.sanitation_request import SanitationPlanRequest
from app.schemas.supervisor_contract import (
    ActionPlan,
    RoutingInfo,
    SupervisorDecision,
    SupervisorDecisionStatus,
)
from app.services.context_builder import build_planning_context
from app.services.template_resolver import resolve_template


def make_context(
    category: str = "WASTE_OVERFLOW",
    incident_type: str = "BIN_OVERFLOW",
    template_id: str = "BIN_OVERFLOW_RESPONSE",
    decision_status: SupervisorDecisionStatus = SupervisorDecisionStatus.APPROVED_TO_PROCEED,
    duplicate_decision: DuplicateDecision = DuplicateDecision.NEW,
    department: str = "SANITATION",
):
    now = datetime.now(timezone.utc)
    req = SanitationPlanRequest(
        contract_version="1.0.0",
        event_id="evt-policy-01",
        incident=IncidentRecord(
            incident_id="INC-001",
            complaint_id="CMP-001",
            category=category,
            incident_type=incident_type,
            reported_at=now,
        ),
        duplicate_result=DuplicateResult(
            decision=duplicate_decision,
        ),
        supervisor_decision=SupervisorDecision(
            decision_id="SUP-001",
            decision_status=decision_status,
            department=department,
            routing=RoutingInfo(status="RESOLVED"),
            action_plan=ActionPlan(
                template_id=template_id,
                template_version="1",
            ),
        ),
    )
    return build_planning_context(req)


def test_bin_overflow_resolves_deterministic_template():
    ctx = make_context("WASTE_OVERFLOW", "BIN_OVERFLOW", "BIN_OVERFLOW_RESPONSE")
    res = resolve_template(ctx)
    assert not res.is_held
    assert res.template is not None
    assert res.template.template_id == "BIN_OVERFLOW_RESPONSE"


def test_garbage_pile_resolves_deterministic_template():
    ctx = make_context("WASTE_OVERFLOW", "GARBAGE_PILE", "GARBAGE_PILE_REMOVAL")
    res = resolve_template(ctx)
    assert not res.is_held
    assert res.template is not None
    assert res.template.template_id == "GARBAGE_PILE_REMOVAL"


def test_dirty_public_toilet_resolves_deterministic_template():
    ctx = make_context("FACILITY_CLEANING", "DIRTY_PUBLIC_TOILET", "PUBLIC_TOILET_CLEANING")
    res = resolve_template(ctx)
    assert not res.is_held
    assert res.template is not None
    assert res.template.template_id == "PUBLIC_TOILET_CLEANING"


def test_waste_spill_resolves_deterministic_template():
    ctx = make_context("HAZARD_OR_SPILL", "WASTE_SPILL", "SPILL_RESPONSE")
    res = resolve_template(ctx)
    assert not res.is_held
    assert res.template is not None
    assert res.template.template_id == "SPILL_RESPONSE"


def test_unknown_template_id_returns_needs_review():
    ctx = make_context(template_id="NON_EXISTENT_TEMPLATE")
    res = resolve_template(ctx)
    assert res.is_held
    assert "TEMPLATE_NOT_FOUND_OR_DISABLED" in res.hold_reason_codes


def test_mismatched_category_returns_template_policy_conflict():
    # Category is STREETLIGHTING but template is BIN_OVERFLOW_RESPONSE
    ctx = make_context(category="STREETLIGHTING", incident_type="BIN_OVERFLOW", template_id="BIN_OVERFLOW_RESPONSE")
    res = resolve_template(ctx)
    assert res.is_held
    assert "TEMPLATE_POLICY_CONFLICT" in res.hold_reason_codes
    assert "TEMPLATE_CATEGORY_MISMATCH" in res.hold_reason_codes


def test_mismatched_department_returns_conflict():
    ctx = make_context(department="ELECTRICAL", template_id="BIN_OVERFLOW_RESPONSE")
    res = resolve_template(ctx)
    assert res.is_held
    assert "TEMPLATE_POLICY_CONFLICT" in res.hold_reason_codes
    assert "TEMPLATE_DEPARTMENT_MISMATCH" in res.hold_reason_codes


def test_unapproved_supervisor_holds_template_resolution():
    ctx = make_context(decision_status=SupervisorDecisionStatus.PENDING_APPROVAL)
    res = resolve_template(ctx)
    assert res.is_held
    assert "SUPERVISOR_NOT_APPROVED" in res.hold_reason_codes
