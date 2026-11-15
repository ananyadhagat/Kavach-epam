from typing import Any, Callable
from pydantic import BaseModel, Field


class TaskRule(BaseModel):
    """Rule defining how a task is created from a template."""

    task_code: str
    sequence: int
    title: str
    description: str
    required: bool = True
    depends_on_codes: list[str] = Field(default_factory=list)
    condition_predicate_name: str | None = None
    unknown_behavior: str = "OMIT"  # OMIT, REVIEW, INSPECT
    completion_criteria: list[str] = Field(default_factory=list)
    default_resource_codes: list[str] = Field(default_factory=list)


class SanitationTemplate(BaseModel):
    """Approved sanitation work template."""

    template_id: str
    template_version: str = "1"
    policy_version: str = "sanitation-template-policy-1"
    enabled: bool = True
    title: str
    objective: str
    allowed_categories: list[str]
    allowed_incident_types: list[str]
    allowed_departments: list[str] = ["SANITATION"]
    allowed_priorities: list[str] = ["LOW", "MEDIUM", "HIGH", "CRITICAL"]
    safety_constraints: list[str] = Field(default_factory=list)
    tasks: list[TaskRule] = Field(default_factory=list)


# Approved Sanitation Templates
SAN_TEMPLATES: dict[tuple[str, str], SanitationTemplate] = {
    ("BIN_OVERFLOW_RESPONSE", "1"): SanitationTemplate(
        template_id="BIN_OVERFLOW_RESPONSE",
        template_version="1",
        title="Bin Overflow Cleaning and Area Clearance",
        objective="Prepare to remove overflowing waste and restore safe access around the reported bin.",
        allowed_categories=["WASTE_OVERFLOW"],
        allowed_incident_types=["BIN_OVERFLOW"],
        allowed_departments=["SANITATION"],
        safety_constraints=[
            "Do not handle unknown hazardous materials without trained personnel",
            "Use PPE required by the approved procedure",
            "Escalate newly discovered hazards",
        ],
        tasks=[
            TaskRule(
                task_code="INSPECT_AREA",
                sequence=1,
                title="Inspect the affected bin and surrounding area",
                description="Confirm visible overflow, affected area and any immediate hazards before handling waste.",
                required=True,
                depends_on_codes=[],
                completion_criteria=[
                    "Inspection findings are recorded",
                    "Any hazardous or unknown material is escalated",
                ],
                default_resource_codes=["PPE_GENERAL", "INSPECTION_TOOLS"],
            ),
            TaskRule(
                task_code="REMOVE_WASTE",
                sequence=2,
                title="Collect and contain overflowing waste",
                description="Collect only waste that can be handled safely under the approved sanitation procedure.",
                required=True,
                depends_on_codes=["INSPECT_AREA"],
                completion_criteria=[
                    "Overflowing waste is contained",
                    "Hazardous items are not handled outside authorized procedure",
                ],
                default_resource_codes=["WASTE_CONTAINERS", "PPE_GENERAL"],
            ),
            TaskRule(
                task_code="CLEAN_AREA",
                sequence=3,
                title="Clean the surrounding affected area",
                description="Clean the area using the approved procedure and suitable materials.",
                required=True,
                depends_on_codes=["REMOVE_WASTE"],
                completion_criteria=[
                    "Visible loose waste in the approved work area is removed",
                    "Area is left in a safe condition",
                ],
                default_resource_codes=["CLEANING_TOOLS"],
            ),
            TaskRule(
                task_code="CHECK_PATH_CLEAR",
                sequence=4,
                title="Check public access around the bin",
                description="Check whether the affected path is clear; report any remaining obstruction.",
                required=False,
                condition_predicate_name="check_path_obstruction",
                unknown_behavior="INSPECT",
                depends_on_codes=["CLEAN_AREA"],
                completion_criteria=[
                    "Path status is recorded",
                    "Remaining obstruction is escalated",
                ],
                default_resource_codes=[],
            ),
        ],
    ),
    ("GARBAGE_PILE_REMOVAL", "1"): SanitationTemplate(
        template_id="GARBAGE_PILE_REMOVAL",
        template_version="1",
        title="Open Garbage Pile Clearance",
        objective="Inspect, contain, and clear illegal or open garbage pile accumulation.",
        allowed_categories=["WASTE_OVERFLOW"],
        allowed_incident_types=["GARBAGE_PILE"],
        allowed_departments=["SANITATION"],
        safety_constraints=[
            "Do not handle unidentified hazardous materials without trained personnel",
            "Use heavy-duty puncture-resistant gloves and protective footwear",
            "Secure the perimeter if waste spills into traffic corridors",
        ],
        tasks=[
            TaskRule(
                task_code="INSPECT_AREA",
                sequence=1,
                title="Inspect garbage pile and assess hazards",
                description="Examine the size, composition, sharp objects, and perimeter safety before manual handling.",
                required=True,
                depends_on_codes=[],
                completion_criteria=[
                    "Pile dimensions and hazard assessment recorded",
                    "Perimeter clearance established",
                ],
                default_resource_codes=["PPE_GENERAL", "INSPECTION_TOOLS"],
            ),
            TaskRule(
                task_code="REMOVE_WASTE",
                sequence=2,
                title="Load and contain garbage pile",
                description="Bag or shovel loose waste into designated transport containers.",
                required=True,
                depends_on_codes=["INSPECT_AREA"],
                completion_criteria=[
                    "All accumulated waste collected into containers",
                    "No sharp debris left uncontained",
                ],
                default_resource_codes=["WASTE_CONTAINERS", "SHOVEL_TOOLS"],
            ),
            TaskRule(
                task_code="DISINFECT_AREA",
                sequence=3,
                title="Disinfect and wash the ground site",
                description="Apply approved lime or disinfectant powder to prevent vector breeding and odor.",
                required=True,
                depends_on_codes=["REMOVE_WASTE"],
                completion_criteria=[
                    "Disinfectant applied evenly over the ground",
                    "Area visually clean and odor suppressed",
                ],
                default_resource_codes=["DISINFECTANT_SUPPLIES"],
            ),
        ],
    ),
    ("PUBLIC_TOILET_CLEANING", "1"): SanitationTemplate(
        template_id="PUBLIC_TOILET_CLEANING",
        template_version="1",
        title="Public Toilet Sanitation and Disinfection",
        objective="Deep clean, sanitize fixtures, and restore public toilet hygiene.",
        allowed_categories=["FACILITY_CLEANING"],
        allowed_incident_types=["DIRTY_PUBLIC_TOILET", "TOILET_CLEANING"],
        allowed_departments=["SANITATION"],
        safety_constraints=[
            "Follow strict hygiene and biological contamination-control procedures",
            "Never mix acid-based toilet cleaner with chlorine bleach",
            "Place 'Cleaning in Progress' warning signage and restrict entry",
        ],
        tasks=[
            TaskRule(
                task_code="RESTRICT_ACCESS",
                sequence=1,
                title="Restrict access and place caution signage",
                description="Ensure the facility is unoccupied and place warning barricades.",
                required=True,
                depends_on_codes=[],
                completion_criteria=[
                    "Caution signs posted at all entrances",
                    "Facility secured against public entry during cleaning",
                ],
                default_resource_codes=["CAUTION_SIGNS"],
            ),
            TaskRule(
                task_code="CLEAN_FIXTURES",
                sequence=2,
                title="Sanitize fixtures and wash floors",
                description="Scrub and sanitize toilets, sinks, faucets, and scrub floor surfaces.",
                required=True,
                depends_on_codes=["RESTRICT_ACCESS"],
                completion_criteria=[
                    "All toilet fixtures scrubbed and sanitized",
                    "Floor washed, drained, and dried",
                ],
                default_resource_codes=["DISINFECTANT_SUPPLIES", "CLEANING_TOOLS"],
            ),
            TaskRule(
                task_code="RESTORE_ACCESS",
                sequence=3,
                title="Inspect quality and restore public access",
                description="Ensure surfaces are dry, remove caution signs, and reopen facility.",
                required=True,
                depends_on_codes=["CLEAN_FIXTURES"],
                completion_criteria=[
                    "Inspection checklist verified",
                    "Facility reopened to the public",
                ],
                default_resource_codes=[],
            ),
        ],
    ),
    ("SPILL_RESPONSE", "1"): SanitationTemplate(
        template_id="SPILL_RESPONSE",
        template_version="1",
        title="Waste Spill Containment and Response",
        objective="Contain, absorb, and dispose of hazardous or nuisance waste spills safely.",
        allowed_categories=["HAZARD_OR_SPILL", "WASTE_OVERFLOW"],
        allowed_incident_types=["WASTE_SPILL"],
        allowed_departments=["SANITATION"],
        safety_constraints=[
            "Keep people away from unidentified or potentially chemical spills",
            "Use appropriate chemical-resistant PPE",
            "Escalate immediately if biological, flammable, or toxic liquid is detected",
        ],
        tasks=[
            TaskRule(
                task_code="CORDON_AREA",
                sequence=1,
                title="Cordon off spill zone and assess substance",
                description="Place safety cones and identify spill boundaries without direct contact.",
                required=True,
                depends_on_codes=[],
                completion_criteria=[
                    "Spill perimeter cordoned",
                    "Substance evaluated for hazardous traits",
                ],
                default_resource_codes=["CAUTION_SIGNS", "PPE_GENERAL"],
            ),
            TaskRule(
                task_code="ABSORB_SPILL",
                sequence=2,
                title="Apply absorbent and remove waste residue",
                description="Spread absorbent material over spill, sweep into sealed waste bags.",
                required=True,
                depends_on_codes=["CORDON_AREA"],
                completion_criteria=[
                    "Liquid spill fully absorbed and bagged",
                    "Residue neutralized",
                ],
                default_resource_codes=["ABSORBENT_MATERIAL", "CLEANING_TOOLS"],
            ),
            TaskRule(
                task_code="CLEAR_AREA",
                sequence=3,
                title="Verify surface safety and remove cordoning",
                description="Ensure surface traction is safe and remove barricades.",
                required=True,
                depends_on_codes=["ABSORB_SPILL"],
                completion_criteria=[
                    "No slick residue remaining",
                    "Perimeter signs cleared",
                ],
                default_resource_codes=[],
            ),
        ],
    ),
}
