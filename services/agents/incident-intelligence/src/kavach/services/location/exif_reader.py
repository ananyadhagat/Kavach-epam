"""Safe EXIF GPS extraction with Pillow. Extracts only what KAVACH needs; never logs raw EXIF."""
from __future__ import annotations

import logging
from datetime import datetime
from io import BytesIO

from PIL import ExifTags, Image

from kavach.schemas.location import (
    Coordinates,
    ImageMetadataResult,
    ImageMetadataStatus,
    ReasonCode,
)
from kavach.services.location.coordinate_conversion import dms_to_decimal, validate_coordinates

logger = logging.getLogger(__name__)

_GPS_LAT_REF, _GPS_LAT, _GPS_LON_REF, _GPS_LON = 1, 2, 3, 4
_EXIF_DATETIME_ORIGINAL = 36867


def _parse_exif_time(raw: object) -> datetime | None:
    if not isinstance(raw, str):
        return None
    try:
        return datetime.strptime(raw.strip(), "%Y:%m:%d %H:%M:%S")  # naive, camera-local, unverified
    except ValueError:
        return None


def read_image_metadata(image_bytes: bytes, media_id: str) -> ImageMetadataResult:
    """Never raises: malformed input yields an UNREADABLE / INVALID_GPS result."""
    try:
        with Image.open(BytesIO(image_bytes)) as image:
            exif = image.getexif()
            gps = dict(exif.get_ifd(ExifTags.IFD.GPSInfo) or {})
            captured = _parse_exif_time(exif.get_ifd(ExifTags.IFD.Exif).get(_EXIF_DATETIME_ORIGINAL))
    except Exception:  # noqa: BLE001 - any decoder/metadata failure must not crash the request
        logger.warning("exif_read_failed media_id=%s", media_id)
        return ImageMetadataResult(
            media_id=media_id, status=ImageMetadataStatus.UNREADABLE,
            reason_codes=[ReasonCode.EXIF_UNREADABLE],
        )

    time_reason = [] if captured else [ReasonCode.EXIF_TIME_MISSING]
    if not gps:
        return ImageMetadataResult(
            media_id=media_id, status=ImageMetadataStatus.GPS_MISSING,
            claimed_captured_at=captured, reason_codes=[ReasonCode.EXIF_GPS_MISSING, *time_reason],
        )
    try:
        lat = dms_to_decimal(gps[_GPS_LAT], gps[_GPS_LAT_REF])
        lon = dms_to_decimal(gps[_GPS_LON], gps[_GPS_LON_REF])
        validate_coordinates(lat, lon)
        if lat == 0.0 and lon == 0.0:  # "Null Island": cameras write 0/0 when no fix was available
            raise ValueError("zero coordinates")
    except (KeyError, ValueError, TypeError, ZeroDivisionError):
        logger.warning("exif_gps_invalid media_id=%s", media_id)
        return ImageMetadataResult(
            media_id=media_id, status=ImageMetadataStatus.INVALID_GPS,
            claimed_captured_at=captured, reason_codes=[ReasonCode.EXIF_GPS_MISSING, *time_reason],
        )
    return ImageMetadataResult(
        media_id=media_id, status=ImageMetadataStatus.GPS_FOUND,
        coordinates=Coordinates(latitude=lat, longitude=lon),
        claimed_captured_at=captured, reason_codes=time_reason,
    )
