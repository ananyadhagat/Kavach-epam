
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from app.data import workers, tasks
from app.dispatch import dispatch_task

app = FastAPI(
    title="KAVACH Dispatch Agent",
    description="Deterministic worker assignment for civic incidents",
    version="0.1.0",
)


class DispatchRequest(BaseModel):
    incident_id: str
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    required_skills: list[str] = Field(min_length=1)
    required_equipment: list[str] = Field(default_factory=list)
    priority: str = "HIGH"
    max_radius_km: float = Field(default=2.0, gt=0, le=50)


@app.get("/")
def home():
    return {
        "project": "KAVACH Dispatch Agent",
        "status": "running",
        "docs": "/docs",
    }


@app.get("/api/v1/dispatch/health")
def health():
    return {
        "status": "healthy",
        "worker_count": len(workers),
        "database": "in-memory demo",
    }


@app.get("/api/v1/workers")
def get_workers():
    return [
        {
            **worker,
            "location_updated_at": worker[
                "location_updated_at"
            ].isoformat(),
        }
        for worker in workers
    ]


@app.post("/api/v1/dispatch/assign")
def assign_task(request: DispatchRequest):
    if request.incident_id in tasks:
        return tasks[request.incident_id]

    result = dispatch_task(request.model_dump(), workers)

    if not result["candidates"]:
        response = {
            "incident_id": request.incident_id,
            "status": "UNASSIGNED",
            "message": "Escalate to Supervisor",
            "rejected_workers": result["rejected_workers"],
        }
        tasks[request.incident_id] = response
        return response

    best = result["candidates"][0]
    selected = next(
        w for w in workers if w["worker_id"] == best["worker_id"]
    )

    selected["active_tasks"] += 1
    if selected["active_tasks"] >= selected["max_active_tasks"]:
        selected["available"] = False

    response = {
        "assignment_id": str(uuid4()),
        "incident_id": request.incident_id,
        "status": "ASSIGNED",
        "assigned_worker": best,
        "selection_reason": "Best eligible candidate by distance and workload score",
        "ranking": result["candidates"],
        "rejected_workers": result["rejected_workers"],
        "priority": request.priority,
    }

    tasks[request.incident_id] = response
    return response


@app.get("/api/v1/dispatch/tasks/{incident_id}")
def get_task(incident_id: str):
    if incident_id not in tasks:
        raise HTTPException(status_code=404, detail="Task not found")
    return tasks[incident_id]
