"""Deterministic Location Verification Service.

Compares sources against a target and returns an explainable result with reason codes.
It never declares a complaint fake: a mismatch is a signal for review, and remote
reporting is legitimate. The LLM has no role here.
"""
from __future__ import annotations

from dataclasses import dataclass

from kavach.schemas.location import (
    Coordinates,
    DeviceLocation,
    ImageMetadataResult,
    ImageMetadataStatus,
    LocationCheckSummary,
    LocationSource,
    LocationStatus,
    ReasonCode,
    SourceComparison,
)
from kavach.services.location.distance import haversine_meters

RULE_VERSION = "loc-rules-1.0"


@dataclass(frozen=True)
class LocationRules:
    """Product settings, not universal GPS truths. Calibrate per site type with field tests."""
    radius_m: float = 100.0            # allowed distance from target
    max_accuracy_m: float = 150.0      # device accuracy worse than this -> point not usable
    source_conflict_m: float = 250.0   # device-vs-EXIF disagreement threshold


class LocationVerificationService:
    def __init__(self, rules: LocationRules | None = None):
        self.rules = rules or LocationRules()

    def _compare_device(self, device: DeviceLocation, target: Coordinates) -> SourceComparison:
        d = haversine_meters(device.latitude, device.longitude, target.latitude, target.longitude)
        acc = device.accuracy_meters
        base = dict(source=LocationSource.DEVICE_GEOLOCATION, distance_meters=round(d, 1), accuracy_meters=acc)
        if acc is not None and acc > self.rules.max_accuracy_m:
            return SourceComparison(**base, status=LocationStatus.INCONCLUSIVE,
                                    reason_codes=[ReasonCode.POOR_DEVICE_ACCURACY])
        if d <= self.rules.radius_m:
            return SourceComparison(**base, status=LocationStatus.CONSISTENT,
                                    reason_codes=[ReasonCode.WITHIN_CONFIGURED_RADIUS])
        if d > self.rules.radius_m + (acc or 0.0):
            return SourceComparison(**base, status=LocationStatus.MISMATCH,
                                    reason_codes=[ReasonCode.OUTSIDE_CONFIGURED_RADIUS,
                                                  ReasonCode.REMOTE_REPORT_POSSIBLE])
        return SourceComparison(**base, status=LocationStatus.INCONCLUSIVE,
                                reason_codes=[ReasonCode.WITHIN_ACCURACY_UNCERTAINTY])

    def _compare_exif(self, meta: ImageMetadataResult, target: Coordinates) -> SourceComparison:
        base = dict(source=LocationSource.IMAGE_EXIF, media_id=meta.media_id)
        if meta.status != ImageMetadataStatus.GPS_FOUND or meta.coordinates is None:
            return SourceComparison(**base, status=LocationStatus.INCONCLUSIVE,
                                    reason_codes=list(meta.reason_codes) or [ReasonCode.EXIF_GPS_MISSING])
        d = haversine_meters(meta.coordinates.latitude, meta.coordinates.longitude,
                             target.latitude, target.longitude)
        ok = d <= self.rules.radius_m
        return SourceComparison(
            **base, distance_meters=round(d, 1),
            status=LocationStatus.CONSISTENT if ok else LocationStatus.MISMATCH,
            reason_codes=[ReasonCode.WITHIN_CONFIGURED_RADIUS if ok else ReasonCode.OUTSIDE_CONFIGURED_RADIUS],
        )

    def verify(
        self,
        target: Coordinates | None,
        target_source: LocationSource | None,
        device: DeviceLocation | None,
        exif_results: list[ImageMetadataResult],
    ) -> LocationCheckSummary:
        def summary(status: LocationStatus, **kw) -> LocationCheckSummary:
            return LocationCheckSummary(status=status, target_source=target_source,
                                        rule_version=RULE_VERSION, **kw)

        if target is None:
            return summary(LocationStatus.NOT_CHECKED, reason_codes=[ReasonCode.NO_TARGET_COORDINATE])
        if device is None and not exif_results:
            return summary(LocationStatus.INCONCLUSIVE,
                           reason_codes=[ReasonCode.NO_COMPARISON_SOURCE, ReasonCode.DEVICE_LOCATION_UNAVAILABLE])

        comparisons: list[SourceComparison] = []
        reasons: list[ReasonCode] = []

        def add_reason(r: ReasonCode) -> None:
            if r not in reasons:
                reasons.append(r)

        if device is not None:
            comparisons.append(self._compare_device(device, target))
        else:
            add_reason(ReasonCode.DEVICE_LOCATION_UNAVAILABLE)
        comparisons.extend(self._compare_exif(m, target) for m in exif_results)
        for c in comparisons:
            for r in c.reason_codes:
                add_reason(r)

        # Device vs EXIF disagreement is preserved regardless of the target.
        # A device point with unusable accuracy cannot create a conflict (it is not a reliable point).
        requires_review = False
        device_usable = device is not None and (
            device.accuracy_meters is None or device.accuracy_meters <= self.rules.max_accuracy_m)
        if device_usable:
            for m in exif_results:
                if m.coordinates and haversine_meters(
                    device.latitude, device.longitude, m.coordinates.latitude, m.coordinates.longitude
                ) > self.rules.source_conflict_m:
                    add_reason(ReasonCode.SOURCE_CONFLICT)
                    requires_review = True
                    break

        statuses = {c.status for c in comparisons}
        if LocationStatus.CONSISTENT in statuses and LocationStatus.MISMATCH in statuses:
            final = LocationStatus.INCONCLUSIVE  # signals disagree: no winner
            add_reason(ReasonCode.SOURCE_CONFLICT)
            requires_review = True
        elif LocationStatus.MISMATCH in statuses:
            final = LocationStatus.MISMATCH
        elif LocationStatus.CONSISTENT in statuses:
            final = LocationStatus.CONSISTENT
        else:
            final = LocationStatus.INCONCLUSIVE

        distances = [c.distance_meters for c in comparisons if c.distance_meters is not None]
        return summary(
            final,
            distance_meters=min(distances) if distances else None,
            evidence_sources=list(dict.fromkeys(c.source for c in comparisons)),
            comparisons=comparisons,
            reason_codes=reasons,
            requires_human_review=requires_review,
        )
