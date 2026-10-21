from copy import deepcopy

from ..adapters.agent_contracts import adapt_sanitation_plan


TASKS = {
    "TASK-100": {
        "task_id": "TASK-100",
        "site": {"latitude": 28.6139, "longitude": 77.2090, "tolerance_m": 150},
        "requirements": [
            {"requirement_id": "STEP-01", "label": "Remove visible scattered waste", "mandatory": True},
            {"requirement_id": "STEP-02", "label": "Clear the walking path", "mandatory": True},
            {"requirement_id": "STEP-03", "label": "Remove visible overflow", "mandatory": True},
        ],
    }
}


class TaskRepository:
    def __init__(self, tasks: dict | None = None):
        self.tasks = tasks if tasks is not None else TASKS

    def get(self, task_id: str) -> dict | None:
        task = self.tasks.get(task_id)
        if task and "sanitation_plan" in task:
            return adapt_sanitation_plan(
                task["sanitation_plan"], task_id=task_id, authoritative_site=task.get("authoritative_site"),
            )
        return deepcopy(task) if task else None

    def save_sanitation_plan(self, task_id: str, plan: dict, authoritative_site: dict | None = None) -> None:
        self.tasks[task_id] = {"sanitation_plan": deepcopy(plan), "authoritative_site": deepcopy(authoritative_site)}


InMemoryTaskRepository = TaskRepository
