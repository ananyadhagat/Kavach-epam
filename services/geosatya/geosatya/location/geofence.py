"""The worker geofence rule. Pure and deterministic: no database, no HTTP,
no AI. The browser's distance is never used; everything is recomputed here.

Outcomes
    PASS             inside the radius with usable accuracy, no conflicts
    FAIL             clearly outside the radius (even allowing for GPS error)
    REVIEW_REQUIRED  inconclusive or conflicting: weak accuracy, boundary,
                     photo/device/incident disagree, unverified photo place,
                     duplicate photo, simulated location
    NOT_CHECKED      no usable location, so nothing could be verified

The geofence is a business rule, not a promise that GPS is that precise.
A PASS means "reported location is consistent with the incident", never
proof of presence, and never proof the photo shows the right object.
"""

from __future__ import annotations

from dataclasses import dataclass

from geosatya.location.coordinates import haversine_m, is_number, is_valid_pair

OUTCOMES = ("PASS", "FAIL", "REVIEW_REQUIRED", "NOT_CHECKED")

REASON_TEXT = {
    "PERMISSION_DENIED": "location permission was denied",
    "POSITION_UNAVAILABLE": "the device could not work out its position",
    "TIMEOUT": "getting a GPS fix took too long",
    "UNSUPPORTED": "this browser or page cannot share location",
    "NOT_REQUESTED": "location was not requested",
}


@dataclass(frozen=True)
class Policy:
    radius_m: float
    max_accuracy_m: float
    exif_tolerance_m: float = 50.0
    simulated_can_pass: bool = False

    def __post_init__(self) -> None:
        for name in ("radius_m", "max_accuracy_m", "exif_tolerance_m"):
            value = getattr(self, name)
            if not is_number(value) or value <= 0:
                raise ValueError(f"{name} must be a positive finite number")


@dataclass(frozen=True)
class Fix:
    latitude: float
    longitude: float
    accuracy_m: float | None = None
    simulated: bool = False


def check_worker_location(
    *,
    target: tuple[float, float] | None,
    fix: Fix | None,
    unavailable_reason: str | None = None,
    exif: tuple[float, float] | None = None,
    photo_source: str = "CAMERA_LIVE",
    duplicate: bool = False,
    policy: Policy,
) -> dict:
    codes: list[str] = []
    out = {
        "outcome": "NOT_CHECKED", "message": "", "distance_m": None, "accuracy_m": None,
        "radius_m": policy.radius_m, "max_accuracy_m": policy.max_accuracy_m,
        "reason_codes": codes, "simulated": False,
        "exif_target_distance_m": None, "exif_device_distance_m": None,
    }

    def finish(outcome: str, message: str) -> dict:
        out["outcome"], out["message"] = outcome, message
        out["needs_review"] = outcome == "REVIEW_REQUIRED"
        return out

    if target is None or not is_valid_pair(*target):
        codes.append("NO_TARGET")
        return finish("NOT_CHECKED", "This incident has no valid location to compare against, so nothing could be checked.")
    if fix is None or not is_valid_pair(fix.latitude, fix.longitude):
        codes.append("LOCATION_UNAVAILABLE")
        if unavailable_reason:
            codes.append(unavailable_reason)
        why = REASON_TEXT.get(unavailable_reason or "", "no usable location was provided")
        return finish("NOT_CHECKED", f"Your location could not be checked ({why}). Fix location access and try again; nothing was verified.")

    distance = haversine_m(target[0], target[1], fix.latitude, fix.longitude)
    accuracy = fix.accuracy_m if is_number(fix.accuracy_m) and fix.accuracy_m > 0 else None
    out.update(distance_m=round(distance, 1), accuracy_m=accuracy, simulated=fix.simulated)
    radius = policy.radius_m

    # Clearly outside, giving the reading the benefit of its own uncertainty.
    margin = accuracy if accuracy is not None else policy.max_accuracy_m
    if distance - margin > radius:
        codes.append("OUTSIDE_RADIUS")
        return finish("FAIL", f"Worker location is outside the permitted radius ({distance:.0f} m away, limit {radius:g} m). "
                              "Move closer to the assigned incident location and try again.")

    review: list[str] = []
    if accuracy is None:
        review.append("ACCURACY_NOT_REPORTED")
    elif accuracy > policy.max_accuracy_m:
        review.append("POOR_GPS_ACCURACY")
    if distance > radius:
        review.append("BOUNDARY_UNCERTAIN")

    exif_ok = False
    if exif is not None and is_valid_pair(*exif):
        to_target = haversine_m(target[0], target[1], exif[0], exif[1])
        to_device = haversine_m(fix.latitude, fix.longitude, exif[0], exif[1])
        out.update(exif_target_distance_m=round(to_target, 1), exif_device_distance_m=round(to_device, 1))
        if to_target > radius + policy.exif_tolerance_m:
            review += ["EXIF_FAR_FROM_TARGET", "SOURCE_CONFLICT"]
        elif to_device > max(policy.exif_tolerance_m, accuracy or 0):
            review.append("SOURCE_CONFLICT")
        else:
            exif_ok = True
    # A file picked from the gallery says nothing about where it was taken:
    # the device location is where the worker is now, not where the photo is from.
    if photo_source == "GALLERY" and not exif_ok:
        review.append("PHOTO_LOCATION_UNVERIFIED")
    if duplicate:
        review.append("DUPLICATE_PHOTO")
    if fix.simulated:
        codes.append("SIMULATED_LOCATION")
        if not policy.simulated_can_pass:
            review.append("SIMULATED_LOCATION_NOT_ACCEPTED")

    codes.extend(c for c in review if c not in codes)
    if not review:
        codes.append("WITHIN_RADIUS")
        note = " (SIMULATED location, demo only)" if fix.simulated else ""
        return finish("PASS", f"Worker location is within the permitted radius ({distance:.0f} m, limit {radius:g} m) "
                              f"and the required completion evidence has been submitted{note}.")

    parts = []
    if "POOR_GPS_ACCURACY" in review:
        parts.append(f"GPS accuracy (±{accuracy:.0f} m) is too weak to confirm you are at the spot.")
    if "ACCURACY_NOT_REPORTED" in review:
        parts.append("The device did not report GPS accuracy.")
    if "BOUNDARY_UNCERTAIN" in review and "POOR_GPS_ACCURACY" not in review:
        parts.append("You are at the edge of the permitted radius and GPS accuracy can't place you inside it.")
    if "SOURCE_CONFLICT" in review:
        parts.append("The photo's own location data doesn't match your location or the incident.")
    if "PHOTO_LOCATION_UNVERIFIED" in review:
        parts.append("Location checks passed, but the submitted photograph could not be confidently associated "
                     "with the assigned incident (it was not taken in the app, so where it was taken is unknown).")
    if "DUPLICATE_PHOTO" in review:
        parts.append("This exact photo has been submitted before.")
    if "SIMULATED_LOCATION_NOT_ACCEPTED" in review:
        parts.append("The location was simulated, which can't verify presence.")
    return finish("REVIEW_REQUIRED", " ".join(parts) + " A supervisor will review it.")
