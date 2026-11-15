from copy import deepcopy
from pathlib import Path

from ..validators.evidence_validator import InvalidStoredImage, validate_image_bytes


SUBMISSIONS = {
    "SUB-PASS": {
        "task_id": "TASK-100",
        "evidence": [
            {"evidence_id": "IMG-BEFORE-1", "type": "BEFORE_IMAGE", "status": "READY", "task_id": "TASK-100"},
            {"evidence_id": "IMG-AFTER-1", "type": "AFTER_IMAGE", "status": "READY", "task_id": "TASK-100"},
        ],
        "location": {"latitude": 28.6142, "longitude": 77.2092, "accuracy_m": 12, "timestamp_valid": True},
        "checklist": {"STEP-01": True, "STEP-02": True, "STEP-03": True},
        "mock_visual": {
            "before_observations": {"scattered_waste": "PRESENT", "path_obstructed": "PRESENT", "overflow": "PRESENT"},
            "after_observations": {"scattered_waste": "ABSENT", "path_obstructed": "ABSENT", "overflow": "ABSENT"},
            "visual_change": "IMPROVED", "limitations": [],
        },
    },
    "SUB-FAIL": {
        "task_id": "TASK-100",
        "evidence": [
            {"evidence_id": "IMG-BEFORE-2", "type": "BEFORE_IMAGE", "status": "READY", "task_id": "TASK-100"},
            {"evidence_id": "IMG-AFTER-2", "type": "AFTER_IMAGE", "status": "READY", "task_id": "TASK-100"},
        ],
        "location": {"latitude": 28.6141, "longitude": 77.2090, "accuracy_m": 10, "timestamp_valid": True},
        "checklist": {"STEP-01": True, "STEP-02": True, "STEP-03": True},
        "mock_visual": {
            "before_observations": {"scattered_waste": "PRESENT", "path_obstructed": "PRESENT", "overflow": "PRESENT"},
            "after_observations": {"scattered_waste": "PRESENT", "path_obstructed": "ABSENT", "overflow": "ABSENT"},
            "visual_change": "IMPROVED", "limitations": [],
        },
    },
    "SUB-INCOMPLETE": {
        "task_id": "TASK-100",
        "evidence": [
            {"evidence_id": "IMG-BEFORE-3", "type": "BEFORE_IMAGE", "status": "READY", "task_id": "TASK-100"},
            {"evidence_id": "IMG-AFTER-3", "type": "AFTER_IMAGE", "status": "MISSING", "task_id": "TASK-100"},
        ],
        "location": None, "checklist": {"STEP-01": True}, "mock_visual": None,
    },
}


class EvidenceRepository:
    def __init__(self, submissions: dict | None = None, storage_root: str | Path = "stored_evidence",
                 evidence_records: dict | None = None, location_events: dict | None = None):
        self.submissions = submissions if submissions is not None else SUBMISSIONS
        self.storage_root = Path(storage_root).resolve()
        self.evidence_records = evidence_records or {}
        self.location_events = location_events or {}

    def get(self, submission_id: str) -> dict | None:
        submission = self.submissions.get(submission_id)
        return deepcopy(submission) if submission else None

    def get_evidence_records(self, evidence_ids: list[str]) -> list[dict]:
        return [deepcopy(self.evidence_records[item]) for item in evidence_ids if item in self.evidence_records]

    def get_location_events(self, event_ids: list[str]) -> list[dict]:
        return [deepcopy(self.location_events[item]) for item in event_ids if item in self.location_events]

    def save_evidence_record(self, evidence_record: dict) -> None:
        self.evidence_records[evidence_record["evidence_id"]] = deepcopy(evidence_record)

    def save_location_event(self, location_event: dict) -> None:
        self.location_events[location_event["location_event_id"]] = deepcopy(location_event)

    def load_image(self, evidence_item: dict) -> tuple[bytes, str]:
        """Load only server-recorded file references beneath the configured storage root."""
        stored_path = evidence_item.get("storage_path")
        if not isinstance(stored_path, str) or not stored_path.strip():
            raise InvalidStoredImage("Stored image reference is unavailable.")
        candidate = Path(stored_path)
        resolved = (candidate if candidate.is_absolute() else self.storage_root / candidate).resolve()
        if self.storage_root != resolved and self.storage_root not in resolved.parents:
            raise InvalidStoredImage("Stored image reference is outside the evidence store.")
        try:
            data = resolved.read_bytes()
        except OSError as exc:
            raise InvalidStoredImage("Stored image could not be read.") from exc
        return data, validate_image_bytes(data)


InMemoryEvidenceRepository = EvidenceRepository
