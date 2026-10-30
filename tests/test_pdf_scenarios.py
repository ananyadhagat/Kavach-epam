from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
import tempfile
from time import sleep

import pytest
from pydantic import ValidationError

from app.repositories.evidence_repository import EvidenceRepository
from app.repositories.task_repository import TaskRepository
from app.repositories.verification_repository import MemoryVerificationRepository
from app.schemas import VerificationRequest, VisualFindings
from app.services.verification_service import VerificationService, UnknownSubmission
from app.services.vision_model_service import MockVisionAnalyzer
from app.validators.evidence_validator import EvidenceTaskMismatch


def run(service, submission_id="SUB-PASS"):
    return service.verify("TASK-100", VerificationRequest(submission_id=submission_id))


def test_pdf_01_clear_improvement_is_supported(make_service):
    result = run(make_service())
    assert result["verification_status"] == "PASS"
    assert result["image_findings"]["visual_change"] == "IMPROVED"


def test_pdf_02_definite_mandatory_issue_and_claimed_completion_fail(make_service):
    result = run(make_service(), "SUB-FAIL")
    assert result["verification_status"] == "FAIL"
    assert result["image_findings"]["visual_change"] == "IMPROVED"
    assert result["plan_compliance_findings"][0]["evidence_finding"] == "CONTRADICTED"
    failed = result["plan_compliance_findings"][0]
    assert "mandatory requirement" in result["remarks"][0].lower()
    assert failed["label"] in result["remarks"][0]
    assert failed["requirement_id"] in result["remarks"][0]
    assert failed["requirement_id"] in " ".join(result["remarks"])
    assert all(evidence_id in " ".join(result["remarks"]) for evidence_id in failed["evidence_ids"])
    assert failed["reason"] in " ".join(result["remarks"])
    assert any("informational" in item.lower() and "did not determine the outcome" in item.lower()
               for item in result["remarks"])


def test_mandatory_contradiction_with_blur_still_requires_manual_review(make_service, submissions):
    submissions["SUB-FAIL"]["mock_visual"]["limitations"] = ["After image is blurry"]
    result = run(make_service(), "SUB-FAIL")
    assert result["verification_status"] == "MANUAL_REVIEW"


def test_pdf_03_blurry_or_obstructed_image_requires_manual_review(make_service, submissions):
    submissions["SUB-PASS"]["mock_visual"]["limitations"] = ["After image is blurry and partly obstructed"]
    assert run(make_service())["verification_status"] == "MANUAL_REVIEW"


def test_pdf_04_gps_match_supports_location_only(make_service):
    result = run(make_service())
    assert result["location_finding"]["status"] == "CONSISTENT"
    assert result["verification_status"] == "PASS"
    assert "location" not in result["image_findings"]


def test_pdf_05_required_gps_unavailable_is_inconclusive(make_service, submissions):
    submissions["SUB-PASS"]["location"] = None
    result = run(make_service())
    assert result["verification_status"] == "INCONCLUSIVE"
    assert result["location_finding"]["status"] == "UNAVAILABLE"


def test_pdf_06_evidence_from_another_task_is_rejected_with_specific_reason(make_service, submissions):
    submissions["SUB-PASS"]["evidence"][1]["task_id"] = "TASK-OTHER"
    service = make_service()
    with pytest.raises(EvidenceTaskMismatch, match="belongs to another task"):
        run(service)


def test_pdf_07_malformed_vision_output_is_inconclusive(make_service, submissions):
    submissions["SUB-PASS"]["mock_visual"]["visual_change"] = "PARTIAL"
    result = run(make_service())
    assert result["verification_status"] == "INCONCLUSIVE"
    assert "unavailable or malformed" in " ".join(result["remarks"])


def test_pdf_08_mandatory_failure_overrides_high_score(make_service):
    service = make_service()
    visual = VisualFindings.model_validate({
        "before_observations": {"overflow": "PRESENT"},
        "after_observations": {"overflow": "ABSENT", "scattered_waste": "ABSENT", "path_obstructed": "ABSENT"},
        "visual_change": "IMPROVED", "limitations": [], "confidence": 100.0,
    })
    submission = {
        "task_id": "TASK-100",
        "evidence": [
            {"evidence_id": "B", "type": "BEFORE_IMAGE", "status": "READY", "task_id": "TASK-100"},
            {"evidence_id": "A", "type": "AFTER_IMAGE", "status": "READY", "task_id": "TASK-100"},
        ],
        "location": {"latitude": 28.614, "longitude": 77.209, "accuracy_m": 5, "timestamp_valid": True},
        "checklist": {"STEP-01": True, "STEP-02": True, "STEP-03": False},
        "mock_visual": visual.model_dump(mode="json"),
    }
    service.submissions = EvidenceRepository({"SUB-HARD-FAIL": submission})
    result = run(service, "SUB-HARD-FAIL")
    assert result["verification_score"] >= 75.0
    assert result["verification_status"] == "FAIL"


def test_pdf_09_gps_image_contradiction_and_clean_photos_require_review(make_service, submissions):
    submissions["SUB-PASS"]["location"]["latitude"] = 0
    submissions["SUB-PASS"]["location"]["longitude"] = 0
    result = run(make_service())
    assert result["location_finding"]["status"] == "MISMATCH"
    assert result["verification_status"] == "MANUAL_REVIEW"


def test_gps_match_with_clear_photo_contradiction_fails(make_service):
    result = run(make_service(), "SUB-FAIL")
    assert result["location_finding"]["status"] == "CONSISTENT"
    assert result["verification_status"] == "FAIL"


def test_pdf_10_repeated_submission_reuses_audit_record(make_service):
    service = make_service()
    first, second = run(service), run(service)
    assert first["verification_id"] == second["verification_id"]
    assert first["created_at"] == second["created_at"]


def test_concurrent_duplicate_requests_return_the_same_stored_record():
    from app.config import Settings
    from app.repositories.evidence_repository import SUBMISSIONS
    from app.repositories.task_repository import TASKS, TaskRepository
    from app.repositories.verification_repository import SQLiteVerificationRepository
    from app.services.verification_service import VerificationService
    from app.services.vision_model_service import MockVisionAnalyzer

    class SlowMockVision:
        provider = "mock"
        model_version = "mock-vision-1"
        prompt_version = "mock-prompt-1"
        unavailable_reason = None

        def analyze(self, submission, evidence):
            sleep(0.03)
            return MockVisionAnalyzer().analyze(submission, evidence)

    with tempfile.TemporaryDirectory(prefix=".tmp-audit-", dir=".") as temp_dir:
        audit = SQLiteVerificationRepository(f"{temp_dir}/concurrent-audit.sqlite")
        audit.initialize()
        service = VerificationService(
            TaskRepository(deepcopy(TASKS)), EvidenceRepository(deepcopy(SUBMISSIONS)), SlowMockVision(), audit,
            Settings(rule_version="concurrent-test", pass_threshold=75, require_gps=True),
        )
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(lambda _: run(service), range(8)))
        assert len({item["verification_id"] for item in results}) == 1
        stored = audit.get_existing("TASK-100", "SUB-PASS", "concurrent-test")
        assert all(item == stored for item in results)


def test_pdf_formula_example_scores_89_5():
    from app.services.score_calculator import calculate_score

    score, score_status, breakdown = calculate_score({
        "image_evidence": 90, "gps_consistency": 100, "plan_compliance": 80,
    })
    assert score == 89.5
    assert score_status == "AVAILABLE"
    assert breakdown["gps_consistency"] == 100


def test_score_decides_failure_when_all_mandatory_requirements_pass(make_service):
    result = run(make_service(threshold=101), "SUB-PASS")
    assert result["verification_status"] == "FAIL"
    assert result["failed_requirement_ids"] == []
    assert "SCORE_BELOW_THRESHOLD" in result["reason_codes"]
    score_remark = next(item for item in result["remarks"] if item.startswith("Weighted score"))
    assert "configured threshold" in score_remark
    assert "informational" not in score_remark


def test_demo_submissions_return_expected_reason_codes_and_contract_version(make_service):
    expected = {
        "SUB-PASS": ["QUALITY_NOT_CHECKED"],
        "SUB-FAIL": ["MANDATORY_REQUIREMENT_CONTRADICTED", "QUALITY_NOT_CHECKED"],
        "SUB-INCOMPLETE": [
            "MANDATORY_REQUIREMENT_NOT_CLAIMED", "EVIDENCE_MISSING", "ANALYSIS_UNAVAILABLE",
            "QUALITY_NOT_CHECKED",
        ],
    }
    for submission_id, codes in expected.items():
        result = run(make_service(), submission_id)
        assert result["contract_version"] == "1.1"
        assert result["reason_codes"] == codes
    assert run(make_service(), "SUB-FAIL")["failed_requirement_ids"] == ["STEP-01"]
    assert run(make_service(), "SUB-PASS")["failed_requirement_ids"] == []
    assert run(make_service(), "SUB-INCOMPLETE")["failed_requirement_ids"] == []
