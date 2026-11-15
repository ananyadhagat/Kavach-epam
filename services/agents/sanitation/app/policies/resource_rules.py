import math
from typing import Any
from app.schemas.sanitation_task import TaskResourceDemand
from app.schemas.sanitation_response import EstimateStatus, WorkerDemand, ResourceEstimate


RESOURCE_POLICY_VERSION = "resource-policy-1"

# Known Resource Catalog
RESOURCE_METADATA = {
    "PPE_GENERAL": {"unit": "SET", "fixed_quantity": 1, "basis": "TEMPLATE_MINIMUM"},
    "INSPECTION_TOOLS": {"unit": "SET", "fixed_quantity": 1, "basis": "TEMPLATE_MINIMUM"},
    "WASTE_CONTAINERS": {"unit": "AS_REQUIRED", "capacity_kg": 25.0, "basis": "QUANTITY_DEPENDENT"},
    "CLEANING_TOOLS": {"unit": "SET", "fixed_quantity": 1, "basis": "TEMPLATE_MINIMUM"},
    "CAUTION_SIGNS": {"unit": "SET", "fixed_quantity": 1, "basis": "TEMPLATE_MINIMUM"},
    "DISINFECTANT_SUPPLIES": {"unit": "KG", "basis": "QUANTITY_DEPENDENT"},
    "SHOVEL_TOOLS": {"unit": "SET", "fixed_quantity": 1, "basis": "TEMPLATE_MINIMUM"},
    "ABSORBENT_MATERIAL": {"unit": "KG", "basis": "QUANTITY_DEPENDENT"},
}


def calculate_task_resource_demand(
    resource_code: str,
    task_code: str,
    estimated_waste_kg: float | None = None,
    affected_area_sqm: float | None = None,
) -> TaskResourceDemand:
    """Calculate demand for a single resource code under approved policy rules."""
    meta = RESOURCE_METADATA.get(resource_code, {"unit": "UNIT", "fixed_quantity": None, "basis": "TEMPLATE_MINIMUM"})
    unit = meta.get("unit")
    basis = meta.get("basis", "REQUIRED_BY_TEMPLATE")
    fixed_qty = meta.get("fixed_quantity")

    if fixed_qty is not None:
        return TaskResourceDemand(
            resource_code=resource_code,
            quantity=fixed_qty,
            unit=unit,
            basis=basis,
        )

    # Dynamic quantity evaluation
    if resource_code == "WASTE_CONTAINERS":
        if estimated_waste_kg is not None and estimated_waste_kg > 0:
            capacity = meta.get("capacity_kg", 25.0)
            qty = math.ceil(estimated_waste_kg / capacity)
            return TaskResourceDemand(
                resource_code=resource_code,
                quantity=max(1, qty),
                unit="BAG",
                basis=f"CALCULATED_FROM_ESTIMATED_WASTE_KG_{estimated_waste_kg}",
            )
        else:
            return TaskResourceDemand(
                resource_code=resource_code,
                quantity=None,
                unit=unit,
                basis="QUANTITY_DEPENDENT",
            )

    if resource_code in ("DISINFECTANT_SUPPLIES", "ABSORBENT_MATERIAL"):
        if affected_area_sqm is not None and affected_area_sqm > 0:
            qty = round(affected_area_sqm * 0.2, 2)
            return TaskResourceDemand(
                resource_code=resource_code,
                quantity=max(1.0, qty),
                unit=unit,
                basis=f"CALCULATED_FROM_AFFECTED_AREA_SQM_{affected_area_sqm}",
            )
        else:
            return TaskResourceDemand(
                resource_code=resource_code,
                quantity=None,
                unit=unit,
                basis="QUANTITY_DEPENDENT",
            )

    return TaskResourceDemand(
        resource_code=resource_code,
        quantity=None,
        unit=unit,
        basis=basis,
    )


def compute_worker_demand(priority: str, task_count: int) -> WorkerDemand:
    """Determine estimated crew demand based on priority and operational rules."""
    norm_priority = priority.upper()
    if norm_priority in ("HIGH", "CRITICAL"):
        return WorkerDemand(
            count=2,
            roles=["LEAD_SANITATION_WORKER", "SANITATION_OPERATIVE"],
            basis=f"PRIORITY_{norm_priority}_CREW_RULE",
        )
    elif norm_priority == "MEDIUM":
        return WorkerDemand(
            count=1,
            roles=["SANITATION_OPERATIVE"],
            basis="PRIORITY_MEDIUM_CREW_RULE",
        )
    elif norm_priority == "LOW":
        return WorkerDemand(
            count=1,
            roles=["SANITATION_OPERATIVE"],
            basis="PRIORITY_LOW_CREW_RULE",
        )
    return WorkerDemand(
        count=None,
        roles=[],
        basis="CREW_RULE_NOT_CONFIGURED",
    )
