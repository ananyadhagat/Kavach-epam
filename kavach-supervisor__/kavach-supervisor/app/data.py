
DEPARTMENTS = ["SANITATION", "MAINTENANCE", "ELECTRICAL", "WATER_SUPPLY"]

# complaint category -> department that should handle it
CATEGORY_TO_DEPARTMENT = {
    "WASTE_OVERFLOW": "SANITATION",
    "ILLEGAL_DUMPING": "SANITATION",
    "TOILET_UNCLEAN": "SANITATION",
    "DRAIN_BLOCKAGE": "SANITATION",
    "BROKEN_STREETLIGHT": "ELECTRICAL",
    "BROKEN_PIPE": "WATER_SUPPLY",
    "DAMAGED_BENCH": "MAINTENANCE",
}

# only Sanitation has a domain agent right now
DEPARTMENTS_WITH_AGENT = ["SANITATION"]

# actions each department is allowed to put in a plan
ALLOWED_ACTIONS = {
    "SANITATION": ["REMOVE_WASTE", "CLEAN_AREA", "SANITIZE_AREA", "CHECK_PATH_CLEAR",
                   "CHECK_DRAINAGE", "PLACE_WARNING_SIGN"],
    "MAINTENANCE": ["INSPECT_ASSET", "REPAIR_ASSET", "PLACE_WARNING_SIGN"],
    "ELECTRICAL": ["INSPECT_FAULT", "ISOLATE_POWER", "REPAIR_LIGHT"],
    "WATER_SUPPLY": ["INSPECT_PIPE", "STOP_WATER_FLOW", "REPAIR_PIPE"],
}

# starting actions for each category
DEFAULT_ACTIONS = {
    "WASTE_OVERFLOW": ["REMOVE_WASTE", "CLEAN_AREA"],
    "ILLEGAL_DUMPING": ["REMOVE_WASTE", "CLEAN_AREA"],
    "TOILET_UNCLEAN": ["CLEAN_AREA", "SANITIZE_AREA"],
    "DRAIN_BLOCKAGE": ["CHECK_DRAINAGE", "CLEAN_AREA"],
    "BROKEN_STREETLIGHT": ["INSPECT_FAULT"],
    "BROKEN_PIPE": ["INSPECT_PIPE"],
    "DAMAGED_BENCH": ["INSPECT_ASSET"],
}

# risks Gemini is allowed to report
ALLOWED_RISKS = ["IMMEDIATE_SAFETY_RISK", "WALKING_PATH_OBSTRUCTED", "HEALTH_HAZARD"]

# priorities that can be approved automatically (HIGH always needs a human)
AUTO_APPROVE_PRIORITIES = ["LOW", "MEDIUM"]

# sample incidents for quick testing (GET /samples)
SAMPLE_INCIDENTS = [
    {
        "incident_id": "INC-101",
        "description": "Dustbin overflowing near the main gate, waste is blocking the path.",
        "category": "WASTE_OVERFLOW",
        "ward": "Ward-1",
        "walking_path_obstructed": True,
        "immediate_safety_risk": False,
        "evidence_complete": True,
    },
    {
        "incident_id": "INC-102",
        "description": "Drain blocked and dirty water is flowing on the ghat steps.",
        "category": "DRAIN_BLOCKAGE",
        "ward": "Ghat-3",
        "walking_path_obstructed": True,
        "immediate_safety_risk": True,
        "evidence_complete": True,
    },
    {
        "incident_id": "INC-103",
        "description": "Bins are full near the bus stand.",
        "category": "WASTE_OVERFLOW",
        "ward": "Ward-5",
        "walking_path_obstructed": True,
        "immediate_safety_risk": None,
        "evidence_complete": True,
    },
    {
        "incident_id": "INC-104",
        "description": "Streetlight is not working near the parking.",
        "category": "BROKEN_STREETLIGHT",
        "ward": "Ward-2",
        "walking_path_obstructed": False,
        "immediate_safety_risk": False,
        "evidence_complete": True,
    },
]
