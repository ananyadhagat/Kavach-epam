from io import BytesIO

import cv2
import numpy as np

from app.services.image_alignment_service import ImageAlignmentService


def encode_png(image):
    ok, encoded = cv2.imencode(".png", image)
    assert ok
    return encoded.tobytes()


def evidence_pair():
    return [
        {"evidence_id": "before", "type": "BEFORE_IMAGE", "status": "READY", "task_id": "TASK-100"},
        {"evidence_id": "after", "type": "AFTER_IMAGE", "status": "READY", "task_id": "TASK-100"},
    ]


def test_same_scene_translation_is_registered_and_encoded():
    rng = np.random.default_rng(472)
    before = rng.integers(0, 256, (480, 640, 3), dtype=np.uint8)
    transform = np.float32([[1, 0, 12], [0, 1, -8]])
    after = cv2.warpAffine(before, transform, (640, 480))
    images = {"BEFORE_IMAGE": encode_png(before), "AFTER_IMAGE": encode_png(after)}

    result = ImageAlignmentService().align_pair(
        evidence_pair(), lambda item: (images[item["type"]], "image/png"),
    )

    assert result.status == "ALIGNED"
    assert result.confidence >= 80
    assert result.good_matches >= result.inliers >= 8
    assert result.inlier_ratio is not None
    assert result.before_mime == result.after_mime == "image/jpeg"
    assert result.aligned_after and result.before_image
    assert "aligned_after" not in result.as_dict()
    assert "before_image" not in result.as_dict()
    aligned = cv2.imdecode(np.frombuffer(result.aligned_after, dtype=np.uint8), cv2.IMREAD_COLOR)
    assert aligned.shape[:2] == (480, 640)


def test_blank_images_are_marked_low_confidence_without_crashing():
    blank = encode_png(np.zeros((200, 300, 3), dtype=np.uint8))
    result = ImageAlignmentService().align_pair(evidence_pair(), lambda _: (blank, "image/png"))
    assert result.status == "LOW_CONFIDENCE"
    assert result.confidence is not None and result.confidence < 80
    assert result.reason


def test_missing_pair_is_not_fabricated_as_aligned():
    result = ImageAlignmentService().align_pair([], lambda _: (_ for _ in ()).throw(AssertionError()))
    assert result.status == "NOT_CHECKED"
    assert result.confidence is None
    assert result.as_dict()["reason"]
