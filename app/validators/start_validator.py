from app.schemas.evidence import EvidenceRecord, EvidenceStatus, EvidenceType
from app.schemas.location_event import (
    LocationCaptureStatus,
    LocationEventRecord,
    LocationEventType,
)
from app.schemas.worker_task import WorkerTask


class StartPrerequisiteError(ValueError):
    pass


def validate_start_prerequisites(
    task: WorkerTask,
    evidence_records: list[EvidenceRecord],
    arrival: LocationEventRecord | None,
) -> None:
    # Only server records count: a photo that was selected locally, is
    # still uploading, or failed validation never produces a record.
    confirmed_before = any(
        record.task_id == task.task_id
        and record.worker_id == task.assigned_worker_id
        and record.evidence_type == EvidenceType.BEFORE
        and record.status == EvidenceStatus.STORED
        for record in evidence_records
    )

    if not confirmed_before:
        raise StartPrerequisiteError(
            "A stored BEFORE image is required before starting the task."
        )

    # No exception policy for unavailable GPS has been agreed, so only a
    # CAPTURED fix (within the accuracy limit) satisfies arrival.
    if (
        arrival is None
        or arrival.task_id != task.task_id
        or arrival.worker_id != task.assigned_worker_id
        or arrival.event_type != LocationEventType.ARRIVAL
        or arrival.capture_status != LocationCaptureStatus.CAPTURED
    ):
        raise StartPrerequisiteError(
            "A captured arrival location is required before starting the "
            "task."
        )
