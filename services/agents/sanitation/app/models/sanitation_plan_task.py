from typing import Any
from pydantic import BaseModel, ConfigDict, Field

from app.schemas.sanitation_task import (
    SanitationTaskStatus,
    TaskDuration,
    TaskResourceDemand,
)


class SanitationPlanTaskModel(BaseModel):
    """In-memory domain model for a planned sanitation task."""

    model_config = ConfigDict(extra="ignore")

    plan_id: str
    task_id: str
    sequence: int
    task_code: str
    title: str
    description: str
    depends_on: list[str] = Field(default_factory=list)
    estimated_duration: TaskDuration = Field(default_factory=TaskDuration)
    required_resources: list[TaskResourceDemand] = Field(default_factory=list)
    completion_criteria: list[str] = Field(default_factory=list)
    status: SanitationTaskStatus = SanitationTaskStatus.NOT_STARTED
