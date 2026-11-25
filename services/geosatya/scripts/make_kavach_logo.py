"""Builds KAVACH's logo assets from the supplied logo image.

Input : frontend/icons/kavach-logo-source.webp  (the supplied horizontal logo, on a near-white background)
Output: frontend/icons/
  kavach-logo.png / .webp   full horizontal logo, transparent background (nav, landing, login, loading)
  kavach-mark.png           the shield alone, transparent background (compact headers, mobile)
  icon-192.png icon-512.png maskable-512.png apple-touch-icon.png favicon.png   (PWA / browser icons)

The artwork itself is not redrawn or re-coloured: the near-white background is converted to transparency
("colour to alpha"), then the result is trimmed and scaled with proportions kept.
Run:  python scripts/make_kavach_logo.py
"""

from pathlib import Path

import numpy as np
from PIL import Image

ICONS = Path(__file__).resolve().parent.parent / "frontend" / "icons"
SRC = ICONS / "kavach-logo-source.webp"


def to_alpha(img: Image.Image) -> Image.Image:
    """Turn the (slightly off-white) background transparent, keeping anti-aliased edges."""
    a = np.asarray(img.convert("RGB"), dtype=np.float32)
    bg = np.percentile(a.reshape(-1, 3), 99.5, axis=0)            # the paper colour
    a = np.minimum(255.0, a * 255.0 / np.maximum(bg, 1.0))        # paper -> pure white
    alpha = np.clip((255.0 - a.min(axis=2)) / 255.0, 0, 1)        # darkest channel = coverage
    alpha = np.where(alpha < 0.04, 0.0, alpha)                    # remove paper noise
    safe = np.maximum(alpha, 1e-3)[..., None]
    rgb = np.clip((a - 255.0 * (1 - alpha[..., None])) / safe, 0, 255)
    out = np.dstack([rgb, alpha * 255.0]).astype(np.uint8)
    return Image.fromarray(out, "RGBA")


def trim(img: Image.Image, pad: int = 0) -> Image.Image:
    box = img.getchannel("A").point(lambda v: 255 if v > 24 else 0).getbbox()
    x0, y0, x1, y1 = box
    return img.crop((max(0, x0 - pad), max(0, y0 - pad), min(img.width, x1 + pad), min(img.height, y1 + pad)))


def on_square(mark: Image.Image, size: int, bg=(255, 255, 255, 255), fill: float = 0.78) -> Image.Image:
    canvas = Image.new("RGBA", (size, size), bg)
    scale = size * fill / max(mark.size)
    m = mark.resize((round(mark.width * scale), round(mark.height * scale)), Image.LANCZOS)
    canvas.alpha_composite(m, ((size - m.width) // 2, (size - m.height) // 2))
    return canvas


def main() -> None:
    full = to_alpha(Image.open(SRC))
    logo = trim(full, 6)
    logo.save(ICONS / "kavach-logo.png", optimize=True)
    logo.save(ICONS / "kavach-logo.webp", quality=92, method=6)

    # The shield is everything left of the thin divider line (about 36% of the logo's width).
    left = full.crop((0, 0, int(full.width * 0.36), full.height))
    mark = trim(left, 6)
    mark.save(ICONS / "kavach-mark.png", optimize=True)

    on_square(mark, 192).save(ICONS / "icon-192.png", optimize=True)
    on_square(mark, 512).save(ICONS / "icon-512.png", optimize=True)
    on_square(mark, 512, fill=0.58).save(ICONS / "maskable-512.png", optimize=True)    # safe zone for maskable icons
    on_square(mark, 180, fill=0.74).save(ICONS / "apple-touch-icon.png", optimize=True)
    on_square(mark, 64, bg=(0, 0, 0, 0), fill=0.94).save(ICONS / "favicon.png", optimize=True)
    for f in ("kavach-logo.png", "kavach-logo.webp", "kavach-mark.png", "icon-192.png", "icon-512.png", "maskable-512.png", "apple-touch-icon.png", "favicon.png"):
        im = Image.open(ICONS / f)
        print(f"{f:22} {im.size[0]}x{im.size[1]}  {(ICONS / f).stat().st_size // 1024} KB")


if __name__ == "__main__":
    main()
