import pytest

from kavach.schemas.location import ImageMetadataStatus, ReasonCode
from kavach.services.location.coordinate_conversion import dms_to_decimal, validate_coordinates
from kavach.services.location.distance import haversine_meters
from kavach.services.location.exif_reader import read_image_metadata


# ---- DMS conversion -------------------------------------------------------------
def test_dms_north_east_positive():
    assert dms_to_decimal((23, 15, 0), "N") == pytest.approx(23.25)
    assert dms_to_decimal((77, 24, 0), "E") == pytest.approx(77.4)


def test_dms_south_west_negative():
    assert dms_to_decimal((33, 30, 0), "S") == pytest.approx(-33.5)
    assert dms_to_decimal((70, 0, 36), "W") == pytest.approx(-70.01)


def test_dms_accepts_rational_tuples_and_bytes_ref():
    assert dms_to_decimal(((23, 1), (30, 1), (0, 1)), b"N") == pytest.approx(23.5)


@pytest.mark.parametrize("dms,ref", [
    ((23, 15), "N"), ((23, 15, 0), "X"), ((23, 15, 0), None),
    ((23, 60, 0), "N"), ((23, 0, 60), "N"), ((-1, 0, 0), "N"), (((1, 0), 0, 0), "N"),
])
def test_dms_rejects_malformed(dms, ref):
    with pytest.raises(ValueError):
        dms_to_decimal(dms, ref)


@pytest.mark.parametrize("lat,lon", [(91, 0), (0, 181), (float("nan"), 0), (0, float("inf"))])
def test_validate_coordinates_rejects(lat, lon):
    with pytest.raises(ValueError):
        validate_coordinates(lat, lon)


def test_haversine_known_values():
    assert haversine_meters(0, 0, 1, 0) == pytest.approx(111_195, abs=150)
    assert haversine_meters(23.25, 77.4, 23.25, 77.4) == 0
    with pytest.raises(ValueError):
        haversine_meters(100, 0, 0, 0)


# ---- Pillow EXIF reading --------------------------------------------------------
def test_reads_gps_and_claimed_time(make_image):
    r = read_image_metadata(make_image(gps=(23.25, 77.4)), "img-1")
    assert r.status == ImageMetadataStatus.GPS_FOUND
    assert r.coordinates.latitude == pytest.approx(23.25, abs=1e-4)
    assert r.coordinates.longitude == pytest.approx(77.4, abs=1e-4)
    assert r.claimed_captured_at.year == 2026 and r.reason_codes == []


def test_southern_western_hemisphere_signs(make_image):
    r = read_image_metadata(make_image(gps=(-33.8688, -70.5)), "img-1")
    assert r.coordinates.latitude < 0 and r.coordinates.longitude < 0


def test_missing_gps_is_recorded_not_fatal(make_image):
    r = read_image_metadata(make_image(gps=None, taken=None), "img-1")
    assert r.status == ImageMetadataStatus.GPS_MISSING and r.coordinates is None
    assert ReasonCode.EXIF_GPS_MISSING in r.reason_codes and ReasonCode.EXIF_TIME_MISSING in r.reason_codes


def test_png_without_exif_is_handled(make_image):
    assert read_image_metadata(make_image(fmt="PNG"), "img-1").status == ImageMetadataStatus.GPS_MISSING


def test_invalid_hemisphere_ref_marks_invalid_gps(make_image):
    r = read_image_metadata(make_image(gps=(23.25, 77.4), bad_ref=True), "img-1")
    assert r.status == ImageMetadataStatus.INVALID_GPS and r.coordinates is None


@pytest.mark.parametrize("blob", [b"", b"not an image", b"\xff\xd8\xff\xe0garbage"])
def test_garbage_bytes_never_raise(blob):
    r = read_image_metadata(blob, "img-1")
    assert r.status == ImageMetadataStatus.UNREADABLE and ReasonCode.EXIF_UNREADABLE in r.reason_codes
