import sys
import pytest
from app.services.sanitation_planning_service import planning_service
from tests.unit.test_module04_unit import sample_request


def test_no_llm_guard_ensures_zero_generative_ai_in_normal_planning_path():
    """Verify that planning executes deterministically without importing or calling any LLM / LangGraph."""
    # Ensure prohibited packages are not actively imported or invoked in normal path
    prohibited_modules = [
        "google.genai",
        "google.generativeai",
        "langchain",
        "langgraph",
    ]

    # Run the planning pipeline on a valid request
    req = sample_request()
    plan, is_replay = planning_service.create_plan(req)

    assert plan is not None
    assert plan.plan_id.startswith("SAN-PLAN-")
    assert plan.planning_status.value in ("PLAN_READY", "PRELIMINARY_PLAN")
    assert len(plan.tasks) > 0

    # Verify none of the prohibited modules are in sys.modules as a result of planning
    for mod in prohibited_modules:
        assert mod not in sys.modules, f"Prohibited AI module '{mod}' was imported into runtime!"


def test_issue_classifier_deprecated_runtime_error():
    """Verify legacy issue classifier actively blocks generative attempts with RuntimeError."""
    from app.services.issue_classifier import identify_issue_type_with_gemini

    with pytest.raises(RuntimeError, match="LLM classification is forbidden"):
        identify_issue_type_with_gemini("Garbage overflowing")

