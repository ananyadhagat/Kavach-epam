"""Write a few clearly-labelled synthetic photos to demo_images/ for uploading
by hand (e.g. with "Choose a photo"). Some carry EXIF GPS so the photo-GPS
checks can be shown.

    python scripts/make_demo_images.py
"""

import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from geosatya.seed import DEMO_POINT  # noqa: E402
from geosatya.synthetic_images import pothole_scene  # noqa: E402


def offset(point, north_m=0.0, east_m=0.0):
    lat, lon = point
    return (lat + north_m / 111_320.0, lon + east_m / (111_320.0 * math.cos(math.radians(lat))))


IMAGES = {
    "pothole_before.jpg": lambda: pothole_scene(1),
    "pothole_repaired.jpg": lambda: pothole_scene(1, repaired=True),
    "pothole_with_gps_near_demo_point.jpg": lambda: pothole_scene(2, gps=offset(DEMO_POINT, east_m=4)),
    "pothole_with_gps_far_away.jpg": lambda: pothole_scene(3, repaired=True, gps=offset(DEMO_POINT, north_m=1500)),
}

if __name__ == "__main__":
    out = ROOT / "demo_images"
    out.mkdir(exist_ok=True)
    for name, make in IMAGES.items():
        (out / name).write_bytes(make())
        print(f"wrote demo_images/{name}")
