import logging
from fastapi import FastAPI
from app.api.sanitation_routes import router as sanitation_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

app = FastAPI(
    title="KAVACH Module 04 — Sanitation Planning Agent",
    description="Deterministic, policy-driven sanitation planning connecting Supervisor to Dispatch.",
    version="1.0.0",
)

app.include_router(sanitation_router)


@app.get("/health")
def health_check():
    """Health check endpoint confirming service status and in-memory storage."""
    return {
        "status": "healthy",
        "agent": "sanitation-agent",
        "module": "04-sanitation-planning",
        "storage": "in-memory-only",
        "zero_llm_mode": True,
    }
