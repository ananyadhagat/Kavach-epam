from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Optional, Any
from app.dispatch import dispatch_task
from app.data import workers, tasks

app = FastAPI(title="KAVACH Dispatch Agent")

class DispatchRequest(BaseModel):
    incident_id: str
    latitude: float
    longitude: float
    required_skills: list[str] = []
    required_equipment: list[str] = []
    priority: str = "MEDIUM"
    max_radius_km: float = 10.0


@app.get("/api/v1/dispatch/health")
def health():
    return {"status": "healthy"}


@app.get("/api/v1/workers")
def get_workers():
    return workers


@app.post("/api/v1/dispatch/assign")
def assign_worker(request: DispatchRequest):

    if request.incident_id in tasks:
        return tasks[request.incident_id]

    candidates = dispatch_task(
        latitude=request.latitude,
        longitude=request.longitude,
        required_skills=request.required_skills,
        required_equipment=request.required_equipment,
        max_radius_km=request.max_radius_km
    )

    if not candidates:
        result = {
            "incident_id": request.incident_id,
            "status": "UNASSIGNED",
            "message": "No eligible workers available",
            "escalation_required": True
        }

        tasks[request.incident_id] = result
        return result

    selected_worker = candidates[0]

    selected_worker["active_tasks"] += 1

    if selected_worker["active_tasks"] >= selected_worker["max_active_tasks"]:
        selected_worker["available"] = False

    result = {
        "incident_id": request.incident_id,
        "status": "ASSIGNED",
        "assigned_worker": selected_worker["worker_id"],
        "distance_km": selected_worker["distance_km"],
        "priority": request.priority,
        "escalation_required": False
    }

    tasks[request.incident_id] = result

    return result