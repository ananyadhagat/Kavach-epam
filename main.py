import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s: %(name)s: %(message)s",
)
from fastapi import FastAPI

from app.api.sanitation_routes import router as sanitation_router

app = FastAPI(
    title="KAVACH Sanitation Agent",
    description="Connects the Supervisor Agent to the Dispatch Agent.",
    version="0.1.0",
)

app.include_router(sanitation_router)


@app.get("/health")
def health_check():
    return {
        "status": "healthy",
        "agent": "sanitation-agent",
    }

