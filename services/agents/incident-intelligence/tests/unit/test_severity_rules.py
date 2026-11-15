import pytest

from kavach.schemas.incident_intelligence import Severity
from kavach.services.incident_intelligence.severity_rules import apply_severity_floor, parse_severity


@pytest.mark.parametrize("text,rule", [
    ("There is a fire behind the market", "FIRE"),
    ("Live wire hanging near the bus stop", "ELECTRICAL_HAZARD"),
    ("A child is injured and bleeding", "INJURY"),
    ("I smell a gas leak", "GAS_LEAK"),
    ("Wall collapsed on the footpath", "STRUCTURAL"),
    ("Fear of a stampede at the gate", "CROWD_CRUSH"),
])
def test_danger_keywords_force_high_even_if_model_says_low(text, rule):
    d = apply_severity_floor(text, Severity.LOW, "looked minor")
    assert d.severity == Severity.HIGH and rule in d.matched_rules


def test_routine_complaint_keeps_model_recommendation():
    d = apply_severity_floor("Dustbin overflowing and blocking the path", Severity.MEDIUM, "path blocked")
    assert d.severity == Severity.MEDIUM and d.matched_rules == []


def test_unknown_is_not_silently_downgraded_to_low():
    assert apply_severity_floor("Something is wrong near the gate", Severity.UNKNOWN).severity == Severity.UNKNOWN


def test_never_lowers_high():
    assert apply_severity_floor("dustbin overflowing", Severity.HIGH).severity == Severity.HIGH


def test_word_boundaries_avoid_false_positives():
    assert apply_severity_floor("The campfire-themed cafe sign is crooked", Severity.LOW).matched_rules == []


def test_parse_severity():
    assert parse_severity(" high ") == Severity.HIGH
    assert parse_severity("CRITICAL") is None and parse_severity(None) is None
