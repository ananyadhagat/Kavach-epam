import json

import pytest

from conftest import good_json
from kavach.errors import OutputValidationError
from kavach.services.incident_intelligence.output_validator import (
    DEFAULT_QUESTION, parse_model_json, validate_proposal,
)


def test_valid_response_passes_unchanged():
    p = validate_proposal(good_json())
    assert (p.category, p.incident_type, p.severity_recommendation) == ("SANITATION", "WASTE_OVERFLOW", "MEDIUM")
    assert not p.needs_clarification and p.missing_information == []


def test_markdown_fenced_json_is_accepted():
    assert validate_proposal(f"```json\n{good_json()}\n```").category == "SANITATION"


@pytest.mark.parametrize("raw", ["", "   ", "not json", "[1,2,3]", '{"incident_summary": '])
def test_non_json_or_non_object_rejected(raw):
    with pytest.raises(OutputValidationError):
        parse_model_json(raw)


def test_missing_required_field_reports_problem():
    data = json.loads(good_json()); del data["incident_summary"]
    with pytest.raises(OutputValidationError) as e:
        validate_proposal(json.dumps(data))
    assert any("incident_summary" in p for p in e.value.problems)


def test_wrong_types_rejected():
    with pytest.raises(OutputValidationError):
        validate_proposal(good_json(extracted_facts="a string"))


def test_overlong_summary_rejected():
    with pytest.raises(OutputValidationError):
        validate_proposal(good_json(incident_summary="x" * 601))


def test_invalid_severity_rejected_for_repair():
    with pytest.raises(OutputValidationError):
        validate_proposal(good_json(severity_recommendation="CRITICAL"))


def test_unknown_category_becomes_other_unknown_and_flags_uncertainty():
    p = validate_proposal(good_json(category="PIZZA", incident_type="CALZONE"))
    assert (p.category, p.incident_type) == ("OTHER", "UNKNOWN")
    assert "CATEGORY_UNCERTAIN" in p.missing_information
    assert p.needs_clarification and p.clarification_questions == [DEFAULT_QUESTION]


def test_unknown_severity_flagged_not_guessed():
    p = validate_proposal(good_json(severity_recommendation="unknown"))
    assert p.severity_recommendation == "UNKNOWN" and "SEVERITY_UNDETERMINED" in p.missing_information


def test_category_type_conflict_trusts_type_and_records_conflict():
    p = validate_proposal(good_json(category="SANITATION", incident_type="BROKEN_PIPE"))
    assert p.category == "WATER_SUPPLY" and p.conflicting_information


def test_questions_imply_needs_clarification():
    p = validate_proposal(good_json(clarification_questions=["Which gate?"]))
    assert p.needs_clarification


def test_extra_fields_ignored():
    assert validate_proposal(good_json(unexpected="x")).category == "SANITATION"
