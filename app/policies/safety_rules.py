import re
from typing import Any

SAFETY_POLICY_VERSION = "sanitation-safety-policy-1"

FORBIDDEN_CLAIMS = [
    r"\bworkers have been assigned\b",
    r"\bworker has been assigned\b",
    r"\bteam has been dispatched\b",
    r"\bcleaning has been completed\b",
    r"\bwork has been completed\b",
    r"\bissue has been resolved\b",
    r"\bcomplaint has been resolved\b",
    r"\balready cleaned\b",
    r"\bwork is complete\b",
]


def check_forbidden_operational_claims(text: str) -> list[str]:
    """Find any forbidden claims asserting that operational work has occurred or workers assigned."""
    violations = []
    text_lower = text.lower()
    for pattern in FORBIDDEN_CLAIMS:
        if re.search(pattern, text_lower):
            violations.append(pattern)
    return violations


def get_default_safety_constraints(
    category: str,
    incident_type: str,
    hazard_detected: bool | None = None,
) -> list[str]:
    """Return standard approved safety constraints for the given category and conditions."""
    constraints = [
        "Do not handle unknown hazardous materials without trained personnel",
        "Use PPE required by the approved procedure",
        "Escalate newly discovered hazards",
    ]

    if hazard_detected is True:
        constraints.append("Specialist hazardous materials response required before manual handling")

    if category == "FACILITY_CLEANING" or "TOILET" in incident_type:
        constraints.append("Never mix acidic toilet cleaning agents with bleach products")
        constraints.append("Ensure proper natural or mechanical ventilation during chemical application")

    if category == "HAZARD_OR_SPILL" or "SPILL" in incident_type:
        constraints.append("Keep the public cordoned away until the substance is identified and neutralized")

    return constraints
