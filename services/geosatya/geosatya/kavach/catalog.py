"""Fixed vocabularies used by the KAVACH UI. Values that are business decisions
(prices, legal SLAs) are deliberately not here."""

ORG_CATEGORIES = [
    ("MUNICIPAL_BODY", "Municipal body / Nagar Nigam"),
    ("GOVERNMENT_DEPARTMENT", "Government department"),
    ("ROAD_AUTHORITY", "Road maintenance organization"),
    ("INFRASTRUCTURE", "Infrastructure operator"),
    ("FACILITY_MANAGEMENT", "Facility management company"),
    ("INDUSTRIAL_CAMPUS", "Industrial campus"),
    ("INSTITUTION", "Institution (university, hospital, …)"),
    ("OTHER", "Other organization"),
]

EVENT_CATEGORIES = [
    ("CONCERT", "Concert"), ("FESTIVAL", "Festival"), ("EXHIBITION", "Exhibition"), ("SPORTS", "Sports event"),
    ("CONFERENCE", "Conference"), ("PUBLIC_GATHERING", "Public gathering"), ("RELIGIOUS_CULTURAL", "Religious / cultural event"),
    ("PRIVATE", "Private event"), ("OTHER", "Other event"),
]

ROAD_TYPES = [
    ("LOCAL", "Local / city road"), ("STATE_HIGHWAY", "State highway"), ("NATIONAL_HIGHWAY", "National highway"),
    ("UNKNOWN", "Not sure"),
]

PRIORITY_LEVELS = ["LOW", "NORMAL", "MEDIUM", "HIGH"]

# Kavach's default resolution targets in hours. These are configurable
# workspace targets, not legal or official service-level agreements.
DEFAULT_TARGET_HOURS = {
    "road_damage": 72, "garbage": 12, "water_leakage": 24, "drainage": 24, "streetlight": 48,
    "infrastructure": 72, "safety_hazard": 6, "other": 72,
    "public_toilet": 24, "sanitation": 12, "waste_disposal": 24, "highway": 72,
    "medical_assistance": 0.25, "crowd_management": 0.5, "security_concern": 0.5, "missing_person": 1, "event_operations": 1,
}

DEFAULT_WORKER_ROLES = {
    "ORGANIZATION": ["Field worker", "Technician", "Sanitation worker", "Driver"],
    "EVENT": ["Volunteer", "First-aid responder", "Security staff", "Crowd marshal", "Maintenance crew"],
}

PLANS = [
    # plan_id, name, audience, billing_basis, max_workers, max_events, max_supervisors, features
    ("PILOT", "Pilot (development)", "ANY", "CUSTOM", 25, 3, 5,
     ["live_map", "dispatch", "geosatya_verification", "eta_etr", "reports"]),
    ("EVENT_PASS", "Event Pass", "EVENT", "PER_EVENT", 200, 1, 20,
     ["live_map", "dispatch", "zones", "eta_etr", "reports"]),
    ("ORG_STANDARD", "Organization", "ORGANIZATION", "SUBSCRIPTION", 500, None, 50,
     ["live_map", "dispatch", "departments", "geosatya_verification", "eta_etr", "reports", "audit"]),
    ("ENTERPRISE", "Enterprise", "ANY", "CUSTOM", None, None, None,
     ["live_map", "dispatch", "departments", "zones", "geosatya_verification", "eta_etr", "reports", "audit", "integrations"]),
]


def label_of(pairs, key):
    return dict(pairs).get(key, key)
