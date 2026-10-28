from enum import Enum
from typing import Any
from pydantic import BaseModel, ConfigDict, Field, model_validator


class SanitationTaskStatus(str, Enum):
    NOT_STARTED = "NOT_STARTED"


class DurationEstimateStatus(str, Enum):
    CALCULATED = "CALCULATED"
    RANGE_ESTIMATE = "RANGE_ESTIMATE"
    NEEDS_MORE_DATA = "NEEDS_MORE_DATA"


class TaskDuration(BaseModel):
    """Estimated duration for a single task."""

    model_config = ConfigDict(extra="forbid")

    minutes: float | None = Field(default=None, ge=0)
    status: DurationEstimateStatus = DurationEstimateStatus.NEEDS_MORE_DATA
    basis: list[str] = Field(default_factory=list)


class TaskResourceDemand(BaseModel):
    """Estimated resource requirement for a single task."""

    model_config = ConfigDict(extra="forbid")

    resource_code: str = Field(min_length=1)
    quantity: float | int | None = Field(default=None, ge=0)
    unit: str | None = None
    basis: str = Field(default="REQUIRED_BY_TEMPLATE")


class SanitationTask(BaseModel):
    """A planned sanitation task item within a plan checklist."""

    model_config = ConfigDict(extra="forbid")

    task_id: str = Field(min_length=1)
    sequence: int = Field(default=1, ge=1)
    task_code: str = Field(min_length=1)
    title: str = Field(default="")
    task_name: str | None = None
    description: str = Field(min_length=1)
    depends_on: list[str] = Field(default_factory=list)
    estimated_duration: TaskDuration = Field(default_factory=TaskDuration)
    required_resources: list[TaskResourceDemand] = Field(default_factory=list)
    completion_criteria: list[str] = Field(default_factory=list)
    checklist: list[str] = Field(default_factory=list)
    status: SanitationTaskStatus = SanitationTaskStatus.NOT_STARTED

    @model_validator(mode="before")
    @classmethod
    def sync_title_task_name(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if "task_name" in data and not data.get("title"):
                data["title"] = data["task_name"]
            elif "title" in data and not data.get("task_name"):
                data["task_name"] = data["title"]
        return data

    @model_validator(mode="after")
    def validate_task_invariants(self):
        if not self.title and not self.task_name:
            raise ValueError("Task must have a title or task_name.")

        if self.task_id in self.depends_on:
            raise ValueError(f"Task '{self.task_id}' cannot depend on itself.")

        if len(self.depends_on) != len(set(self.depends_on)):
            raise ValueError(
                f"Task '{self.task_id}' contains duplicate dependencies."
            )

        if self.status != SanitationTaskStatus.NOT_STARTED:
            raise ValueError("All planned tasks must start in NOT_STARTED status.")

        return self
