import cv2
import numpy as np
import pytest

from app.config import Settings
from app.schemas.verification_request import VerificationRequest
from app.services.image_quality_service import ImageQualityService, QualityStatus
from app.services.verification_service import VerificationService
from app.services.vision_model_service import MockVisionAnalyzer


def encode_png(image):
    success, encoded = cv2.imencode(".png", image)
    assert success
    return encoded.tobytes()


def sharp_image(seed=21):
    return np.random.default_rng(seed).integers(0, 256, (480, 640, 3), dtype=np.uint8)


def quality_service(**overrides):
    return ImageQualityService(Settings(**overrides))


def prepare_service(make_service, tmp_path, submission_id, before, after):
    service = make_service()
    service.submissions.storage_root = tmp_path
    records = service.submissions.submissions[submission_id]["evidence"]
    for record, image in zip(records, (before, after)):
        name = record["evidence_id"] + ".png"
        (tmp_path / name).write_bytes(encode_png(image))
        record["storage_path"] = name
    return service


def test_sharp_well_lit_synthetic_image_is_accepted_as_quality_checked():
    result = quality_service().inspect_bytes(encode_png(sharp_image()), evidence_id="E1")
    assert result.status == QualityStatus.CHECKED
    assert result.sharpness_score > 100
    assert result.is_blurry is False
    assert 35 <= result.brightness_mean <= 225
    assert result.is_too_dark is False
    assert result.is_too_bright is False
    assert (result.width, result.height) == (640, 480)
    assert result.is_low_resolution is False
    assert result.perceptual_hash


def test_blurred_photo_adds_limitation_reason_and_routes_to_manual_review(make_service, tmp_path):
    crisp = sharp_image()
    blurred = cv2.GaussianBlur(crisp, (31, 31), 0)
    service = prepare_service(make_service, tmp_path, "SUB-PASS", crisp, blurred)
    result = service.verify("TASK-100", VerificationRequest(submission_id="SUB-PASS"))
    assert result["verification_status"] == "MANUAL_REVIEW"
    assert "IMAGE_BLURRY" in result["reason_codes"]
    assert "Image is blurry" in result["image_findings"]["limitations"]
    assert result["image_quality_audit"]["after"]["is_blurry"] is True


@pytest.mark.parametrize(("color", "expected_field", "expected_code"), [
    ((0, 0, 0), "is_too_dark", "IMAGE_TOO_DARK"),
    ((255, 255, 255), "is_too_bright", "IMAGE_TOO_BRIGHT"),
])
def test_nearly_black_and_white_images_are_flagged(color, expected_field, expected_code):
    image = np.full((480, 640, 3), color, dtype=np.uint8)
    result = quality_service().inspect_bytes(encode_png(image))
    assert result.status == QualityStatus.CHECKED
    assert getattr(result, expected_field) is True


@pytest.mark.parametrize(("image", "expected_code", "limitation"), [
    (np.zeros((480, 640, 3), dtype=np.uint8), "IMAGE_TOO_DARK", "Image is too dark"),
    (np.full((480, 640, 3), 255, dtype=np.uint8), "IMAGE_TOO_BRIGHT", "Image is too bright"),
    (np.random.default_rng(6).integers(0, 256, (240, 320, 3), dtype=np.uint8),
     "IMAGE_LOW_RESOLUTION", "Image resolution is too low"),
])
def test_quality_issues_map_to_limitations_and_reason_codes(make_service, tmp_path, image,
                                                             expected_code, limitation):
    service = prepare_service(make_service, tmp_path, "SUB-PASS", sharp_image(), image)
    result = service.verify("TASK-100", VerificationRequest(submission_id="SUB-PASS"))
    assert result["verification_status"] == "MANUAL_REVIEW"
    assert expected_code in result["reason_codes"]
    assert limitation in result["image_findings"]["limitations"]


def test_tiny_photo_is_low_resolution():
    result = quality_service().inspect_bytes(encode_png(np.full((40, 50, 3), 128, dtype=np.uint8)))
    assert result.is_low_resolution is True


def test_identical_before_after_images_create_review_signal(make_service, tmp_path):
    image = sharp_image()
    service = prepare_service(make_service, tmp_path, "SUB-PASS", image, image.copy())
    result = service.verify("TASK-100", VerificationRequest(submission_id="SUB-PASS"))
    assert result["image_quality_audit"]["before_after_identical"] is True
    assert "BEFORE_AFTER_IDENTICAL" in result["reason_codes"]
    assert "Before and after images appear identical or near-identical" in result["image_findings"]["limitations"]
    assert result["verification_status"] == "MANUAL_REVIEW"


def test_clearly_different_images_do_not_create_duplicate_flag():
    analyzer = quality_service()
    image_before = np.zeros((480, 640, 3), dtype=np.uint8)
    image_after = image_before.copy()
    cv2.rectangle(image_after, (80, 60), (560, 420), (255, 255, 255), thickness=-1)
    before = analyzer.inspect_bytes(encode_png(image_before))
    after = analyzer.inspect_bytes(encode_png(image_after))
    distance = (int(before.perceptual_hash, 16) ^ int(after.perceptual_hash, 16)).bit_count()
    assert distance > analyzer.duplicate_hash_distance


def test_reencoded_jpeg_copy_is_detected_as_near_identical():
    image = np.full((480, 640, 3), 128, dtype=np.uint8)
    cv2.rectangle(image, (80, 70), (540, 410), (20, 20, 20), thickness=12)
    first_ok, first = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, 95])
    second_ok, second = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, 78])
    assert first_ok and second_ok
    analyzer = quality_service()
    before = analyzer.inspect_bytes(first.tobytes())
    after = analyzer.inspect_bytes(second.tobytes())
    distance = (int(before.perceptual_hash, 16) ^ int(after.perceptual_hash, 16)).bit_count()
    assert distance <= analyzer.duplicate_hash_distance


@pytest.mark.parametrize("data", [b"", b"this is not an image"])
def test_undecodable_or_empty_bytes_are_not_checked_without_fabricated_metrics(data):
    result = quality_service().inspect_bytes(data, evidence_id="E-BAD")
    assert result.status == QualityStatus.NOT_CHECKED
    assert result.reason
    assert result.sharpness_score is None
    assert result.brightness_mean is None
    assert result.width is None and result.height is None
    assert result.perceptual_hash is None


def test_unreadable_stored_image_is_not_checked_and_reported_as_limitation(make_service, tmp_path):
    service = prepare_service(make_service, tmp_path, "SUB-PASS", sharp_image(), sharp_image(22))
    after_record = service.submissions.submissions["SUB-PASS"]["evidence"][1]
    (tmp_path / after_record["storage_path"]).write_bytes(b"not an image")
    result = service.verify("TASK-100", VerificationRequest(submission_id="SUB-PASS"))
    assert result["image_quality_audit"]["after"]["status"] == "NOT_CHECKED"
    assert result["image_quality_audit"]["after"]["reason"]
    assert "QUALITY_NOT_CHECKED" in result["reason_codes"]
    assert any("unreadable" in item.lower() for item in result["image_findings"]["limitations"])
    assert result["verification_status"] == "MANUAL_REVIEW"


def test_mock_demo_has_not_checked_quality_without_changing_demo_outcomes(make_service):
    expected = {"SUB-PASS": "PASS", "SUB-FAIL": "FAIL", "SUB-INCOMPLETE": "INCONCLUSIVE"}
    for submission_id, status in expected.items():
        result = make_service().verify("TASK-100", VerificationRequest(submission_id=submission_id))
        assert result["verification_status"] == status
        assert "QUALITY_NOT_CHECKED" in result["reason_codes"]
        assert result["image_quality_audit"]["before"]["status"] == "NOT_CHECKED"
        assert result["image_quality_audit"]["after"]["status"] == "NOT_CHECKED"


def test_quality_threshold_override_changes_integrated_outcome(monkeypatch, make_service, tmp_path):
    monkeypatch.setenv("QUALITY_MIN_WIDTH", "1000")
    settings = Settings()
    service = prepare_service(make_service, tmp_path, "SUB-PASS", sharp_image(), sharp_image(22))
    # Rebuild the injected quality analyzer from environment-loaded configuration.
    service.image_quality = ImageQualityService(settings)
    assert settings.quality_min_width == 1000
    result = service.verify("TASK-100", VerificationRequest(submission_id="SUB-PASS"))
    assert result["verification_status"] == "MANUAL_REVIEW"
    assert "IMAGE_LOW_RESOLUTION" in result["reason_codes"]


def test_blur_does_not_override_existing_mandatory_failure_order(make_service, tmp_path):
    crisp = sharp_image()
    blurred = cv2.GaussianBlur(crisp, (31, 31), 0)
    service = prepare_service(make_service, tmp_path, "SUB-FAIL", crisp, blurred)
    result = service.verify("TASK-100", VerificationRequest(submission_id="SUB-FAIL"))
    # The unchanged decision engine checks limitations before mandatory contradiction.
    assert result["verification_status"] == "MANUAL_REVIEW"
    assert "MANDATORY_REQUIREMENT_CONTRADICTED" in result["reason_codes"]
    assert "IMAGE_BLURRY" in result["reason_codes"]


def test_quality_thresholds_used_are_persisted_without_image_bytes(make_service, tmp_path):
    image = sharp_image()
    service = prepare_service(make_service, tmp_path, "SUB-PASS", image, image.copy())
    result = service.verify("TASK-100", VerificationRequest(submission_id="SUB-PASS"))
    audit_json = str(result["image_quality_audit"])
    assert result["image_quality_audit"]["thresholds"]["QUALITY_BLUR_THRESHOLD"] == 100
    assert result["image_quality_audit"]["before"]["perceptual_hash"]
    assert "image/png" not in audit_json
    assert "storage_path" not in audit_json
    assert "b'" not in audit_json
