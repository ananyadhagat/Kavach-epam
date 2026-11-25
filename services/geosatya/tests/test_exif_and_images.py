from fractions import Fraction

import pytest
from PIL import TiffImagePlugin

from geosatya.location.exif_gps import dms_to_decimal, read_exif_gps
from geosatya.media.image_checks import ImageValidationError, hamming, validate_image
from geosatya.media.storage import LocalImageStorage, StorageError
from geosatya.synthetic_images import clean_scene, dirty_scene, pothole_scene, recompressed

LIMITS = {"max_bytes": 8 * 1024 * 1024, "max_pixels": 50_000_000}
R = TiffImagePlugin.IFDRational


@pytest.mark.parametrize("dms,ref,expected", [
    ((23, 14, 9.24), "N", 23.235900),
    ((23, 14, 9.24), "S", -23.235900),
    ((77, 24, 4.32), "E", 77.401200),
    ((151, 12, 33.48), "W", -151.209300),
    ((R(23, 1), R(14, 1), R(924, 100)), b"N", 23.235900),
    (((23, 1), (14, 1), (924, 100)), "N", 23.235900),
])
def test_dms_conversion_handles_references_and_rationals(dms, ref, expected):
    assert dms_to_decimal(dms, ref) == pytest.approx(expected, abs=1e-6)


@pytest.mark.parametrize("dms,ref", [
    ((23, 14), "N"), ((23, 61, 0), "N"), ((23, 0, 61), "N"), ((-23, 0, 0), "N"),
    ((23, 0, 0), "X"), ((23, 0, 0), None), (((1, 0), 0, 0), "N"),
])
def test_dms_conversion_rejects_malformed(dms, ref):
    with pytest.raises((ValueError, ZeroDivisionError)):
        dms_to_decimal(dms, ref)


def test_exif_with_gps():
    r = read_exif_gps(pothole_scene(1, gps=(23.2359, 77.4012), taken="2026:10:21 09:15:00"))
    assert r.status == "GPS_FOUND"
    assert (r.latitude, r.longitude) == pytest.approx((23.2359, 77.4012), abs=1e-6)
    assert r.datetime_original == "2026:10:21 09:15:00"


def test_exif_southern_western_hemisphere():
    r = read_exif_gps(pothole_scene(1, gps=(-33.8688, -151.2093)))
    assert (r.latitude, r.longitude) == pytest.approx((-33.8688, -151.2093), abs=1e-6)


def test_exif_without_gps():
    r = read_exif_gps(clean_scene(1, taken="2026:10:21 09:15:00"))
    assert r.status == "NO_GPS" and r.latitude is None
    assert r.datetime_original == "2026:10:21 09:15:00"


def test_image_without_exif():
    assert read_exif_gps(clean_scene(1)).status == "NO_EXIF"


def test_malformed_exif_gps_is_reported_not_raised():
    from PIL import ExifTags, Image
    import io
    image = Image.new("RGB", (40, 40))
    exif = Image.Exif()
    gps = exif.get_ifd(ExifTags.IFD.GPSInfo)
    gps[1], gps[2], gps[3], gps[4] = "N", (R(95, 1), R(0, 1), R(0, 1)), "E", (R(10, 1), R(0, 1), R(0, 1))
    buf = io.BytesIO()
    image.save(buf, "JPEG", exif=exif.tobytes())
    assert read_exif_gps(buf.getvalue()).status == "GPS_INVALID"


def test_unreadable_bytes():
    assert read_exif_gps(b"not an image").status == "UNREADABLE"


def test_image_validation():
    info = validate_image(dirty_scene(1), **LIMITS)
    assert info.mime_type == "image/jpeg" and len(info.sha256) == 64
    with pytest.raises(ImageValidationError) as exc:
        validate_image(b"%PDF-1.4", **LIMITS)
    assert exc.value.code == "NOT_AN_IMAGE"
    with pytest.raises(ImageValidationError) as exc:
        validate_image(b"", **LIMITS)
    assert exc.value.code == "EMPTY_FILE"
    with pytest.raises(ImageValidationError) as exc:
        validate_image(dirty_scene(1), max_bytes=1000, max_pixels=50_000_000)
    assert exc.value.status_code == 413


def test_unsupported_image_type():
    from PIL import Image
    import io
    buf = io.BytesIO()
    Image.new("RGB", (20, 20)).save(buf, "GIF")
    with pytest.raises(ImageValidationError) as exc:
        validate_image(buf.getvalue(), **LIMITS)
    assert exc.value.code == "UNSUPPORTED_TYPE"


def test_similar_images_are_close_but_not_identical():
    a = validate_image(clean_scene(3), **LIMITS)
    b = validate_image(recompressed(clean_scene(3)), **LIMITS)
    assert a.sha256 != b.sha256 and hamming(a.dhash, b.dhash) <= 6
    assert hamming(a.dhash, validate_image(dirty_scene(3), **LIMITS).dhash) > 6


def test_storage_keys_are_server_generated(tmp_path):
    storage = LocalImageStorage(tmp_path)
    key = storage.save(b"abc", "image/png")
    assert key.endswith(".png") and storage.read(key) == b"abc"
    for bad in ("../secret.png", "..\\x.jpg", "abc.jpg", "/etc/passwd"):
        with pytest.raises(StorageError):
            storage.read(bad)
