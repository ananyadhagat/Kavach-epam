"""GeoSatya check of a citizen complaint (photo + automatic GPS).

The browser's coordinates are a claim, not proof. The server records them as
evidence and decides the status itself from what it can check:
- a photo exists and was taken with the in-app camera (not a gallery file);
- the phone's GPS fix exists, is LIVE (not simulated), is accurate enough
  (the GeoSatya accuracy limit) and was taken close to the photo moment;
- the fix is not older than the freshness window when it reaches the server,
  and not dated in the future;
- if the photo carries EXIF GPS, it is compared with the phone's fix
  (EXIF is optional: most phone browsers strip it).

Result: LOCATION_VERIFIED, or NEEDS_REVIEW with the reasons. Nothing is rejected
silently, and a weak check is never shown as verified.
"""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select

from geosatya.location.coordinates import haversine_m
from geosatya.models import EvidenceRow, MediaRow
from geosatya.services.common import get_limits
from geosatya.timeutil import as_utc, iso, utcnow

# A fix reaching the server later than this after it was measured is stale (slow uploads included).
MAX_FIX_AGE = timedelta(minutes=15)

REASONS = {
    "NO_PHOTO": "No photograph was received.",
    "PHOTO_NOT_FROM_CAMERA": "The photo did not come from the in-app camera.",
    "NO_DEVICE_GPS": "The phone did not share its GPS location.",
    "SIMULATED_LOCATION": "The location was simulated (development only), not real GPS.",
    "LOW_GPS_ACCURACY": "The GPS reading was not accurate enough.",
    "LOCATION_NOT_AT_PHOTO_TIME": "The GPS reading was not taken at the moment of the photo.",
    "STALE_LOCATION": "The GPS reading was too old when it reached the server.",
    "FUTURE_TIMESTAMP": "The GPS reading is dated in the future.",
    "PHOTO_GPS_CONFLICT": "The location stored inside the photo is far from the phone's GPS.",
}


def check_report(session, settings, incident) -> dict:
    limits = get_limits(session, settings)
    reasons: list[str] = []
    media = session.scalars(select(MediaRow).where(MediaRow.incident_id == incident.incident_id, MediaRow.role == "REPORT")
                            .order_by(MediaRow.received_at)).all()
    fix = session.scalar(select(EvidenceRow).where(EvidenceRow.incident_id == incident.incident_id, EvidenceRow.task_id.is_(None),
                                                   EvidenceRow.source_type == "DEVICE_GEOLOCATION").order_by(EvidenceRow.received_at))
    exif_rows = session.scalars(select(EvidenceRow).where(EvidenceRow.incident_id == incident.incident_id, EvidenceRow.task_id.is_(None),
                                                          EvidenceRow.source_type == "IMAGE_EXIF")).all()
    if not media:
        reasons.append("NO_PHOTO")
    elif not any(m.capture_source in ("CAMERA_LIVE", "CAMERA_INPUT") for m in media):
        reasons.append("PHOTO_NOT_FROM_CAMERA")
    photo = media[0] if media else None

    gps = None
    if fix is None or not fix.available:
        reasons.append("NO_DEVICE_GPS")
    else:
        gps = {"latitude": fix.latitude, "longitude": fix.longitude, "accuracy_m": fix.accuracy_m,
               "observed_at": iso(fix.observed_at) if fix.observed_at else None, "received_at": iso(fix.received_at),
               "mode": fix.mode}
        if fix.mode == "SIMULATED":
            reasons.append("SIMULATED_LOCATION")
        if fix.accuracy_m is None or fix.accuracy_m > limits["max_accuracy_m"]:
            reasons.append("LOW_GPS_ACCURACY")
        observed = as_utc(fix.observed_at) if fix.observed_at else None
        received = as_utc(fix.received_at)
        if observed is None or received - observed > MAX_FIX_AGE:
            reasons.append("STALE_LOCATION")
        elif observed - received > timedelta(seconds=60):
            reasons.append("FUTURE_TIMESTAMP")
        captured = as_utc(photo.captured_at) if photo is not None and photo.captured_at else None
        if observed is not None and captured is not None and \
                abs((captured - observed).total_seconds()) > settings.location_freshness_s:
            reasons.append("LOCATION_NOT_AT_PHOTO_TIME")

    exif = {"status": "NO_EXIF_GPS", "distance_m": None,
            "note": "The photo has no GPS of its own (normal for phone browsers). The phone's GPS is used."}
    for row in exif_rows:
        if row.available and row.latitude is not None and fix is not None and fix.available:
            apart = haversine_m(fix.latitude, fix.longitude, row.latitude, row.longitude)
            close = apart <= max(settings.exif_tolerance_m, fix.accuracy_m or 0)
            exif = {"status": "EXIF_MATCHES" if close else "EXIF_CONFLICT", "distance_m": round(apart, 1),
                    "note": "The photo's own GPS agrees with the phone." if close
                    else "The photo's own GPS is far from the phone's GPS."}
            if not close:
                reasons.append("PHOTO_GPS_CONFLICT")
            break
    if "PHOTO_GPS_CONFLICT" in (incident.location_flags or []) and "PHOTO_GPS_CONFLICT" not in reasons:
        reasons.append("PHOTO_GPS_CONFLICT")

    reasons = list(dict.fromkeys(reasons))
    return {
        "status": "LOCATION_VERIFIED" if not reasons else "NEEDS_REVIEW",
        "reasons": [{"code": r, "text": REASONS.get(r, r)} for r in reasons],
        "gps": gps, "exif": exif,
        "photo": {"media_id": photo.media_id, "capture_source": photo.capture_source,
                  "captured_at": iso(photo.captured_at) if photo.captured_at else None,
                  "received_at": iso(photo.received_at)} if photo else None,
        "submitted_at": iso(incident.created_at), "checked_at": iso(utcnow()),
        "limits": {"max_accuracy_m": limits["max_accuracy_m"], "photo_gps_window_s": settings.location_freshness_s,
                   "geofence_radius_m": limits["geofence_radius_m"]},
        "note": "Checked by the server. Coordinates sent by a phone are evidence, not proof; anything not verified goes to a supervisor.",
    }
