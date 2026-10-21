
from datetime import datetime, timezone

workers = [
    {
        "worker_id": "W001",
        "name": "Worker A",
        "latitude": 23.1810,
        "longitude": 75.7900,
        "skills": ["sanitation", "waste_collection"],
        "equipment": ["cleaning_kit", "waste_vehicle"],
        "available": True,
        "active_tasks": 1,
        "max_active_tasks": 3,
        "location_updated_at": datetime.now(timezone.utc),
    },
    {
        "worker_id": "W002",
        "name": "Worker B",
        "latitude": 23.1790,
        "longitude": 75.8000,
        "skills": ["sanitation", "drain_cleaning"],
        "equipment": ["cleaning_kit", "pump"],
        "available": True,
        "active_tasks": 0,
        "max_active_tasks": 2,
        "location_updated_at": datetime.now(timezone.utc),
    },
    {
        "worker_id": "W003",
        "name": "Worker C",
        "latitude": 23.1850,
        "longitude": 75.7850,
        "skills": ["waste_collection"],
        "equipment": ["waste_vehicle"],
        "available": True,
        "active_tasks": 0,
        "max_active_tasks": 2,
        "location_updated_at": datetime.now(timezone.utc),
    },
    {
        "worker_id": "W004",
        "name": "Worker D",
        "latitude": 23.1775,
        "longitude": 75.7860,
        "skills": ["sanitation", "waste_collection"],
        "equipment": ["cleaning_kit"],
        "available": False,
        "active_tasks": 0,
        "max_active_tasks": 2,
        "location_updated_at": datetime.now(timezone.utc),
    },
]

tasks = {}
