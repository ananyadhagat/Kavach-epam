"""Clearly-labelled synthetic photos for tests and the demo.

Every image carries the word SYNTHETIC. They let the pipeline run without
real field photos; they are not evidence of anything.
"""

from __future__ import annotations

import io
import random

from PIL import ExifTags, Image, ImageDraw, TiffImagePlugin

SIZE = (640, 480)


def _rational(value: float) -> TiffImagePlugin.IFDRational:
    return TiffImagePlugin.IFDRational(round(value * 10000), 10000)


def _dms(decimal: float) -> tuple:
    decimal = abs(decimal)
    degrees = int(decimal)
    minutes_full = (decimal - degrees) * 60
    minutes = int(minutes_full)
    seconds = (minutes_full - minutes) * 60
    return (_rational(degrees), _rational(minutes), _rational(seconds))


def _encode(image: Image.Image, gps: tuple[float, float] | None = None,
            taken: str | None = None, fmt: str = "JPEG") -> bytes:
    buffer = io.BytesIO()
    kwargs = {"quality": 88} if fmt == "JPEG" else {}
    if gps or taken:
        exif = Image.Exif()
        if taken:
            exif.get_ifd(ExifTags.IFD.Exif)[0x9003] = taken
        if gps:
            lat, lon = gps
            gps_ifd = exif.get_ifd(ExifTags.IFD.GPSInfo)
            gps_ifd[1] = "N" if lat >= 0 else "S"
            gps_ifd[2] = _dms(lat)
            gps_ifd[3] = "E" if lon >= 0 else "W"
            gps_ifd[4] = _dms(lon)
        kwargs["exif"] = exif.tobytes()
    image.save(buffer, format=fmt, **kwargs)
    return buffer.getvalue()


def _label(draw, text, colour):
    draw.rectangle((0, 0, 640, 28), fill=(0, 0, 0))
    draw.text((10, 8), f"SYNTHETIC DEMO IMAGE - {text}", fill=colour)


def _door(draw, label):
    draw.rectangle((470, 60, 600, 420), fill=(120, 92, 64), outline=(60, 40, 20), width=4)
    if label:
        draw.rectangle((505, 100, 565, 150), fill=(250, 250, 240), outline=(30, 30, 30), width=2)
        draw.text((520, 115), label, fill=(10, 10, 10))


def dirty_scene(seed: int, label: str | None = "6", gps=None, taken=None) -> bytes:
    """Cluttered, high-texture 'BEFORE' photo (waste around a unit door)."""
    rng = random.Random(seed)
    image = Image.new("RGB", SIZE, (150, 140, 120))
    draw = ImageDraw.Draw(image)
    for _ in range(260):
        x, y, r = rng.randrange(0, 460), rng.randrange(180, 480), rng.randrange(6, 30)
        draw.ellipse((x - r, y - r, x + r, y + r),
                     fill=(rng.randrange(40, 200), rng.randrange(30, 160), rng.randrange(20, 120)))
    _door(draw, label)
    _label(draw, f"BEFORE #{seed}", (255, 255, 255))
    return _encode(image, gps, taken)


def clean_scene(seed: int, label: str | None = "6", gps=None, taken=None) -> bytes:
    """Clean, low-texture 'AFTER' photo."""
    rng = random.Random(seed)
    image = Image.new("RGB", SIZE, (225, 228, 232))
    draw = ImageDraw.Draw(image)
    for i in range(0, 640, 80):
        draw.line((i, 180, i, 480), fill=(200, 204, 210), width=2)
    for j in range(180, 480, 80):
        draw.line((0, j, 640, j), fill=(200, 204, 210), width=2)
    shade = rng.randrange(0, 20)
    draw.rectangle((0, 28, 640, 180), fill=(235 - shade, 238 - shade, 242 - shade))
    _door(draw, label)
    _label(draw, f"AFTER #{seed}", (255, 255, 255))
    return _encode(image, gps, taken)


def pothole_scene(seed: int, repaired: bool = False, gps=None, taken=None) -> bytes:
    """Road surface with (or without) a dark pothole."""
    rng = random.Random(seed)
    image = Image.new("RGB", SIZE, (92, 92, 96))
    draw = ImageDraw.Draw(image)
    for _ in range(1800):
        x, y = rng.randrange(0, 640), rng.randrange(28, 480)
        g = rng.randrange(70, 120)
        draw.point((x, y), fill=(g, g, g + 4))
    draw.rectangle((300, 28, 320, 480), fill=(230, 220, 120))
    if repaired:
        # Fresh, lighter cold-mix patch; the hole itself is gone.
        draw.rectangle((90, 220, 400, 420), fill=(128, 128, 132))
        draw.rectangle((90, 220, 400, 420), outline=(150, 150, 154), width=4)
    else:
        for i in range(6):
            draw.ellipse((120 + i * 8, 240 + i * 6, 360 - i * 8, 400 - i * 6),
                         fill=(30 + i * 6, 26 + i * 5, 22 + i * 4))
    _label(draw, f"{'REPAIRED ROAD' if repaired else 'POTHOLE'} #{seed}", (255, 255, 255))
    return _encode(image, gps, taken)


def streetlight_scene(seed: int, lit: bool, pole: str = "SL-0147", gps=None, taken=None) -> bytes:
    image = Image.new("RGB", SIZE, (20, 24, 40))
    draw = ImageDraw.Draw(image)
    draw.rectangle((300, 120, 316, 470), fill=(110, 110, 120))
    draw.rectangle((316, 120, 420, 132), fill=(110, 110, 120))
    draw.ellipse((400, 128, 440, 150), fill=(255, 236, 160) if lit else (60, 60, 70))
    if lit:
        draw.polygon([(420, 150), (340, 470), (520, 470)], fill=(70, 66, 50))
    draw.rectangle((282, 300, 334, 330), fill=(240, 240, 240))
    draw.text((288, 310), pole, fill=(0, 0, 0))
    _label(draw, f"STREETLIGHT {'ON' if lit else 'OFF'} #{seed}", (255, 255, 255))
    return _encode(image, gps, taken)


def recompressed(data: bytes, quality: int = 60, brightness: int = 6) -> bytes:
    """Same picture, different bytes: a near-duplicate, not an exact one."""
    with Image.open(io.BytesIO(data)) as image:
        image = image.convert("RGB").point(lambda v: min(255, v + brightness))
        return _encode(image)
