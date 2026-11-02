from app.schemas.evidence import EvidenceRecord, EvidenceType
from app.schemas.location_event import (
    LocationCaptureStatus,
    LocationEventRecord,
    LocationEventType,
)
from app.schemas.worker_task import WorkerTask


class CompletionValidationError(ValueError):
    pass


def validate_completion(
    task: WorkerTask,
    evidence_records: list[EvidenceRecord],
    completion_location: LocationEventRecord | None,
    submitted_evidence_ids: list[str],
) -> None:
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

    if not task.arrival_location_event_id:
        raise CompletionValidationError(
            "Arrival location is required before completion."
        )

    # No exception policy for unavailable GPS has been agreed, so only a
    # CAPTURED completion location is accepted.
    if completion_location is None:
        raise CompletionValidationError(
            "A captured completion location is required."
        )

    if completion_location.task_id != task.task_id:
        raise CompletionValidationError("Completion location task mismatch.")

    if completion_location.worker_id != task.assigned_worker_id:
        raise CompletionValidationError("Completion location worker mismatch.")

    if completion_location.event_type != LocationEventType.COMPLETION:
        raise CompletionValidationError(
            "A COMPLETION location event is required."
        )

    if completion_location.capture_status == LocationCaptureStatus.INACCURATE:
        raise CompletionValidationError(
            "Completion location is marked inaccurate."
        )

    if completion_location.capture_status != LocationCaptureStatus.CAPTURED:
        raise CompletionValidationError(
            "Completion location is unavailable; a captured location is "
            "required."
        )