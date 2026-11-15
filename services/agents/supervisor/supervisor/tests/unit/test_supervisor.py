# tests/unit/test_supervisor.py
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from kavach.agents.supervisor import SupervisorAgentClient
from kavach.api.routes.supervisor import router as supervisor_router
from kavach.schemas.supervisor import (
    ApprovalStatus,
    DecisionStatus,
    GeminiSupervisorSuggestion,
    PriorityLevel,
    SupervisorIncidentInput,
)
from kavach.services.supervisor.orchestrator import SupervisorOrchestrator

NEW_OK = {"check_id": str(uuid4()), "decision": "NEW", "processing_status": "COMPLETED", "candidates": []}


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(supervisor_router)
    return TestClient(app)


def _payload(**over) -> dict:
    base = {
        "incident_id": str(uuid4()),
        "description": "Overflowing garbage bin near Indrapuri Sector C main road",
        "category": "SANITATION",
        "incident_type": "WASTE_OVERFLOW",
        "severity": "HIGH",
        "reported_at": datetime(2026, 10, 28, 6, 30, tzinfo=timezone.utc).isoformat(),
        "location_metadata": {
            "latitude": 23.2599, "longitude": 77.4650,
            "locality": "Indrapuri Sector C, Bhopal", "verification_status": "VERIFIED",
        },
    }
    base.update(over)
    return base


def _orch(agent=None) -> SupervisorOrchestrator:
    return SupervisorOrchestrator(agent or SupervisorAgentClient())


def _inc(**over) -> SupervisorIncidentInput:
    return SupervisorIncidentInput.model_validate(_payload(**over))


class _MustNotCall(SupervisorAgentClient):
    def evaluate(self, incident):
        raise AssertionError("LLM must not be called when a hard gate fails")


def _assert_blocked(inc, code, agent=None):
    r = _orch(agent or _MustNotCall()).evaluate_incident(inc)
    assert r.supervisor_decision.decision_status == DecisionStatus.NEEDS_REVIEW
    assert r.routing.dispatch_eligible is False
    assert r.supervisor_decision.response_deadline is None
    assert code in r.audit.reason_codes
    return r


# ---------------------------------------------------------------- plain incident report -> decision
def test_plain_incident_report_gives_approved_decision() -> None:
    res = _client().post("/api/v1/supervisor/evaluate", json=_payload())
    assert res.status_code == 200
    body = res.json()
    d = body["supervisor_decision"]
    assert d["department"] == "SANITATION_DEPT"
    assert d["priority"] == "P2"
    assert d["ward_or_route"] == "WARD_02_INDRAPURI"
    assert d["decision_status"] == "APPROVED_TO_PROCEED" and d["approval_status"] == "NOT_REQUIRED"
    reported = datetime(2026, 10, 28, 6, 30, tzinfo=timezone.utc)
    assert datetime.fromisoformat(d["response_deadline"]) == reported + timedelta(hours=4)
    assert datetime.fromisoformat(d["resolution_deadline"]) == reported + timedelta(hours=12)
    assert body["routing"] == {"next_process": "4.0_SANITATION_PLANNING", "dispatch_eligible": True}
    assert body["audit"]["actor"] == "supervisor_agent:mock"
    assert "DUPLICATE_CHECK_NOT_PROVIDED" in body["audit"]["reason_codes"]


def test_p1_gives_pending_approval_output() -> None:
    p = _payload(description="Massive waste spill outside hospital in MP Nagar Zone 1",
                 incident_type="WASTE_SPILL", severity="CRITICAL",
                 location_metadata={"latitude": 23.2315, "longitude": 77.4350,
                                    "locality": "MP Nagar Zone 1, Bhopal", "verification_status": "VERIFIED"})
    b = _client().post("/api/v1/supervisor/evaluate", json=p).json()
    d = b["supervisor_decision"]
    assert d["priority"] == "P1" and d["decision_status"] == "PENDING_APPROVAL"
    assert d["approval_status"] == "PENDING" and b["routing"]["dispatch_eligible"] is False


def test_nested_agent1_payload_is_accepted() -> None:
    nested = {
        "classification": {"category": "SANITATION", "incident_type": "GARBAGE_PILE"},
        "intake": {"complaint_text": "Garbage pile near Arera Colony market"},
        "severity_assessment": {"final_severity": "MEDIUM"},
        "location": {"latitude": 23.2100, "longitude": 77.4300, "address_text": "Arera Colony"},
    }
    r = _client().post("/api/v1/supervisor/evaluate", json=nested)
    assert r.status_code == 200
    assert r.json()["supervisor_decision"]["ward_or_route"] == "WARD_03_ARERA_COLONY"


# ---------------------------------------------------------------- duplicate handling
def test_duplicate_check_optional_by_default_but_required_when_flag_set(monkeypatch) -> None:
    assert _orch().evaluate_incident(_inc()).supervisor_decision.decision_status == DecisionStatus.APPROVED_TO_PROCEED
    monkeypatch.setenv("KAVACH_REQUIRE_DUPLICATE_CHECK", "true")
    _assert_blocked(_inc(), "DUPLICATE_CHECK_MISSING")


def test_supplied_duplicate_check_is_always_enforced() -> None:
    _assert_blocked(_inc(duplicate_check={**NEW_OK, "decision": "DUPLICATE"}), "DUPLICATE_CONFIRMED_NO_NEW_DISPATCH")
    _assert_blocked(_inc(duplicate_check={**NEW_OK, "decision": "REVIEW_REQUIRED"}), "DUPLICATE_REVIEW_REQUIRED")
    _assert_blocked(_inc(duplicate_check={**NEW_OK, "processing_status": "FAILED"}), "DUPLICATE_CHECK_NOT_COMPLETED")
    dc = {**NEW_OK, "candidates": [{"matched_incident_id": str(uuid4()), "similarity_score": 0.96}]}
    _assert_blocked(_inc(duplicate_check=dc), "DUPLICATE_CONFLICT")


def test_valid_new_duplicate_check_passes_and_links_check_id() -> None:
    r = _orch().evaluate_incident(_inc(duplicate_check=NEW_OK))
    assert r.supervisor_decision.decision_status == DecisionStatus.APPROVED_TO_PROCEED
    assert str(r.supervisor_decision.duplicate_check_id) == NEW_OK["check_id"]
    assert "DUPLICATE_CHECK_NOT_PROVIDED" not in r.audit.reason_codes


# ---------------------------------------------------------------- other gates / validation
def test_location_conflict_blocked() -> None:
    loc = {"latitude": 23.2599, "longitude": 77.4126, "locality": "Indrapuri", "verification_status": "CONFLICT"}
    _assert_blocked(_inc(location_metadata=loc), "LOCATION_VERIFICATION_CONFLICT")


def test_invalid_severity_never_writes_garbage_priority() -> None:
    r = _assert_blocked(_inc(severity="URGENT"), "UNRECOGNIZED_PRIORITY_OR_SEVERITY")
    d = r.supervisor_decision
    assert d.priority == PriorityLevel.P2 and d.department is None and d.ward_or_route is None
    assert "PRIORITY_DEFAULTED_FOR_REVIEW" in r.audit.reason_codes


def test_hallucinated_department_or_ward_forces_review_with_null_fields() -> None:
    class Halluc(SupervisorAgentClient):
        def evaluate(self, incident):
            return GeminiSupervisorSuggestion(department="SPACE_DEPT", ward_or_route="WARD_99_MARS",
                                              suggested_priority=PriorityLevel.P4,
                                              reason_codes=["X"], rationale="Hallucinated values.")
    r = _orch(Halluc()).evaluate_incident(_inc(severity="LOW"))
    d = r.supervisor_decision
    assert d.decision_status == DecisionStatus.NEEDS_REVIEW and d.department is None and d.ward_or_route is None
    assert {"INVALID_DEPARTMENT_FROM_LLM", "INVALID_WARD_FROM_LLM"} <= set(r.audit.reason_codes)


def test_department_without_domain_agent_goes_to_review() -> None:
    r = _orch().evaluate_incident(_inc(category="WATER", incident_type="SEWAGE_OVERFLOW"))
    assert r.supervisor_decision.decision_status == DecisionStatus.NEEDS_REVIEW
    assert "NO_DOMAIN_AGENT_FOR_DEPARTMENT" in r.audit.reason_codes


# ---------------------------------------------------------------- priority rules
def test_gemini_can_raise_priority_and_output_is_pending_approval() -> None:
    r = _orch().evaluate_incident(_inc(severity="LOW", description="Open sewage near the bathing ghat"))
    d = r.supervisor_decision
    assert d.priority == PriorityLevel.P2
    assert d.decision_status == DecisionStatus.PENDING_APPROVAL and d.approval_status == ApprovalStatus.PENDING
    assert {"PRIORITY_ESCALATED_BY_SUPERVISOR", "APPROVAL_RULE_PRIORITY_ESCALATED"} <= set(r.audit.reason_codes)
    assert r.routing.dispatch_eligible is False


def test_gemini_cannot_lower_priority() -> None:
    class Lowball(SupervisorAgentClient):
        def evaluate(self, incident):
            return GeminiSupervisorSuggestion(department="SANITATION_DEPT", ward_or_route="WARD_02_INDRAPURI",
                                              suggested_priority=PriorityLevel.P4, reason_codes=["LOW"],
                                              rationale="Looks minor to me.")
    assert _orch(Lowball()).evaluate_incident(_inc(severity="HIGH")).supervisor_decision.priority == PriorityLevel.P2


# ---------------------------------------------------------------- Gemini mode without network
class _FakeGemini(SupervisorAgentClient):
    def __init__(self, text, key="k"):
        super().__init__(llm_mode="gemini", api_key=key)
        self._text = text

    def _call_gemini(self, prompt):
        assert "<untrusted_citizen_data>" in prompt
        return self._text


GOOD = json.dumps({"department": "SANITATION_DEPT", "ward_or_route": "WARD_02_INDRAPURI",
                   "suggested_priority": "P2", "reason_codes": ["OVERFLOW"], "rationale": "Overflowing bin on main road."})


def test_gemini_mode_parses_valid_json() -> None:
    r = _orch(_FakeGemini(GOOD)).evaluate_incident(_inc())
    assert r.supervisor_decision.decision_status == DecisionStatus.APPROVED_TO_PROCEED
    assert r.audit.actor == "supervisor_agent:gemini"


def test_gemini_mode_malformed_json_goes_to_review() -> None:
    r = _orch(_FakeGemini("not json")).evaluate_incident(_inc())
    assert r.supervisor_decision.decision_status == DecisionStatus.NEEDS_REVIEW
    assert "LLM_EVALUATION_FAILED" in r.audit.reason_codes


def test_gemini_mode_bad_priority_enum_goes_to_review() -> None:
    bad = json.dumps({**json.loads(GOOD), "suggested_priority": "URGENT"})
    assert _orch(_FakeGemini(bad)).evaluate_incident(_inc()).supervisor_decision.decision_status == DecisionStatus.NEEDS_REVIEW


def test_gemini_mode_without_key_goes_to_review_not_crash() -> None:
    r = _orch(SupervisorAgentClient(llm_mode="gemini", api_key=None)).evaluate_incident(_inc())
    assert r.supervisor_decision.decision_status == DecisionStatus.NEEDS_REVIEW
    assert "GEMINI_API_KEY missing" in r.audit.rationale


def test_invalid_llm_mode_raises() -> None:
    with pytest.raises(ValueError):
        SupervisorAgentClient(llm_mode="gemni")


# ---------------------------------------------------------------- Gemini response is visible in the output
def test_output_shows_gemini_response_in_gemini_mode() -> None:
    r = _orch(_FakeGemini(GOOD)).evaluate_incident(_inc())
    llm = r.llm_response
    assert llm.mode == "gemini" and llm.skipped_reason is None and llm.error is None
    assert llm.raw_text == GOOD
    assert llm.parsed_suggestion.department == "SANITATION_DEPT"
    assert llm.parsed_suggestion.suggested_priority == PriorityLevel.P2


def test_output_shows_raw_text_and_error_when_gemini_returns_garbage() -> None:
    r = _orch(_FakeGemini("not json")).evaluate_incident(_inc())
    assert r.llm_response.raw_text == "not json"
    assert r.llm_response.parsed_suggestion is None and r.llm_response.error == "JSONDecodeError"


def test_gemini_priority_visible_even_when_code_overrides_it() -> None:
    lower = json.dumps({**json.loads(GOOD), "suggested_priority": "P4"})
    r = _orch(_FakeGemini(lower)).evaluate_incident(_inc(severity="HIGH"))
    assert r.llm_response.parsed_suggestion.suggested_priority == PriorityLevel.P4
    assert r.supervisor_decision.priority == PriorityLevel.P2  # final priority never lowered


def test_missing_key_is_reported_in_llm_response() -> None:
    r = _orch(SupervisorAgentClient(llm_mode="gemini", api_key=None)).evaluate_incident(_inc())
    assert r.llm_response.called is False and r.llm_response.error == "GEMINI_API_KEY missing"
    assert r.llm_response.raw_text is None


def test_hard_gate_failure_and_mock_mode_are_labelled() -> None:
    blocked = _orch(_MustNotCall()).evaluate_incident(_inc(severity="URGENT"))
    assert blocked.llm_response.called is False and blocked.llm_response.skipped_reason == "HARD_GATE_FAILED"
    mock = _orch().evaluate_incident(_inc())
    assert mock.llm_response.called is False and mock.llm_response.skipped_reason == "MOCK_MODE_NO_API_CALL"
    assert mock.llm_response.parsed_suggestion is not None
