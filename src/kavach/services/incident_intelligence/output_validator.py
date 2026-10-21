"""Validates raw model output: JSON -> schema -> business rules. Never 'fixes' by guessing facts."""
from __future__ import annotations

import json
import re

from pydantic import ValidationError

from kavach.errors import OutputValidationError
from kavach.schemas.incident_intelligence import GeminiIncidentProposal
from kavach.services.incident_intelligence.severity_rules import parse_severity
from kavach.services.incident_intelligence.taxonomy import normalize_taxonomy

DEFAULT_QUESTION = "Could you describe what is happening and exactly where it is?"
_FENCE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.IGNORECASE)


def parse_model_json(text: str) -> dict:
    if not text or not text.strip():
        raise OutputValidationError("Empty model response")
    try:
        data = json.loads(_FENCE.sub("", text.strip()))
    except json.JSONDecodeError as exc:
        raise OutputValidationError("Model response is not valid JSON", [str(exc)]) from exc
    if not isinstance(data, dict):
        raise OutputValidationError("Model response must be a JSON object")
    return data


def validate_proposal(raw_text: str) -> GeminiIncidentProposal:
    data = parse_model_json(raw_text)
    try:
        proposal = GeminiIncidentProposal.model_validate(data)
    except ValidationError as exc:
        problems = [f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors()]
        raise OutputValidationError("Model response failed schema validation", problems) from exc

    severity = parse_severity(proposal.severity_recommendation)
    if severity is None:
        raise OutputValidationError("Invalid severity_recommendation",
                                    [f"severity_recommendation must be LOW|MEDIUM|HIGH|UNKNOWN, got "
                                     f"{proposal.severity_recommendation!r}"])

    tax = normalize_taxonomy(proposal.category, proposal.incident_type)
    missing = list(proposal.missing_information)
    conflicts = list(proposal.conflicting_information)
    if tax.is_uncertain and "CATEGORY_UNCERTAIN" not in missing:
        missing.append("CATEGORY_UNCERTAIN")
    if severity.value == "UNKNOWN" and "SEVERITY_UNDETERMINED" not in missing:
        missing.append("SEVERITY_UNDETERMINED")
    if "CATEGORY_TYPE_MISMATCH" in tax.notes:
        conflicts.append("Model category disagreed with its incident type; incident type was trusted.")

    questions = list(proposal.clarification_questions)
    needs = proposal.needs_clarification or bool(questions) or tax.is_uncertain
    if needs and not questions:
        questions = [DEFAULT_QUESTION]

    return proposal.model_copy(update={
        "category": tax.category.value,
        "incident_type": tax.incident_type.value,
        "severity_recommendation": severity.value,
        "missing_information": missing,
        "conflicting_information": conflicts,
        "needs_clarification": needs,
        "clarification_questions": questions,
    })
