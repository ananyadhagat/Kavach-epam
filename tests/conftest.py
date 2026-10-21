from __future__ import annotations

import json
from io import BytesIO

import pytest
from PIL import ExifTags, Image


def _to_dms(value: float):
    value = abs(value)
    d = int(value)
    m = int((value - d) * 60)
    s = round((value - d - m / 60) * 3600, 4)
    return (float(d), float(m), float(s))


@pytest.fixture
def make_image():
    """Factory: make_image(gps=(lat, lon) | None, taken='YYYY:MM:DD HH:MM:SS' | None, fmt='JPEG', bad_ref=False)."""
    def _make(gps=None, taken="2026:10:12 07:10:00", fmt="JPEG", bad_ref=False) -> bytes:
        img = Image.new("RGB", (64, 64), "gray")
        exif = Image.Exif()
        if gps is not None:
            lat, lon = gps
            exif[ExifTags.IFD.GPSInfo] = {
                1: "X" if bad_ref else ("N" if lat >= 0 else "S"), 2: _to_dms(lat),
                3: "E" if lon >= 0 else "W", 4: _to_dms(lon),
            }
        if taken:
            sub = exif.get_ifd(ExifTags.IFD.Exif)
            sub[36867] = taken
            exif[ExifTags.IFD.Exif] = sub
        buf = BytesIO()
        img.save(buf, fmt, exif=exif) if fmt == "JPEG" else img.save(buf, fmt)
        return buf.getvalue()
    return _make


class ScriptedLLM:
    """Returns queued responses (str) or raises queued exceptions. Records call count."""
    name = "scripted-llm"

    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = 0

    def generate(self, prompt):
        self.calls += 1
        item = self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]
        if isinstance(item, Exception):
            raise item
        return item


def good_json(**overrides) -> str:
    base = {
        "incident_summary": "Overflowing dustbin near main gate.",
        "category": "SANITATION", "incident_type": "WASTE_OVERFLOW",
        "severity_recommendation": "MEDIUM", "severity_reason": "Path partly blocked.",
        "extracted_facts": [{"fact": "Dustbin overflowing", "source": "COMPLAINT_TEXT"}],
        "claimed_location_text": "main gate", "claimed_time_text": None,
        "image_observations": [], "missing_information": [], "conflicting_information": [],
        "needs_clarification": False, "clarification_questions": [],
    }
    base.update(overrides)
    return json.dumps(base)
