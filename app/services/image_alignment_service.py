"""Conservative ORB/RANSAC registration of stored before/after evidence.

The confidence value is a heuristic registration score, not a calibrated
probability. Tune it with labelled field images before operational use.
"""

from dataclasses import dataclass
from typing import Callable

import cv2
import numpy as np


@dataclass(frozen=True)
class ImageAlignmentResult:
    status: str
    confidence: float | None
    good_matches: int | None = None
    inliers: int | None = None
    inlier_ratio: float | None = None
    median_reprojection_error_px: float | None = None
    aligned_after: bytes | None = None
    before_image: bytes | None = None
    before_mime: str | None = None
    after_mime: str | None = None
    reason: str | None = None

    def as_dict(self) -> dict:
        """Return diagnostics only; never include image bytes in API/audit JSON."""
        return {
            "status": self.status,
            "confidence": self.confidence,
            "good_matches": self.good_matches,
            "inliers": self.inliers,
            "inlier_ratio": self.inlier_ratio,
            "median_reprojection_error_px": self.median_reprojection_error_px,
            "reason": self.reason,
        }


class ImageAlignmentService:
    """Align AFTER to BEFORE with ORB descriptors and a RANSAC homography."""

    def __init__(self, minimum_confidence: float = 80.0, max_dimension: int = 1600):
        self.minimum_confidence = float(minimum_confidence)
        self.max_dimension = int(max_dimension)
        if not 0 <= self.minimum_confidence <= 100 or self.max_dimension < 64:
            raise ValueError("Invalid image alignment configuration.")

    @staticmethod
    def _decode(data: bytes) -> np.ndarray | None:
        try:
            return cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)
        except (cv2.error, TypeError, ValueError):
            return None

    def _resize(self, image: np.ndarray) -> np.ndarray:
        height, width = image.shape[:2]
        scale = min(1.0, self.max_dimension / max(height, width))
        if scale == 1.0:
            return image
        return cv2.resize(image, (round(width * scale), round(height * scale)), interpolation=cv2.INTER_AREA)

    @staticmethod
    def _not_checked(reason: str) -> ImageAlignmentResult:
        return ImageAlignmentResult(status="NOT_CHECKED", confidence=None, reason=reason)

    @staticmethod
    def _low_confidence(reason: str, *, confidence: float = 0.0, **metrics) -> ImageAlignmentResult:
        return ImageAlignmentResult(
            status="LOW_CONFIDENCE", confidence=round(max(0.0, min(100.0, confidence)), 1),
            reason=reason, **metrics,
        )

    @staticmethod
    def _jpeg(image: np.ndarray) -> bytes | None:
        ok, encoded = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, 92])
        return encoded.tobytes() if ok else None

    def align_pair(self, evidence: list[dict], image_loader: Callable) -> ImageAlignmentResult:
        by_type: dict[str, dict] = {}
        for item in evidence:
            kind = item.get("type")
            if kind in ("BEFORE_IMAGE", "AFTER_IMAGE"):
                if kind in by_type:
                    return self._not_checked("Before/after evidence records are ambiguous.")
                by_type[kind] = item
        if set(by_type) != {"BEFORE_IMAGE", "AFTER_IMAGE"}:
            return self._not_checked("A ready before/after image pair is required for alignment.")
        if any(item.get("status") != "READY" for item in by_type.values()):
            return self._not_checked("Both images must be READY before alignment.")

        try:
            before_bytes, _ = image_loader(by_type["BEFORE_IMAGE"])
            after_bytes, _ = image_loader(by_type["AFTER_IMAGE"])
        except Exception:
            return self._not_checked("Stored before/after images could not be loaded for alignment.")
        before = self._decode(before_bytes)
        after = self._decode(after_bytes)
        if before is None or after is None or before.size == 0 or after.size == 0:
            return self._not_checked("Stored before/after images are not decodable for alignment.")

        try:
            before = self._resize(before)
            after = self._resize(after)
            before_gray = cv2.cvtColor(before, cv2.COLOR_BGR2GRAY)
            after_gray = cv2.cvtColor(after, cv2.COLOR_BGR2GRAY)
            detector = cv2.ORB_create(nfeatures=1800, fastThreshold=8)
            key_before, descriptors_before = detector.detectAndCompute(before_gray, None)
            key_after, descriptors_after = detector.detectAndCompute(after_gray, None)
            if descriptors_before is None or descriptors_after is None:
                return self._low_confidence(
                    "Not enough stable landmarks were found in both images.",
                )

            matcher = cv2.BFMatcher(cv2.NORM_HAMMING)
            candidates = matcher.knnMatch(descriptors_after, descriptors_before, k=2)
            good = [first for pair in candidates if len(pair) == 2
                    for first, second in [pair] if first.distance < 0.75 * second.distance]
            if len(good) < 8:
                confidence = min(79.9, len(good) / 8 * 45)
                return self._low_confidence(
                    "Too few matching landmarks to align the photo pair reliably.",
                    confidence=confidence, good_matches=len(good),
                )

            after_points = np.float32([key_after[m.queryIdx].pt for m in good]).reshape(-1, 1, 2)
            before_points = np.float32([key_before[m.trainIdx].pt for m in good]).reshape(-1, 1, 2)
            homography, mask = cv2.findHomography(after_points, before_points, cv2.RANSAC, 4.0)
            if homography is None or mask is None:
                return self._low_confidence(
                    "Landmark homography could not be estimated.", good_matches=len(good),
                )

            inlier_mask = mask.ravel().astype(bool)
            inliers = int(inlier_mask.sum())
            ratio = inliers / len(good)
            if inliers < 4:
                return self._low_confidence(
                    "Too few consistent landmarks remain after robust matching.",
                    confidence=min(79.9, ratio * 100), good_matches=len(good), inliers=inliers,
                    inlier_ratio=round(ratio, 4),
                )

            projected = cv2.perspectiveTransform(after_points[inlier_mask], homography)
            errors = np.linalg.norm(projected - before_points[inlier_mask], axis=2).reshape(-1)
            median_error = float(np.median(errors))
            confidence = round(min(
                100.0,
                min(len(good) / 30.0, 1.0) * 25.0
                + min(inliers / 20.0, 1.0) * 25.0
                + ratio * 35.0
                + max(0.0, 15.0 - min(median_error, 7.5) * 2.0),
            ), 1)
            metrics = {
                "good_matches": len(good), "inliers": inliers,
                "inlier_ratio": round(ratio, 4),
                "median_reprojection_error_px": round(median_error, 3),
            }
            if inliers < 8 or confidence < self.minimum_confidence:
                return self._low_confidence(
                    "Landmark alignment confidence is below the configured review threshold.",
                    confidence=confidence, **metrics,
                )

            aligned_after = cv2.warpPerspective(after, homography, (before.shape[1], before.shape[0]))
            encoded_before = self._jpeg(before)
            encoded_after = self._jpeg(aligned_after)
            if encoded_before is None or encoded_after is None:
                return self._low_confidence(
                    "Aligned image frames could not be encoded for semantic analysis.",
                    confidence=confidence, **metrics,
                )
            return ImageAlignmentResult(
                status="ALIGNED", confidence=confidence, **metrics,
                before_image=encoded_before, before_mime="image/jpeg",
                aligned_after=encoded_after, after_mime="image/jpeg",
            )
        except (cv2.error, ValueError, TypeError, IndexError):
            return self._low_confidence(
                "OpenCV could not safely align this before/after image pair.",
            )
