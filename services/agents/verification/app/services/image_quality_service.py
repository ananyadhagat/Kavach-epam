"""Deterministic image quality descriptions; this module never makes decisions."""

from enum import Enum
from typing import Callable

import cv2
import numpy as np
from pydantic import BaseModel, ConfigDict


class QualityStatus(str, Enum):
    CHECKED = "CHECKED"
    NOT_CHECKED = "NOT_CHECKED"


class QualityReasonCode(str, Enum):
    IMAGE_BLURRY = "IMAGE_BLURRY"
    IMAGE_TOO_DARK = "IMAGE_TOO_DARK"
    IMAGE_TOO_BRIGHT = "IMAGE_TOO_BRIGHT"
    IMAGE_LOW_RESOLUTION = "IMAGE_LOW_RESOLUTION"
    BEFORE_AFTER_IDENTICAL = "BEFORE_AFTER_IDENTICAL"
    QUALITY_NOT_CHECKED = "QUALITY_NOT_CHECKED"


class ImageQualityResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence_id: str | None = None
    status: QualityStatus
    reason: str | None = None
    sharpness_score: float | None = None
    is_blurry: bool | None = None
    brightness_mean: float | None = None
    is_too_dark: bool | None = None
    is_too_bright: bool | None = None
    width: int | None = None
    height: int | None = None
    is_low_resolution: bool | None = None
    perceptual_hash: str | None = None


class ImageQualityAudit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    before: ImageQualityResult
    after: ImageQualityResult
    duplicate_hamming_distance: int | None = None
    before_after_identical: bool | None = None
    thresholds: dict[str, float | int]
    limitations: list[str]
    reason_codes: list[QualityReasonCode]


class ImageQualityService:
    """Compute blur, brightness, resolution and dHash from trusted image bytes.

    Thresholds are local demonstration defaults. They must be tuned and approved
    using representative field photos before production use.
    """

    def __init__(self, settings):
        self.blur_threshold = float(settings.quality_blur_threshold)
        self.min_brightness = float(settings.quality_min_brightness)
        self.max_brightness = float(settings.quality_max_brightness)
        self.min_width = int(settings.quality_min_width)
        self.min_height = int(settings.quality_min_height)
        self.duplicate_hash_distance = int(settings.quality_duplicate_hash_distance)
        if (self.blur_threshold < 0 or not 0 <= self.min_brightness < self.max_brightness <= 255
                or self.min_width < 1 or self.min_height < 1
                or not 0 <= self.duplicate_hash_distance <= 64):
            raise ValueError("Invalid image quality threshold configuration.")

    @property
    def thresholds(self) -> dict[str, float | int]:
        return {
            "QUALITY_BLUR_THRESHOLD": self.blur_threshold,
            "QUALITY_MIN_BRIGHTNESS": self.min_brightness,
            "QUALITY_MAX_BRIGHTNESS": self.max_brightness,
            "QUALITY_MIN_WIDTH": self.min_width,
            "QUALITY_MIN_HEIGHT": self.min_height,
            "QUALITY_DUPLICATE_HASH_DISTANCE": self.duplicate_hash_distance,
        }

    @staticmethod
    def _not_checked(evidence_id: str | None, reason: str) -> ImageQualityResult:
        return ImageQualityResult(evidence_id=evidence_id, status=QualityStatus.NOT_CHECKED, reason=reason)

    @staticmethod
    def _dhash(gray: np.ndarray) -> str:
        resized = cv2.resize(gray, (9, 8), interpolation=cv2.INTER_AREA)
        bits = resized[:, 1:] > resized[:, :-1]
        value = 0
        for bit in bits.flat:
            value = (value << 1) | int(bit)
        return f"{value:016x}"

    def inspect_bytes(self, image_bytes: bytes, *, evidence_id: str | None = None) -> ImageQualityResult:
        """Inspect bytes already loaded through the trusted evidence repository."""
        if not isinstance(image_bytes, bytes) or not image_bytes:
            return self._not_checked(evidence_id, "No image bytes are available.")
        try:
            encoded = np.frombuffer(image_bytes, dtype=np.uint8)
            image = cv2.imdecode(encoded, cv2.IMREAD_COLOR)
        except (cv2.error, ValueError, TypeError):
            image = None
        if image is None or image.size == 0:
            return self._not_checked(evidence_id, "Stored image is unreadable or undecodable.")

        height, width = image.shape[:2]
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        sharpness = float(cv2.Laplacian(gray, cv2.CV_64F).var())
        brightness = float(gray.mean())
        return ImageQualityResult(
            evidence_id=evidence_id,
            status=QualityStatus.CHECKED,
            sharpness_score=round(sharpness, 4),
            is_blurry=sharpness < self.blur_threshold,
            brightness_mean=round(brightness, 4),
            is_too_dark=brightness < self.min_brightness,
            is_too_bright=brightness > self.max_brightness,
            width=width,
            height=height,
            is_low_resolution=width < self.min_width or height < self.min_height,
            perceptual_hash=self._dhash(gray),
        )

    def inspect_pair(self, evidence: list[dict], image_loader: Callable) -> ImageQualityAudit:
        """Inspect ready BEFORE/AFTER records using the repository's trusted loader."""
        by_type: dict[str, dict] = {}
        duplicate_type = False
        for item in evidence:
            kind = item.get("type")
            if kind in ("BEFORE_IMAGE", "AFTER_IMAGE"):
                if kind in by_type:
                    duplicate_type = True
                by_type[kind] = item

        def inspect(kind: str) -> ImageQualityResult:
            record = by_type.get(kind)
            if record is None:
                return self._not_checked(None, "Evidence record is unavailable.")
            evidence_id = record.get("evidence_id")
            if duplicate_type:
                return self._not_checked(evidence_id, "Before/after evidence records are ambiguous.")
            if record.get("status") != "READY":
                return self._not_checked(evidence_id, "Evidence is not ready for image quality checks.")
            if not isinstance(record.get("storage_path"), str) or not record["storage_path"].strip():
                return self._not_checked(evidence_id, "No stored image bytes are available.")
            try:
                image_bytes, _mime_type = image_loader(record)
            except Exception:
                return self._not_checked(evidence_id, "Stored image is unreadable or undecodable.")
            return self.inspect_bytes(image_bytes, evidence_id=evidence_id)

        before = inspect("BEFORE_IMAGE")
        after = inspect("AFTER_IMAGE")
        distance = None
        duplicate = None
        limitations: list[str] = []
        codes: list[QualityReasonCode] = []

        for result in (before, after):
            if result.status == QualityStatus.NOT_CHECKED:
                if result.reason and "unreadable or undecodable" in result.reason.lower():
                    limitations.append("Image quality could not be checked because stored image is unreadable")
                codes.append(QualityReasonCode.QUALITY_NOT_CHECKED)
                continue
            if result.is_blurry:
                limitations.append("Image is blurry")
                codes.append(QualityReasonCode.IMAGE_BLURRY)
            if result.is_too_dark:
                limitations.append("Image is too dark")
                codes.append(QualityReasonCode.IMAGE_TOO_DARK)
            if result.is_too_bright:
                limitations.append("Image is too bright")
                codes.append(QualityReasonCode.IMAGE_TOO_BRIGHT)
            if result.is_low_resolution:
                limitations.append("Image resolution is too low")
                codes.append(QualityReasonCode.IMAGE_LOW_RESOLUTION)

        if before.status == QualityStatus.CHECKED and after.status == QualityStatus.CHECKED:
            before_hash = int(before.perceptual_hash or "0", 16)
            after_hash = int(after.perceptual_hash or "0", 16)
            distance = (before_hash ^ after_hash).bit_count()
            duplicate = distance <= self.duplicate_hash_distance
            if duplicate:
                limitations.append("Before and after images appear identical or near-identical")
                codes.append(QualityReasonCode.BEFORE_AFTER_IDENTICAL)

        # Stable order with no duplicate limitations or reason codes.
        return ImageQualityAudit(
            before=before,
            after=after,
            duplicate_hamming_distance=distance,
            before_after_identical=duplicate,
            thresholds=self.thresholds,
            limitations=list(dict.fromkeys(limitations)),
            reason_codes=list(dict.fromkeys(codes)),
        )
