import os
from dataclasses import dataclass, field

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    rule_version: str = os.getenv("KAVACH_RULE_VERSION", "demo-0.2")
    prompt_version: str = os.getenv("VISION_PROMPT_VERSION", "vision-prompt-v1")
    vision_model_version: str = os.getenv("KAVACH_VISION_MODEL_VERSION", "mock-vision-1")
    vision_provider: str = os.getenv("VISION_PROVIDER", "mock").strip().lower()
    gemini_model: str | None = os.getenv("GEMINI_MODEL") or None
    vision_max_retries: int = int(os.getenv("VISION_MAX_RETRIES", "2"))
    vision_timeout_seconds: float = float(os.getenv("VISION_TIMEOUT_SECONDS", "30"))
    vision_max_image_mb: float = float(os.getenv("VISION_MAX_IMAGE_MB", "5"))
    evidence_root: str = os.getenv("KAVACH_EVIDENCE_ROOT", "stored_evidence")
    pass_threshold: float = float(os.getenv("KAVACH_PASS_THRESHOLD", "75"))
    require_gps: bool = os.getenv("KAVACH_REQUIRE_GPS", "true").lower() == "true"
    gps_max_accuracy_m: float = float(os.getenv("KAVACH_GPS_MAX_ACCURACY_M", "100"))
    gps_tolerance_m: float | None = (
        float(os.environ["KAVACH_GPS_TOLERANCE_M"])
        if os.getenv("KAVACH_GPS_TOLERANCE_M") else None
    )
    db_path: str = os.getenv("KAVACH_DB_PATH", "verification_audit.db")
    repository_provider: str = os.getenv("KAVACH_REPOSITORY_PROVIDER", "memory").strip().lower()
    quality_blur_threshold: float = field(default_factory=lambda: float(os.getenv("QUALITY_BLUR_THRESHOLD", "100")))
    quality_min_brightness: float = field(default_factory=lambda: float(os.getenv("QUALITY_MIN_BRIGHTNESS", "35")))
    quality_max_brightness: float = field(default_factory=lambda: float(os.getenv("QUALITY_MAX_BRIGHTNESS", "225")))
    quality_min_width: int = field(default_factory=lambda: int(os.getenv("QUALITY_MIN_WIDTH", "640")))
    quality_min_height: int = field(default_factory=lambda: int(os.getenv("QUALITY_MIN_HEIGHT", "480")))
    quality_duplicate_hash_distance: int = field(
        default_factory=lambda: int(os.getenv("QUALITY_DUPLICATE_HASH_DISTANCE", "5"))
    )


WEIGHTS = {"image_evidence": 0.45, "gps_consistency": 0.25, "plan_compliance": 0.30}
