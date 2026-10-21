from app.schemas.checklist import ChecklistStatus
from app.schemas.evidence import EvidenceRecord, EvidenceType
from app.schemas.location_event import (
    LocationCaptureStatus,
    LocationEventRecord,
)
from app.schemas.worker_task import WorkerTask


class CompletionValidationError(ValueError):
    pass


def validate_completion(
    task: WorkerTask,
    checklist_states: dict[str, str],
    evidence_records: list[EvidenceRecord],
    completion_location: LocationEventRecord | None,
    submitted_step_ids: list[str],
    submitted_evidence_ids: list[str],
    require_arrival_location: bool = False,
) -> None:
    required_steps = {
        step.step_id
        for step in task.checklist
        if step.required
    }

    submitted_steps = set(submitted_step_ids)
    task_steps = {step.step_id for step in task.checklist}

    unknown = sorted(submitted_steps - task_steps)

    if unknown:
        raise CompletionValidationError(
            f"Checklist steps do not belong to this task: {unknown}"
        )

    if not required_steps.issubset(submitted_steps):
        missing = sorted(required_steps - submitted_steps)
        raise CompletionValidationError(
            f"Missing required checklist references: {missing}"
        )

    for step_id in required_steps:
        if checklist_states.get(step_id) != ChecklistStatus.COMPLETED.value:
            raise CompletionValidationError(
                f"Required checklist step {step_id} is not completed."
            )

    evidence_by_id = {
        record.evidence_id: record
        for record in evidence_records
    }

    selected = []

    for evidence_id in submitted_evidence_ids:
        record = evidence_by_id.get(evidence_id)

        if record is None:
            raise CompletionValidationError(
                f"Evidence {evidence_id} does not belong to this task."
            )

        if record.task_id != task.task_id:
            raise CompletionValidationError("Task/evidence mismatch.")

        if record.worker_id != task.assigned_worker_id:
            raise CompletionValidationError("Worker/evidence mismatch.")

        selected.append(record)

    if not any(item.evidence_type == EvidenceType.BEFORE for item in selected):
        raise CompletionValidationError("A BEFORE image is required.")

    if not any(item.evidence_type == EvidenceType.AFTER for item in selected):
        raise CompletionValidationError("An AFTER image is required.")

    if require_arrival_location and not task.arrival_location_event_id:
        raise CompletionValidationError(
            "Arrival location is required by the current policy."
        )

    if completion_location is not None:
        if completion_location.task_id != task.task_id:
            raise CompletionValidationError("Completion location task mismatch.")

        if completion_location.worker_id != task.assigned_worker_id:
            raise CompletionValidationError("Completion location worker mismatch.")

        if completion_location.event_type.value != "COMPLETION":
            raise CompletionValidationError(
                "A COMPLETION location event is required."
            )

        if completion_location.capture_status == LocationCaptureStatus.INACCURATE:
            raise CompletionValidationError(
                "Completion location is marked inaccurate."
            )