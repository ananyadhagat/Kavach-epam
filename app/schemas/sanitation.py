from enum import Enum

from pydantic import BaseModel, Field, model_validator


class SanitationPriority(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class SanitationRequest(BaseModel):
    complaint_id: str = Field(min_length=1)
    description: str = Field(min_length=5)
    location: str = Field(min_length=1)
    priority: SanitationPriority
    estimated_waste_kg: float | None = Field(default=None, ge=0)


class SanitationTask(BaseModel):
    task_id: str = Field(default="", min_length=0)
    task_name: str = Field(min_length=1)
    description: str
    estimated_duration_minutes: int | None = Field(default=None, ge=0)
    required_resources: list[str] = Field(default_factory=list)
    checklist: list[str] = Field(default_factory=list)
    depends_on: list[str] = Field(default_factory=list)
    completion_criteria: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_dependencies(self):
        if self.task_id and self.task_id in self.depends_on:
            raise ValueError("A task cannot depend on itself.")

        if len(self.depends_on) != len(set(self.depends_on)):
            raise ValueError("Task dependencies must be unique.")

        return self


class SanitationPlan(BaseModel):
    complaint_id: str
    summary: str
    tasks: list[SanitationTask] = Field(default_factory=list)
    safety_notes: list[str] = Field(default_factory=list)
    requires_human_review: bool = True
    resource_estimate: dict = Field(default_factory=dict)
    duration_estimate: dict = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_task_relationships(self):
        task_ids = [task.task_id for task in self.tasks if task.task_id]

        if len(task_ids) != len(set(task_ids)):
            raise ValueError("Task IDs must be unique.")

        known_ids = set(task_ids)

        for task in self.tasks:
            missing = set(task.depends_on) - known_ids

            if missing:
                raise ValueError(
                    f"Task '{task.task_id}' references unknown dependencies: "
                    f"{sorted(missing)}"
                )

        dependencies = {
            task.task_id: task.depends_on
            for task in self.tasks
            if task.task_id
        }

        visiting = set()
        visited = set()

        def visit(task_id: str) -> bool:
            if task_id in visiting:
                return True

            if task_id in visited:
                return False

            visiting.add(task_id)

            for dependency in dependencies[task_id]:
                if visit(dependency):
                    return True

            visiting.remove(task_id)
            visited.add(task_id)
            return False

        for task_id in dependencies:
            if visit(task_id):
                raise ValueError(
                    "Circular task dependencies are not allowed."
                )

        return self
