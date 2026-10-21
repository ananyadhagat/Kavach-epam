import tempfile

import pytest
from pydantic import ValidationError

from app.schemas import VerificationRequest, VisualFindings
from app.services.gps_verification_service import verify_location


def run(service, submission_id="SUB-PASS"):
    return service.verify("TASK-100", VerificationRequest(submission_id=submission_id))


@pytest.mark.parametrize("latitude,longitude", [(91, 0), (-91, 0), (0, 181), (0, -181)])
def test_invalid_gps_ranges_are_inconclusive(make_service, submissions, latitude, longitude):
    submissions["SUB-PASS"]["location"].update(latitude=latitude, longitude=longitude)
    result = run(make_service())
    assert result["location_finding"]["status"] == "INCONCLUSIVE"
    assert result["verification_status"] == "INCONCLUSIVE"


def test_gps_accuracy_limit_comes_from_settings(make_service, submissions):
    submissions["SUB-PASS"]["location"]["accuracy_m"] = 30
    result = run(make_service(accuracy=20))
    assert result["location_finding"]["status"] == "INCONCLUSIVE"


def test_gps_tolerance_override_comes_from_settings(make_service):
    result = run(make_service(tolerance=1))
    assert result["location_finding"]["status"] == "MISMATCH"
    assert result["verification_status"] == "MANUAL_REVIEW"


def test_missing_gps_is_partial_when_gps_is_optional(make_service, submissions):
    submissions["SUB-PASS"]["location"] = None
    result = run(make_service(require_gps=False))
    assert result["verification_status"] == "PASS"
    assert result["score_status"] == "PARTIAL"
    assert result["verification_score"] == 100.0
    assert result["score_breakdown"]["gps_consistency"] is None
    assert any("excludes GPS" in item for item in result["remarks"])


def test_visual_schema_accepts_overflow_and_valid_change_labels():
    findings = VisualFindings.model_validate({
        "before_observations": {"overflow": "PRESENT"},
        "after_observations": {"overflow": "ABSENT"},
        "visual_change": "IMPROVED", "limitations": [],
    })
    assert findings.after_observations["overflow"].value == "ABSENT"


def test_visual_schema_rejects_partial_change_value():
    with pytest.raises(ValidationError):
        VisualFindings.model_validate({
            "before_observations": {"overflow": "PRESENT"},
            "after_observations": {"overflow": "ABSENT"},
            "visual_change": "PARTIAL", "limitations": [],
        })


def test_uncertain_visual_change_never_passes_with_clean_observations(make_service, submissions):
    submissions["SUB-PASS"]["mock_visual"]["visual_change"] = "UNCERTAIN"
    submissions["SUB-PASS"]["mock_visual"]["limitations"] = []
    result = run(make_service())
    assert result["image_findings"]["after_observations"] == {
        "scattered_waste": "ABSENT", "path_obstructed": "ABSENT", "overflow": "ABSENT",
    }
    assert result["verification_status"] == "MANUAL_REVIEW"


def test_plan_and_audit_keep_evidence_and_model_prompt_versions(make_service):
    result = run(make_service())
    assert result["plan_compliance_findings"][0]["evidence_ids"] == ["IMG-AFTER-1"]
    assert result["evidence_refs"] == ["IMG-BEFORE-1", "IMG-AFTER-1"]
    assert result["vision_model_version"] == "mock-vision-1"
    assert result["vision_prompt_version"] == "mock-prompt-1"


def test_gps_location_requires_valid_coordinates_and_positive_accuracy():
    finding = verify_location({"latitude": 0, "longitude": 0, "tolerance_m": 10},
                              {"latitude": 100, "longitude": 0, "accuracy_m": 1, "timestamp_valid": True},
                              max_accuracy_m=10, tolerance_m=10)
    assert finding["status"] == "INCONCLUSIVE"


@pytest.mark.parametrize("field,value", [
    ("latitude", 91), ("longitude", 181), ("tolerance_m", 0), ("tolerance_m", -1),
])
def test_invalid_server_site_policy_is_inconclusive(make_service, field, value):
    service = make_service()
    service.tasks.tasks["TASK-100"]["site"][field] = value
    result = run(service)
    assert result["location_finding"]["status"] == "INCONCLUSIVE"
    assert result["verification_status"] == "INCONCLUSIVE"
    assert "site" in " ".join(result["location_finding"]["reasons"]).lower()


def test_stale_sqlite_contract_response_is_refreshed_without_http_500(make_service):
    from app.repositories.verification_repository import SQLiteVerificationRepository

    service = make_service()
    with tempfile.TemporaryDirectory(prefix=".tmp-contract-upgrade-", dir=".") as temp_dir:
        audit = SQLiteVerificationRepository(f"{temp_dir}/audit.sqlite")
        audit.initialize()
        audit.save({
            "verification_id": "VER-OLD-1.0", "task_id": "TASK-100", "submission_id": "SUB-PASS",
            "rule_version": service.settings.rule_version, "created_at": "2026-01-01T00:00:00Z",
            "contract_version": "1.0",
        })
        service.audit = audit
        result = run(service)
        assert result["contract_version"] == "1.1"
        assert result["reason_codes"] == ["QUALITY_NOT_CHECKED"]
        assert result["failed_requirement_ids"] == []
        assert audit.get_existing("TASK-100", "SUB-PASS", service.settings.rule_version) == result
