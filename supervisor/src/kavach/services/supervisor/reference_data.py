# src/kavach/services/supervisor/reference_data.py
from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Optional

from kavach.schemas.supervisor import PriorityLevel, SupervisorIncidentInput

CURRENT_POLICY_VERSION = "v1.0.0"
# Used only by the mock LLM when it cannot resolve a value. Never stored in the DB.
UNRESOLVED_DEPARTMENT = "UNRESOLVED_DEPT"
UNRESOLVED_WARD = "UNRESOLVED_WARD"

# Duplicate-check handling (confirm with process 2.0 owners)
DUPLICATE_OK_STATUSES: frozenset[str] = frozenset({"COMPLETED", "SUCCESS", "SUCCEEDED", "DONE"})
DUPLICATE_CONFLICT_THRESHOLD = 0.90  # decision NEW but a candidate scores >= this -> review

# Used when Agent 1's severity cannot be mapped to P1-P4 (conservative, goes to review anyway)
DEFAULT_UNRECOGNIZED_PRIORITY = PriorityLevel.P2


@dataclass(frozen=True)
class DepartmentSpec:
    code: str
    display_name: str
    supported_categories: frozenset[str]
    supported_incident_types: frozenset[str]
    downstream_process: Optional[str]


@dataclass(frozen=True)
class WardSpec:
    code: str
    display_name: str
    keywords: tuple[str, ...]
    lat_min: float
    lat_max: float
    lon_min: float
    lon_max: float


@dataclass(frozen=True)
class SLADeadlineSpec:
    response_delta: timedelta
    resolution_delta: timedelta


DEPARTMENT_ROSTER: dict[str, DepartmentSpec] = {
    "SANITATION_DEPT": DepartmentSpec(
        code="SANITATION_DEPT",
        display_name="Municipal Sanitation & Solid Waste Department",
        supported_categories=frozenset(
            {"SANITATION", "SOLID_WASTE", "WASTE_MANAGEMENT", "HYGIENE", "PUBLIC_HEALTH"}
        ),
        supported_incident_types=frozenset(
            {
                "WASTE_OVERFLOW",
                "OVERFLOWING_DUSTBIN",
                "GARBAGE_PILE",
                "DIRTY_PUBLIC_TOILET",
                "WASTE_SPILL",
                "DEAD_ANIMAL",
                "OPEN_DUMPING",
                "DRAIN_SILTING",
            }
        ),
        downstream_process="4.0_SANITATION_PLANNING",
    ),
    "PUBLIC_WORKS_DEPT": DepartmentSpec(
        code="PUBLIC_WORKS_DEPT",
        display_name="Public Works & Road Maintenance Department",
        supported_categories=frozenset({"ROADS", "INFRASTRUCTURE", "PUBLIC_WORKS"}),
        supported_incident_types=frozenset(
            {"ROAD_DAMAGE", "POTHOLE", "BROKEN_FOOTPATH", "FALLEN_TREE"}
        ),
        downstream_process=None,  # Domain agent not built yet -> routes to 8.0 review per README
    ),
    "WATER_SUPPLY_DEPT": DepartmentSpec(
        code="WATER_SUPPLY_DEPT",
        display_name="Water Supply & Sewage Department",
        supported_categories=frozenset({"WATER", "SEWAGE", "DRAINAGE"}),
        supported_incident_types=frozenset(
            {"WATER_LEAKAGE", "SEWAGE_OVERFLOW", "PIPE_BURST", "WATERLOGGING"}
        ),
        downstream_process=None,
    ),
    "ELECTRICAL_DEPT": DepartmentSpec(
        code="ELECTRICAL_DEPT",
        display_name="Municipal Streetlight & Electrical Department",
        supported_categories=frozenset({"ELECTRICAL", "STREETLIGHT"}),
        supported_incident_types=frozenset(
            {"STREETLIGHT_OUTAGE", "EXPOSED_WIRING", "SPARKING_POLE"}
        ),
        downstream_process=None,
    ),
}

WARD_ROUTE_MAP: dict[str, WardSpec] = {
    "WARD_01_MP_NAGAR": WardSpec(
        code="WARD_01_MP_NAGAR",
        display_name="Ward 01 - MP Nagar Zone I & II",
        keywords=("mp nagar", "maharana pratap nagar", "zone 1", "zone 2", "db mall", "habibganj"),
        lat_min=23.2200,
        lat_max=23.2450,
        lon_min=77.4250,
        lon_max=77.4500,
    ),
    "WARD_02_INDRAPURI": WardSpec(
        code="WARD_02_INDRAPURI",
        display_name="Ward 02 - Indrapuri & BHEL",
        keywords=("indrapuri", "sector a", "sector b", "sector c", "bhel", "piplani", "jk road"),
        lat_min=23.2400,
        lat_max=23.2750,
        lon_min=77.4501,
        lon_max=77.5000,
    ),
    "WARD_03_ARERA_COLONY": WardSpec(
        code="WARD_03_ARERA_COLONY",
        display_name="Ward 03 - Arera Colony (E-1 to E-8)",
        keywords=("arera", "arera colony", "bittan market", "10 number", "shahpura", "gulmohar"),
        lat_min=23.1950,
        lat_max=23.2199,
        lon_min=77.4150,
        lon_max=77.4500,
    ),
    "WARD_04_KOLAR": WardSpec(
        code="WARD_04_KOLAR",
        display_name="Ward 04 - Kolar Road",
        keywords=("kolar", "kolar road", "chuna bhatti", "danish kunj", "bairagarh chichli"),
        lat_min=23.1500,
        lat_max=23.1949,
        lon_min=77.3900,
        lon_max=77.4350,
    ),
    "WARD_05_NEW_MARKET": WardSpec(
        code="WARD_05_NEW_MARKET",
        display_name="Ward 05 - TT Nagar & New Market",
        keywords=("new market", "tt nagar", "roshanpura", "malviya nagar", "shyamla hills"),
        lat_min=23.2250,
        lat_max=23.2550,
        lon_min=77.3800,
        lon_max=77.4249,
    ),
    "WARD_06_AYODHYA_BYPASS": WardSpec(
        code="WARD_06_AYODHYA_BYPASS",
        display_name="Ward 06 - Ayodhya Bypass & Raisen Road",
        keywords=("ayodhya", "ayodhya bypass", "raisen road", "minal", "ashoka garden", "govindpura"),
        lat_min=23.2551,
        lat_max=23.3100,
        lon_min=77.4300,
        lon_max=77.5100,
    ),
}

SLA_POLICY_BY_PRIORITY: dict[PriorityLevel, SLADeadlineSpec] = {
    PriorityLevel.P1: SLADeadlineSpec(
        response_delta=timedelta(hours=1),
        resolution_delta=timedelta(hours=4),
    ),
    PriorityLevel.P2: SLADeadlineSpec(
        response_delta=timedelta(hours=4),
        resolution_delta=timedelta(hours=12),
    ),
    PriorityLevel.P3: SLADeadlineSpec(
        response_delta=timedelta(hours=12),
        resolution_delta=timedelta(hours=24),
    ),
    PriorityLevel.P4: SLADeadlineSpec(
        response_delta=timedelta(hours=24),
        resolution_delta=timedelta(hours=72),
    ),
}

HIGH_RISK_INCIDENT_TYPES: frozenset[str] = frozenset(
    {"WASTE_SPILL", "BIOHAZARD", "CHEMICAL_SPILL", "SEWAGE_OVERFLOW", "EXPOSED_WIRING"}
)


def resolve_department_deterministically(category: str, incident_type: str) -> Optional[str]:
    """Resolves department code from incident category or incident_type."""
    cat_norm = category.strip().upper()
    type_norm = incident_type.strip().upper()

    for dept_code, spec in DEPARTMENT_ROSTER.items():
        if type_norm in spec.supported_incident_types or cat_norm in spec.supported_categories:
            return dept_code
    return None


def resolve_ward_deterministically(
    locality: Optional[str],
    latitude: Optional[float],
    longitude: Optional[float],
    ward_hint: Optional[str] = None,
) -> Optional[str]:
    """Resolves ward code via explicit ward_hint, locality keyword match, or GPS bounding box."""
    if ward_hint:
        hint_norm = ward_hint.strip().upper()
        if hint_norm in WARD_ROUTE_MAP:
            return hint_norm

    if locality:
        loc_lower = locality.strip().lower()
        for ward_code, spec in WARD_ROUTE_MAP.items():
            if ward_code.lower() in loc_lower or any(kw in loc_lower for kw in spec.keywords):
                return ward_code

    if latitude is not None and longitude is not None:
        for ward_code, spec in WARD_ROUTE_MAP.items():
            if (
                spec.lat_min <= latitude <= spec.lat_max
                and spec.lon_min <= longitude <= spec.lon_max
            ):
                return ward_code

    return None


def evaluate_approval_rules(
    incident: SupervisorIncidentInput,
    priority: PriorityLevel,
) -> tuple[bool, list[str]]:
    """
    Determines whether human supervisor approval is required (PENDING_APPROVAL).
    Per workflow spec & README: P1/CRITICAL priority or high-risk incident types require human approval.
    """
    reasons: list[str] = []
    if priority == PriorityLevel.P1:
        reasons.append("APPROVAL_RULE_P1_CRITICAL_PRIORITY")

    if incident.incident_type.strip().upper() in HIGH_RISK_INCIDENT_TYPES:
        reasons.append("APPROVAL_RULE_HIGH_RISK_INCIDENT_TYPE")

    return (len(reasons) > 0, reasons)