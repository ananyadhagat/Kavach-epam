"""EXIF GPS extraction with Pillow.

EXIF GPS is a claim written into the file. It may be missing (screenshots,
messaging apps, privacy settings), stale, or edited. It is extracted and
compared, never trusted on its own. Only the fields this feature needs are
returned; full EXIF is never stored or logged.
"""

from __future__ import annotations

import io
import math
from dataclasses import dataclass
from datetime import datetime
from fractions import Fraction

from PIL import ExifTags, Image, UnidentifiedImageError

from geosatya.location.coordinates import CoordinateError, validate_coordinates

# GPS IFD tag ids (EXIF 2.3).
GPS_LATITUDE_REF = 1
GPS_LATITUDE = 2
GPS_LONGITUDE_REF = 3
GPS_LONGITUDE = 4
GPS_DATESTAMP = 29
GPS_TIMESTAMP = 7
DATETIME_ORIGINAL = 0x9003


@dataclass(frozen=True)
class ExifGpsResult:
    # GPS_FOUND | NO_GPS | NO_EXIF | GPS_INVALID | UNREADABLE
    status: str
    latitude: float | None = None
    longitude: float | None = None
    # Claimed capture time as written (no timezone), and GPS UTC time if present.
    datetime_original: str | None = None
    gps_timestamp_utc: str | None = None
    detail: str = ""

    @property
    def has_gps(self) -> bool:
        return self.status == "GPS_FOUND"


def _to_float(value) -> float:
    """EXIF rationals arrive as IFDRational, (num, den) tuples or numbers."""
    if isinstance(value, tuple) and len(value) == 2:
        num, den = value
        if den == 0:
            raise ValueError("zero denominator")
        return float(Fraction(int(num), int(den)))
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("non-finite rational")
    return result


def dms_to_decimal(dms, ref: str | bytes | None) -> float:
    """(degrees, minutes, seconds) + N/S/E/W reference -> signed decimal."""
    if dms is None or len(dms) != 3:
        raise ValueError("GPS value must have degrees, minutes and seconds")
    degrees, minutes, seconds = (_to_float(part) for part in dms)
    if degrees < 0 or not 0 <= minutes < 60 or not 0 <= seconds < 60:
        raise ValueError("GPS degrees/minutes/seconds out of range")
    decimal = degrees + minutes / 60.0 + seconds / 3600.0
    if isinstance(ref, bytes):
        ref = ref.decode("ascii", "ignore")
    ref = (ref or "").strip().upper()[:1]
    if ref not in ("N", "S", "E", "W"):
        raise ValueError("GPS reference must be N, S, E or W")
    return -decimal if ref in ("S", "W") else decimal


def _datetime_original(exif) -> str | None:
    try:
        value = exif.get_ifd(ExifTags.IFD.Exif).get(DATETIME_ORIGINAL)
    except Exception:
        return None
    if isinstance(value, bytes):
        value = value.decode("ascii", "ignore")
    value = str(value or "").strip()[:19]
    try:
        datetime.strptime(value, "%Y:%m:%d %H:%M:%S")
    except ValueError:
        return None
    return value


def read_exif_gps(data: bytes) -> ExifGpsResult:
    """Extract GPS lat/lon and claimed capture time from image bytes."""
    try:
        with Image.open(io.BytesIO(data)) as image:
            exif = image.getexif()
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError):
        return ExifGpsResult("UNREADABLE", detail="Image metadata could not be read.")
    if not exif:
        return ExifGpsResult("NO_EXIF", detail="The image has no EXIF metadata.")

    original = _datetime_original(exif)
    try:
        gps = exif.get_ifd(ExifTags.IFD.GPSInfo)
    except Exception:
        gps = {}
    if not gps or GPS_LATITUDE not in gps or GPS_LONGITUDE not in gps:
        return ExifGpsResult("NO_GPS", datetime_original=original,
                             detail="EXIF present but it contains no GPS coordinates.")
    try:
        latitude = dms_to_decimal(gps.get(GPS_LATITUDE), gps.get(GPS_LATITUDE_REF))
        longitude = dms_to_decimal(gps.get(GPS_LONGITUDE), gps.get(GPS_LONGITUDE_REF))
        latitude, longitude = validate_coordinates(latitude, longitude)
    except (ValueError, TypeError, ZeroDivisionError, CoordinateError) as exc:
        return ExifGpsResult("GPS_INVALID", datetime_original=original,
                             detail=f"EXIF GPS present but malformed ({type(exc).__name__}).")

    gps_time = None
    try:
        date = gps.get(GPS_DATESTAMP)
        hms = gps.get(GPS_TIMESTAMP)
        if date and hms and len(hms) == 3:
            h, m, s = (int(_to_float(x)) for x in hms)
            gps_time = f"{str(date).replace(':', '-')}T{h:02d}:{m:02d}:{s:02d}Z"
    except Exception:
        gps_time = None

    return ExifGpsResult(
        "GPS_FOUND", round(latitude, 7), round(longitude, 7), original, gps_time,
        detail="GPS coordinates read from image metadata (unverified claim).",
    )
