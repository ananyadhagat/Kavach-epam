from datetime import datetime, timezone

workers = [
    {
        "worker_id": "W001",
        "latitude": 25.4358,
        "longitude": 81.8463,
        "skills": ["SANITATION_OPERATIVE", "WASTE_COLLECTION"],
        "equipment": ["PPE_GENERAL", "CLEANING_KIT"],
        "available": True,
        "active_tasks": 0,
        "max_active_tasks": 3,
        "location_updated_at": datetime.now(timezone.utc)
    },
    {
        "worker_id": "W002",
        "latitude": 25.4400,
        "longitude": 81.8500,
        "skills": ["DRAIN_CLEANING", "SANITATION_OPERATIVE"],
        "equipment": ["PPE_GENERAL", "PUMP"],
        "available": True,
        "active_tasks": 1,
        "max_active_tasks": 3,
        "location_updated_at": datetime.now(timezone.utc)
    },
    {
        "worker_id": "W003",
        "latitude": 25.4280,
        "longitude": 81.8400,
        "skills": ["WASTE_COLLECTION"],
        "equipment": ["WASTE_VEHICLE", "PPE_GENERAL"],
        "available": True,
        "active_tasks": 0,
        "max_active_tasks": 2,
        "location_updated_at": datetime.now(timezone.utc)
    },
    {
        "worker_id": "W004",
        "latitude": 25.4450,
        "longitude": 81.8550,
        "skills": ["INSPECTION", "SANITATION_OPERATIVE"],
        "equipment": ["INSPECTION_TOOLS", "PPE_GENERAL"],
        "available": True,
        "active_tasks": 0,
        "max_active_tasks": 2,
        "location_updated_at": datetime.now(timezone.utc)
    },
    {
        "worker_id": "W005",
        "latitude": 25.4200,
        "longitude": 81.8300,
        "skills": ["SANITATION_OPERATIVE"],
        "equipment": ["PPE_GENERAL", "CLEANING_KIT"],
        "available": True,
        "active_tasks": 2,
        "max_active_tasks": 3,
        "location_updated_at": datetime.now(timezone.utc)
    }
]

tasks = {}