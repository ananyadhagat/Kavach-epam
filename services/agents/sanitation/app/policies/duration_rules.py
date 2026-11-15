from typing import Any
from app.schemas.sanitation_task import DurationEstimateStatus, TaskDuration

DURATION_POLICY_VERSION = "duration-policy-1"

# Productivity rules per task_code:
# setup_minutes, productivity_per_hour, quantity_unit
PRODUCTIVITY_RULES: dict[str, dict[str, Any]] = {
    "REMOVE_WASTE": {
        "setup_minutes": 10.0,
        "productivity_per_hour": 150.0,  # kg per hour
        "unit": "KG",
    },
    "CLEAN_AREA": {
        "setup_minutes": 15.0,
        "productivity_per_hour": 50.0,  # sqm per hour
        "unit": "SQM",
    },
    "DISINFECT_AREA": {
        "setup_minutes": 10.0,
        "productivity_per_hour": 80.0,  # sqm per hour
        "unit": "SQM",
    },
    "CLEAN_FIXTURES": {
        "setup_minutes": 10.0,
        "productivity_per_hour": 5.0,   # fixtures per hour
        "unit": "FIXTURES",
    },
    "ABSORB_SPILL": {
        "setup_minutes": 15.0,
        "productivity_per_hour": 30.0,  # sqm per hour
        "unit": "SQM",
    },
}

# Fixed duration task rules (e.g. inspection, cordon, clear path)
FIXED_TASK_RULES: dict[str, dict[str, Any]] = {
    "INSPECT_AREA": {"fixed_minutes": 15.0, "basis": "STANDARD_INSPECTION_DURATION"},
    "CHECK_PATH_CLEAR": {"fixed_minutes": 10.0, "basis": "STANDARD_ACCESS_CHECK_DURATION"},
    "RESTRICT_ACCESS": {"fixed_minutes": 10.0, "basis": "STANDARD_BARRICADE_SETUP_DURATION"},
    "RESTORE_ACCESS": {"fixed_minutes": 10.0, "basis": "STANDARD_ACCESS_REOPEN_DURATION"},
    "CORDON_AREA": {"fixed_minutes": 15.0, "basis": "STANDARD_CORDON_SETUP_DURATION"},
    "CLEAR_AREA": {"fixed_minutes": 10.0, "basis": "STANDARD_CLEARANCE_CHECK_DURATION"},
}


def calculate_task_duration(
    task_code: str,
    estimated_waste_kg: float | None = None,
    affected_area_sqm: float | None = None,
) -> TaskDuration:
    """Calculate deterministic task duration from approved productivity and setup rules."""
    # Check fixed duration rules
    if task_code in FIXED_TASK_RULES:
        rule = FIXED_TASK_RULES[task_code]
        return TaskDuration(
            minutes=rule["fixed_minutes"],
            status=DurationEstimateStatus.CALCULATED,
            basis=[rule["basis"]],
        )

    # Check productivity formula rules
    if task_code in PRODUCTIVITY_RULES:
        rule = PRODUCTIVITY_RULES[task_code]
        setup = rule["setup_minutes"]
        prod_rate = rule["productivity_per_hour"]
        unit = rule["unit"]

        quantity: float | None = None
        qty_basis: str = ""

        if unit == "KG":
            quantity = estimated_waste_kg
            qty_basis = "WASTE_QUANTITY_NOT_MEASURED"
        elif unit == "SQM":
            quantity = affected_area_sqm
            qty_basis = "AFFECTED_AREA_NOT_MEASURED"

        if quantity is not None and quantity > 0:
            calc_minutes = round(setup + (quantity / prod_rate) * 60.0, 1)
            return TaskDuration(
                minutes=calc_minutes,
                status=DurationEstimateStatus.CALCULATED,
                basis=[
                    f"FORMULA_SETUP_{setup}M_PLUS_QTY_{quantity}{unit}_AT_{prod_rate}_PER_HOUR"
                ],
            )
        else:
            return TaskDuration(
                minutes=None,
                status=DurationEstimateStatus.NEEDS_MORE_DATA,
                basis=[qty_basis or "QUANTITY_NOT_MEASURED", "PRODUCTIVITY_RULE_CONFIGURED"],
            )

    return TaskDuration(
        minutes=None,
        status=DurationEstimateStatus.NEEDS_MORE_DATA,
        basis=["NO_VALIDATED_PRODUCTIVITY_RULE"],
    )
