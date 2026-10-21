import json
import re
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from app.ai.gemini_client import generate_text
from app.schemas.sanitation import SanitationPlan, SanitationRequest
from app.services.sanitation_plan_builder import build_sanitation_plan
from app.services.resource_estimator import estimate_resources
from app.services.time_estimator import estimate_duration
from app.validators.sanitation_safety import validate_sanitation_safety


SUPPORTED_ISSUE_TYPES = {
    "overflowing_dustbin",
    "garbage_pile",
    "dirty_public_toilet",
    "waste_spill",
}


class SanitationState(TypedDict, total=False):
    request: dict
    issue_type: str | None
    classification_reason: str
    plan: dict


def identify_issue_type_with_gemini(
    description: str,
) -> tuple[str | None, str]:
    """Classify a sanitation complaint using Gemini."""

    prompt = f"""
You classify sanitation complaints for the KAVACH system.

Return ONLY one valid JSON object, without Markdown fences.

Allowed issue_type values:
- overflowing_dustbin
- garbage_pile
- dirty_public_toilet
- waste_spill
- null for unsupported, unclear, or no actual problem

Do not invent facts. If the complaint describes something already
fixed or explicitly says there is no problem, return null.

Required format:
{{
  "issue_type": "overflowing_dustbin",
  "reason": "The complaint describes an overflowing dustbin."
}}

Complaint:
{description}
"""

    response_text = generate_text(prompt).strip()
    response_text = re.sub(
        r"^```(?:json)?\s*|\s*```$",
        "",
        response_text,
        flags=re.IGNORECASE,
    ).strip()

    try:
        result = json.loads(response_text)
    except json.JSONDecodeError as exc:
        raise ValueError(
            "Gemini returned invalid JSON for complaint classification."
        ) from exc

    if not isinstance(result, dict):
        raise ValueError("Gemini classification must be a JSON object.")

    issue_type = result.get("issue_type")
    reason = result.get("reason")

    if issue_type is not None and issue_type not in SUPPORTED_ISSUE_TYPES:
        raise ValueError("Gemini returned an unsupported issue type.")

    if not isinstance(reason, str) or not reason.strip():
        raise ValueError("Gemini did not provide a classification reason.")

    return issue_type, reason.strip()


def analyze_complaint(state: SanitationState) -> dict:
    """Classify with Gemini and build a policy-based proposed plan."""

    request = SanitationRequest.model_validate(state["request"])

    issue_type, classification_reason = identify_issue_type_with_gemini(
        request.description
    )

    plan = build_sanitation_plan(
        request=request,
        issue_type=issue_type,
    )

    plan.resource_estimate = estimate_resources(plan.tasks)
    plan.duration_estimate = estimate_duration(
        quantity=request.estimated_waste_kg,
        productivity_per_hour=None,
    )

    return {
        "issue_type": issue_type,
        "classification_reason": classification_reason,
        "plan": plan.model_dump(mode="json"),
    }


def validate_plan(state: SanitationState) -> dict:
    """Validate the proposed plan and reject unsafe operational claims."""

    plan = SanitationPlan.model_validate(state["plan"])

    if plan.complaint_id != state["request"]["complaint_id"]:
        raise ValueError("Plan complaint ID does not match the request.")

    plan = validate_sanitation_safety(plan)
    plan.requires_human_review = True

    return {"plan": plan.model_dump(mode="json")}


def build_sanitation_graph():
    graph = StateGraph(SanitationState)

    graph.add_node("analyze_complaint", analyze_complaint)
    graph.add_node("validate_plan", validate_plan)

    graph.add_edge(START, "analyze_complaint")
    graph.add_edge("analyze_complaint", "validate_plan")
    graph.add_edge("validate_plan", END)

    return graph.compile()


sanitation_graph = build_sanitation_graph()
