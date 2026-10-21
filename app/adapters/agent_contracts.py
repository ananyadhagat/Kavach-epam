"""Translate upstream agent contracts into the verification agent's internal dictionaries."""

from collections.abc import Iterable

from pydantic import ValidationError

from ..contracts.v1 import (
    EvidenceRecord,
    EvidenceType,
    EvidenceUploadStatus,
    FieldWorkerCompletion,
    LocationCaptureStatus,
    LocationEvent,
    LocationEventType,
    SanitationPlan,
)


class ContractAdapterError(ValueError):
    pass


def _validate(model, value, label):
    try:
        return model.model_validate(value)
    except ValidationError as exc:
        raise ContractAdapterError(f"Invalid {label} contract: {exc.errors()[0]['msg']}") from exc


def adapt_field_worker_completion(
    completion: dict,
    *,
    evidence_records: Iterable[dict],
    location_events: Iterable[dict] = (),
) -> dict:
    """Map Field Worker IDs and enums; absent checklist entries remain unknown claims."""
    source = _validate(FieldWorkerCompletion, completion, "Field Worker completion")
    evidence_by_id: dict[str, EvidenceRecord] = {}
    for raw in evidence_records:
        item = _validate(EvidenceRecord, raw, "evidence")
        if item.evidence_id in evidence_by_id:
            raise ContractAdapterError(f"Duplicate evidence record: {item.evidence_id}")
        evidence_by_id[item.evidence_id] = item

    evidence: list[dict] = []
    referenced = [*source.before_evidence_ids, *source.after_evidence_ids]
    if len(set(referenced)) != len(referenced):
        raise ContractAdapterError("Completion references an evidence ID more than once.")
    expected = [
        *((evidence_id, EvidenceType.BEFORE) for evidence_id in source.before_evidence_ids),
        *((evidence_id, EvidenceType.AFTER) for evidence_id in source.after_evidence_ids),
    ]
    for evidence_id, expected_type in expected:
        record = evidence_by_id.get(evidence_id)
        if record is None:
            raise ContractAdapterError(f"Completion references unknown evidence ID: {evidence_id}")
        if record.task_id != source.task_id:
            raise ContractAdapterError(f"Evidence {evidence_id} belongs to another task.")
        if record.evidence_type != expected_type:
            raise ContractAdapterError(f"Evidence {evidence_id} has the wrong evidence type.")
        status = {
            EvidenceUploadStatus.STORED: "READY",
            EvidenceUploadStatus.PENDING: "PENDING",
            EvidenceUploadStatus.FAILED: "FAILED",
        }[record.upload_status]
        evidence.append({
            "evidence_id": record.evidence_id,
            "task_id": record.task_id,
            "type": "BEFORE_IMAGE" if expected_type == EvidenceType.BEFORE else "AFTER_IMAGE",
            "status": status,
            "storage_path": record.storage_key,
            "source_upload_status": record.upload_status.value,
        })

    event = None
    if source.completion_location_event_id:
        for raw in location_events:
            candidate = _validate(LocationEvent, raw, "location event")
            if candidate.location_event_id == source.completion_location_event_id:
                event = candidate
                break
        if event is None:
            raise ContractAdapterError(
                f"Completion references unknown location event: {source.completion_location_event_id}"
            )
        if event.task_id != source.task_id:
            raise ContractAdapterError("Completion location event belongs to another task.")
        if event.event_type != LocationEventType.COMPLETION:
            raise ContractAdapterError("Completion must reference a COMPLETION location event.")

    location = None
    if event is not None:
        location = {
            "latitude": event.latitude,
            "longitude": event.longitude,
            "accuracy_m": event.accuracy_meters,
            "timestamp_valid": event.received_at_server is not None,
            "capture_status": event.capture_status.value,
            "location_event_id": event.location_event_id,
        }

    return {
        "task_id": source.task_id,
        "submission_id": source.submission_id,
        "completion_note": source.completion_note,
        "checklist": {step_id: True for step_id in source.checklist_completed},
        "evidence": evidence,
        "location": location,
    }


def adapt_sanitation_plan(plan: dict, *, task_id: str, authoritative_site: dict | None = None) -> dict:
    """Translate a Sanitation plan without inferring IDs, mandatory flags, or target coordinates."""
    source = _validate(SanitationPlan, plan, "Sanitation plan")
    warnings: list[str] = []
    requirements: list[dict] = []
    if not source.task_checklist:
        warnings.append("Sanitation plan contains no task checklist entries.")
    for index, item in enumerate(source.task_checklist, start=1):
        missing_fields = []
        if not item.requirement_id:
            missing_fields.append("requirement_id")
        if item.mandatory is None:
            missing_fields.append("mandatory flag")
        if missing_fields:
            warnings.append(
                f"Sanitation checklist item {item.task_id or index} is missing "
                + " and ".join(missing_fields)
                + "; verification cannot safely classify it."
            )
            continue
        requirements.append({
            "requirement_id": item.requirement_id,
            "label": item.description,
            "mandatory": item.mandatory,
            "target_observation": item.target_observation,
        })

    site = dict(authoritative_site or {})
    # The Sanitation example location is a site/zone label, not an approved coordinate source.
    if not site:
        warnings.append("Authoritative target coordinates and tolerance were not supplied by the location owner.")
    else:
        coordinates_present = all(name in site and site[name] is not None for name in ("latitude", "longitude", "tolerance_m"))
        if not coordinates_present:
            warnings.append("Authoritative target coordinates and tolerance are incomplete.")

    return {
        "task_id": task_id,
        "incident_id": source.incident_id,
        "site": site,
        "requirements": requirements,
        "contract_warnings": warnings,
    }
