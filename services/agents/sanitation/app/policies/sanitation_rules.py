from typing import Any


SANITATION_RULES: dict[str, dict[str, Any]] = {
    "overflowing_dustbin": {
        "category": "Waste Collection",
        "default_tasks": [
            {
                "task_name": "Inspect overflowing dustbin",
                "checklist": [
                    "Assess the amount and type of waste",
                    "Check the surrounding area for scattered waste",
                    "Identify any immediate safety hazards",
                ],
                "required_resources": [
                    "Protective gloves",
                ],
            },
            {
                "task_name": "Collect and contain waste",
                "checklist": [
                    "Use appropriate waste-handling procedures",
                    "Collect scattered waste where safe",
                    "Place waste in the designated collection container",
                ],
                "required_resources": [
                    "Waste collection bags or containers",
                    "Appropriate protective equipment",
                ],
            },
        ],
        "safety_notes": [
            "Avoid direct contact with unknown or hazardous waste.",
            "Use appropriate protective equipment.",
            "Escalate hazardous materials to trained personnel.",
        ],
    },
    "garbage_pile": {
        "category": "Waste Collection",
        "default_tasks": [
            {
                "task_name": "Inspect garbage pile",
                "checklist": [
                    "Assess the size and type of waste",
                    "Check for sharp objects or hazardous materials",
                    "Determine whether special handling is needed",
                ],
                "required_resources": [
                    "Appropriate protective equipment",
                ],
            },
            {
                "task_name": "Plan waste removal",
                "checklist": [
                    "Identify a suitable collection method",
                    "Identify an appropriate disposal destination",
                ],
                "required_resources": [
                    "Suitable waste collection equipment",
                ],
            },
        ],
        "safety_notes": [
            "Do not handle unidentified hazardous materials without trained personnel.",
            "Use suitable protective equipment.",
        ],
    },
    "dirty_public_toilet": {
        "category": "Public Facility Cleaning",
        "default_tasks": [
            {
                "task_name": "Inspect public toilet",
                "checklist": [
                    "Assess cleanliness and visible contamination",
                    "Check water availability",
                    "Identify any blocked drains or damaged fixtures",
                ],
                "required_resources": [
                    "Appropriate protective equipment",
                ],
            },
            {
                "task_name": "Prepare cleaning procedure",
                "checklist": [
                    "Select suitable cleaning products",
                    "Follow product safety instructions",
                    "Plan safe disposal of cleaning waste",
                ],
                "required_resources": [
                    "Approved cleaning supplies",
                    "Suitable cleaning tools",
                ],
            },
        ],
        "safety_notes": [
            "Follow hygiene and contamination-control procedures.",
            "Never mix cleaning chemicals unless explicitly permitted by their instructions.",
            "Restrict access during cleaning when necessary.",
        ],
    },
    "waste_spill": {
        "category": "Spill Response",
        "default_tasks": [
            {
                "task_name": "Assess waste spill",
                "checklist": [
                    "Identify the apparent substance if safe to do so",
                    "Assess immediate risks to people",
                    "Determine whether specialist response is required",
                ],
                "required_resources": [
                    "Appropriate protective equipment",
                ],
            },
            {
                "task_name": "Prepare spill response",
                "checklist": [
                    "Restrict access if needed",
                    "Select a safe handling procedure",
                    "Arrange appropriate waste collection and disposal",
                ],
                "required_resources": [
                    "Suitable spill-response equipment",
                ],
            },
        ],
        "safety_notes": [
            "Keep people away from unidentified or potentially hazardous spills.",
            "Escalate chemical, biological, or otherwise hazardous spills to trained responders.",
        ],
    },
}


def get_sanitation_rule(issue_type: str) -> dict[str, Any] | None:
    """Return a sanitation rule for a known issue type."""
    normalized_type = issue_type.strip().lower()
    return SANITATION_RULES.get(normalized_type)
