from copy import deepcopy

import pytest

from app.config import Settings
from app.repositories.evidence_repository import SUBMISSIONS, EvidenceRepository
from app.repositories.task_repository import TASKS, TaskRepository
from app.repositories.verification_repository import MemoryVerificationRepository
from app.services.verification_service import VerificationService
from app.services.vision_model_service import MockVisionAnalyzer


@pytest.fixture
def submissions():
    return deepcopy(SUBMISSIONS)


@pytest.fixture
def make_service(submissions):
    def factory(*, require_gps=True, threshold=75, tolerance=None, accuracy=100, vision=None,
                quality_blur_threshold=100, quality_min_brightness=35, quality_max_brightness=225,
                quality_min_width=640, quality_min_height=480, quality_duplicate_hash_distance=5,
                review_confidence_threshold=80):
        settings = Settings(rule_version="test-1", prompt_version="test-prompt", vision_model_version="mock-test",
                            pass_threshold=threshold, require_gps=require_gps,
                            gps_max_accuracy_m=accuracy, gps_tolerance_m=tolerance, db_path=":memory:",
                            quality_blur_threshold=quality_blur_threshold,
                            quality_min_brightness=quality_min_brightness,
                            quality_max_brightness=quality_max_brightness,
                            quality_min_width=quality_min_width, quality_min_height=quality_min_height,
                            quality_duplicate_hash_distance=quality_duplicate_hash_distance,
                            verification_confidence_threshold=review_confidence_threshold)
        return VerificationService(TaskRepository(deepcopy(TASKS)), EvidenceRepository(submissions),
                                   vision or MockVisionAnalyzer(), MemoryVerificationRepository(), settings)
    return factory
