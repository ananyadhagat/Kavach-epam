from copy import deepcopy
from datetime import datetime
import tempfile
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.adapters.agent_contracts import ContractAdapterError, adapt_field_worker_completion, adapt_sanitation_plan
from app.contracts.v1 import (
    CONTRACT_VERSION,
    DispatchAssignmentRequest,
    DuplicateDetectionRequest,
    EvidenceRecord,
    FieldWorkerCompletion,
    GeolocationRequest,
    IncidentIntelligenceRequest,
    LocationEvent,
    Requirement,
    SanitationPlan,
    SupervisorEvaluationRequest,
    VerificationRequestV1,
    VerificationResponseV1,
)
from app.repositories.evidence_repository import EvidenceRepository
from app.repositories.task_repository import TaskRepository
from app.repositories.sqlite_repositories import SQLiteEvidenceRepository, SQLiteTaskRepository
from app.services.location_service import check_location, combine_location_checks
from app.schemas import VerificationRequest


def test_field_worker_completion_example_adapts_without_inventing_unchecked_claims():
    completion_json = {
        "task_id": "TASK-104",
        "completion_note": "Overflow collected and path cleaned",
        "checklist_completed": ["STEP-01", "STEP-02", "STEP-03"],
        "before_evidence_ids": ["EVD-501"],
        "after_evidence_ids": ["EVD-502"],
        "completion_location_event_id": "LOC-902",
    }
    evidence_records = [
        {"evidence_id": "EVD-501", "task_id": "TASK-104", "evidence_type": "BEFORE",
         "upload_status": "STORED", "storage_key": "tasks/TASK-104/before.jpg"},
        {"evidence_id": "EVD-502", "task_id": "TASK-104", "evidence_type": "AFTER",
         "upload_status": "STORED", "storage_key": "tasks/TASK-104/after.jpg"},
    ]
    location_events = [{
        "location_event_id": "LOC-902", "task_id": "TASK-104", "worker_id": "WRK-77",
        "event_type": "COMPLETION", "latitude": 22.7196, "longitude": 75.8577,
        "accuracy_meters": 18, "captured_at_device": "2026-10-12T10:00:00+05:30",
        "received_at_server": "2026-10-12T04:30:02Z", "capture_status": "CAPTURED",
    }]

    adapted = adapt_field_worker_completion(
        completion_json, evidence_records=evidence_records, location_events=location_events,
    )
    assert adapted["checklist"] == {"STEP-01": True, "STEP-02": True, "STEP-03": True}
    assert [item["type"] for item in adapted["evidence"]] == ["BEFORE_IMAGE", "AFTER_IMAGE"]
    assert all(item["status"] == "READY" for item in adapted["evidence"])
    assert adapted["evidence"][0]["storage_path"] == "tasks/TASK-104/before.jpg"
    assert adapted["location"]["location_event_id"] == "LOC-902"
    assert adapted["location"]["timestamp_valid"] is True
    assert FieldWorkerCompletion.model_validate(completion_json).task_id == "TASK-104"


def test_field_worker_checklist_step_ids_are_mapped_to_verification_checklist():
    completion_json = {
        "task_id": "TASK-104",
        "checklist_step_ids": ["STEP-01", "STEP-02"],
    }

    adapted = adapt_field_worker_completion(completion_json, evidence_records=[])

    assert adapted["checklist"] == {"STEP-01": True, "STEP-02": True}


def test_field_worker_bad_evidence_reference_is_rejected():
    completion = {"task_id": "TASK-104", "before_evidence_ids": ["OTHER"], "after_evidence_ids": []}
    record = {"evidence_id": "OTHER", "task_id": "TASK-999", "evidence_type": "BEFORE",
              "upload_status": "STORED", "storage_key": "private/file.jpg"}
    with pytest.raises(ContractAdapterError, match="belongs to another task"):
        adapt_field_worker_completion(completion, evidence_records=[record])


def test_sanitation_example_keeps_unknown_quantities_and_missing_policy_explicit(make_service):
    plan_json = {
        "incident_id": "INC-104", "planning_status": "PRELIMINARY_PLAN", "job_type": "WASTE_OVERFLOW",
        "cleaning_plan": {"objective": "Remove overflow and restore access", "steps": ["Collect waste"]},
        "resources_required": {"workers": {"count": None, "basis": "QUANTITY_NOT_MEASURED"},
                               "vehicle_required": None, "tools": ["WASTE_COLLECTION_TOOLS"]},
        "estimated_time": {"minutes": None, "estimate_type": "NEEDS_MORE_DATA"},
        "task_checklist": [], "assumptions": ["Waste quantity has not been measured"],
    }
    assert SanitationPlan.model_validate(plan_json).resources_required["workers"]["count"] is None
    adapted = adapt_sanitation_plan(plan_json, task_id="TASK-104")
    assert adapted["requirements"] == []
    assert any("no task checklist" in item.lower() for item in adapted["contract_warnings"])
    assert any("target coordinates" in item.lower() for item in adapted["contract_warnings"])

    service = make_service()
    service.tasks = TaskRepository({})
    service.tasks.save_sanitation_plan("TASK-100", plan_json)
    result = service.verify("TASK-100", VerificationRequest(submission_id="SUB-PASS"))
    assert result["verification_status"] == "INCONCLUSIVE"
    assert any("no task checklist" in item.lower() for item in result["remarks"])


def test_sanitation_checklist_missing_requirement_id_or_mandatory_flag_is_not_inferred():
    plan_json = {
        "incident_id": "INC-104", "planning_status": "PRELIMINARY_PLAN",
        "task_checklist": [{"task_id": "TASK-02", "sequence": 2,
                            "description": "Collect overflowing waste",
                            "depends_on": ["TASK-01"], "required_resources": ["WASTE_COLLECTION_TOOLS"],
                            "completion_criteria": ["Overflowing waste has been collected"],
                            "status": "NOT_STARTED"}],
    }
    adapted = adapt_sanitation_plan(plan_json, task_id="TASK-100",
                                    authoritative_site={"latitude": 28.6139, "longitude": 77.209,
                                                        "tolerance_m": 150})
    assert adapted["requirements"] == []
    message = " ".join(adapted["contract_warnings"])
    assert "requirement_id" in message
    assert "mandatory flag" in message


def test_invalid_stored_evidence_contract_cannot_claim_storage_without_reference():
    with pytest.raises(ValidationError, match="storage_key"):
        EvidenceRecord.model_validate({"evidence_id": "EVD-501", "task_id": "TASK-104",
                                       "evidence_type": "BEFORE", "upload_status": "STORED"})


def test_contract_examples_from_dispatch_duplicate_geolocation_incident_and_supervisor_specs():
    dispatch = DispatchAssignmentRequest.model_validate({
        "task_id": "TASK-104", "incident_id": "INC-104", "required_workers": 2,
        "required_skills": ["WASTE_COLLECTION"],
        "location": {"latitude": 22.7196, "longitude": 75.8577},
        "required_resources": ["WASTE_COLLECTION_EQUIPMENT"],
        "estimated_task_duration_minutes": 45, "priority": "MEDIUM",
    })
    duplicate = DuplicateDetectionRequest.model_validate({
        "complaint_id": "INC-127", "description": "Garbage is spilling out of the bin at the entrance",
        "category": "WASTE_OVERFLOW",
        "location": {"facility_id": "SITE-01", "location_id": "MAIN_GATE",
                     "latitude": 23.2599, "longitude": 77.4126},
        "reported_at": "2026-10-12T09:05:00+05:30", "image_hash": "a1b2c3d4",
    })
    geo = GeolocationRequest.model_validate({
        "description": "The public toilet is overflowing",
        "reported_location": {"latitude": 23.25, "longitude": 77.4, "source": "USER_SELECTED_PIN"},
        "device_location": {"latitude": 23.2503, "longitude": 77.4002, "accuracy_meters": 15,
                            "observed_at": "2026-10-12T07:10:00Z", "source": "DEVICE_GEOLOCATION"},
        "media_ids": ["media_123"],
    })
    intelligence = IncidentIntelligenceRequest.model_validate({
        "request_id": "REQ-104", "complaint_text": "Overflowing waste near the gate",
        "selected_incident_location": {"latitude": 23.25, "longitude": 77.4},
        "device_location": {"latitude": 23.2503, "longitude": 77.4002, "accuracy_meters": 15,
                            "observed_at": "2026-10-12T07:10:00Z"},
        "image_refs": [], "image_exif_results": [], "voice_transcript": None,
        "location_check": {"status": "CONSISTENT", "distance_meters": 39.2,
                           "reason_codes": ["WITHIN_CONFIGURED_RADIUS"], "requires_human_review": False},
        "submitted_at": "2026-10-12T07:10:01Z", "taxonomy_version": "taxonomy-v1",
    })
    supervisor = SupervisorEvaluationRequest.model_validate({
        "incident_id": "INC-104", "description": "Dustbin overflow at main gate",
        "category": "WASTE_OVERFLOW", "location": {"site_id": "SITE-01", "zone": "MAIN_GATE"},
        "severity_indicators": {"walking_path_obstructed": True, "immediate_safety_risk": None},
        "evidence_complete": True,
    })
    assert (dispatch.task_id, duplicate.complaint_id, geo.device_location.accuracy_meters) == (
        "TASK-104", "INC-127", 15,
    )
    assert intelligence.location_check.status.value == "CONSISTENT"
    assert supervisor.severity_indicators.immediate_safety_risk is None
    assert LocationEvent.model_validate({
        "location_event_id": "LOC-902", "task_id": "TASK-104", "event_type": "COMPLETION",
        "latitude": 22.7196, "longitude": 75.8577, "accuracy_meters": None,
        "capture_status": "CAPTURED",
    }).accuracy_meters is None
    assert CONTRACT_VERSION == "1.1"


def test_verification_response_has_contract_version(make_service):
    result = make_service().verify("TASK-100", VerificationRequest(submission_id="SUB-PASS"))
    assert result["contract_version"] == CONTRACT_VERSION
    assert VerificationRequestV1.model_validate({"submission_id": "SUB-PASS"}).contract_version == CONTRACT_VERSION
    assert Requirement.model_validate({"requirement_id": "R-1", "label": "Clear path", "mandatory": True}).mandatory
    response_contract = VerificationResponseV1.model_validate({
        "verification_id": "VER-1", "task_id": "TASK-1", "submission_id": "SUB-1",
        "verification_status": "PASS", "verification_score": 100, "score_status": "AVAILABLE", "remarks": [],
    })
    assert response_contract.contract_version == CONTRACT_VERSION


def test_field_worker_contract_flows_through_verification_service(make_service, tmp_path):
    import cv2
    import numpy as np

    service = make_service()
    service.submissions.storage_root = tmp_path
    storage_dir = tmp_path / "TASK-100"
    storage_dir.mkdir()
    for filename, seed in (("before.jpg", 11), ("after.jpg", 22)):
        image = np.random.default_rng(seed).integers(0, 256, (480, 640, 3), dtype=np.uint8)
        ok, encoded = cv2.imencode(".jpg", image)
        assert ok
        (storage_dir / filename).write_bytes(encoded.tobytes())
    service.submissions.save_evidence_record({
        "evidence_id": "EVD-BEFORE", "task_id": "TASK-100", "evidence_type": "BEFORE",
        "upload_status": "STORED", "storage_key": "TASK-100/before.jpg",
    })
    service.submissions.save_evidence_record({
        "evidence_id": "EVD-AFTER", "task_id": "TASK-100", "evidence_type": "AFTER",
        "upload_status": "STORED", "storage_key": "TASK-100/after.jpg",
    })
    service.submissions.save_location_event({
        "location_event_id": "LOC-COMPLETE", "task_id": "TASK-100", "event_type": "COMPLETION",
        "latitude": 28.614, "longitude": 77.209, "accuracy_meters": 10, "capture_status": "CAPTURED",
        "captured_at_device": "2026-10-12T10:00:00Z", "received_at_server": "2026-10-12T10:00:01Z",
    })

    class FixedVision:
        provider = "mock"
        model_version = "mock-v1"
        prompt_version = "prompt-v1"
        unavailable_reason = None

        def analyze(self, submission, evidence):
            from app.schemas.visual_findings import VisualFindings
            return VisualFindings.model_validate({
                "before_observations": {"scattered_waste": "PRESENT", "path_obstructed": "PRESENT", "overflow": "PRESENT"},
                "after_observations": {"scattered_waste": "ABSENT", "path_obstructed": "ABSENT", "overflow": "ABSENT"},
                "visual_change": "IMPROVED", "limitations": [], "confidence": 100,
            })

    service.vision = FixedVision()
    from types import SimpleNamespace
    service.image_alignment.align_pair = lambda *_: SimpleNamespace(
        status="ALIGNED", confidence=100, before_image=None, before_mime=None,
        aligned_after=None, after_mime=None, as_dict=lambda: {"status": "ALIGNED", "confidence": 100},
    )
    completion = FieldWorkerCompletion.model_validate({
        "task_id": "TASK-100", "submission_id": "SUB-CONTRACT", "checklist_completed": ["STEP-01", "STEP-02", "STEP-03"],
        "before_evidence_ids": ["EVD-BEFORE"], "after_evidence_ids": ["EVD-AFTER"],
        "completion_location_event_id": "LOC-COMPLETE",
    })
    result = service.verify("TASK-100", VerificationRequest(field_worker_completion=completion))
    assert result["verification_status"] == "PASS"
    assert result["evidence_refs"] == ["EVD-BEFORE", "EVD-AFTER"]
    assert result["contract_version"] == CONTRACT_VERSION


def test_sqlite_task_and_evidence_repositories_round_trip():
    with tempfile.TemporaryDirectory(prefix=".tmp-repositories-", dir=".") as temp_dir:
        db_path = Path(temp_dir) / "agent-repositories.sqlite"
        tasks = SQLiteTaskRepository(db_path)
        evidence = SQLiteEvidenceRepository(db_path)
        tasks.initialize()
        evidence.initialize()
        tasks.save("TASK-100", {"task_id": "TASK-100", "site": {"latitude": 1, "longitude": 2}, "requirements": []})
        tasks.save_sanitation_plan("TASK-PLAN", {
            "incident_id": "INC-1", "planning_status": "PRELIMINARY_PLAN", "task_checklist": [],
        })
        evidence.save("SUB-1", {"task_id": "TASK-100", "evidence": [], "location": None})
        evidence.save_evidence_record({"evidence_id": "E-1", "task_id": "TASK-100", "evidence_type": "BEFORE"})
        evidence.save_location_event({"location_event_id": "L-1", "task_id": "TASK-100", "event_type": "ARRIVAL"})

        assert tasks.get("TASK-100")["site"]["latitude"] == 1
        assert "contract_warnings" in tasks.get("TASK-PLAN")
        assert evidence.get("SUB-1")["task_id"] == "TASK-100"
        assert evidence.get_evidence_records(["E-1"])[0]["task_id"] == "TASK-100"
        assert evidence.get_location_events(["L-1"])[0]["location_event_id"] == "L-1"


@pytest.mark.parametrize(("target", "event", "expected"), [
    ({"latitude": 10, "longitude": 20}, {"latitude": 10, "longitude": 20, "accuracy_m": 5, "timestamp_valid": True}, "CONSISTENT"),
    ({"latitude": 10, "longitude": 20}, {"latitude": 11, "longitude": 21, "accuracy_m": 5, "timestamp_valid": True}, "MISMATCH"),
])
def test_shared_location_check_consistent_and_mismatch(target, event, expected):
    assert check_location(target=target, evidence=event, max_accuracy_m=20, tolerance_m=100)["status"] == expected


def test_shared_location_check_not_checked_missing_inconclusive_and_review_conflict():
    with pytest.raises(TypeError, match="max_accuracy_m"):
        check_location(target=None, evidence=None)
    assert check_location(target=None, evidence=None, max_accuracy_m=100)["status"] == "NOT_CHECKED"
    assert check_location(target={"latitude": 10, "longitude": 20}, evidence=None,
                          max_accuracy_m=100, tolerance_m=100)["status"] == "INCONCLUSIVE"
    assert combine_location_checks("CONSISTENT", "MISMATCH").value == "REVIEW_REQUIRED"


@pytest.mark.parametrize("event", [
    {"latitude": 10, "longitude": 20, "accuracy_m": 50, "timestamp_valid": True},
    {"latitude": "bad", "longitude": 20, "accuracy_m": 1, "timestamp_valid": True},
])
def test_shared_location_check_invalid_or_inaccurate_is_inconclusive(event):
    assert check_location(target={"latitude": 10, "longitude": 20}, evidence=event,
                          max_accuracy_m=20, tolerance_m=100)["status"] == "INCONCLUSIVE"
