from typing import Optional

from fastapi import FastAPI
from pydantic import BaseModel

from app.data import SAMPLE_INCIDENTS
from app.supervisor import evaluate

app = FastAPI(title="Kavach Supervisor Agent")


class Incident(BaseModel):
    incident_id: str
    description: str
    category: str
    ward: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    # None means "not known". It is NOT the same as False.
    walking_path_obstructed: Optional[bool] = None
    immediate_safety_risk: Optional[bool] = None
    evidence_complete: bool
    is_duplicate: bool = False


@app.get("/")
def home():
    return {"message": "Kavach Supervisor Agent is running"}


@app.get("/samples")
def samples():
    return SAMPLE_INCIDENTS


@app.post("/supervisor/evaluate")
def supervisor_evaluate(incident: Incident):
    return evaluate(incident.model_dump())
