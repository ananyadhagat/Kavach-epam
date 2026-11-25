"""Write the installable app's icons to frontend/icons/ (run once; the PNGs are committed).

    python scripts/make_app_icons.py
"""

from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parent.parent / "frontend" / "icons"
NAVY, BLUE, CYAN, WHITE = (10, 22, 48), (47, 107, 255), (34, 211, 238), (255, 255, 255)


def icon(size: int, *, maskable: bool) -> Image.Image:
    scale = 4  # draw large, then downsample for smooth edges
    s = size * scale
    img = Image.new("RGB", (s, s), NAVY)
    d = ImageDraw.Draw(img)
    if not maskable:  # rounded tile; maskable icons must fill the square (the OS crops them)
        img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        d.rounded_rectangle((0, 0, s - 1, s - 1), radius=s // 5, fill=NAVY)
    # Ring (blue to cyan) with a white centre dot: GeoSatya's logo mark.
    safe = 0.62 if maskable else 0.74          # maskable keeps the mark inside the safe zone
    r = s * safe / 2
    c = s / 2
    for i in range(int(r * 0.22)):
        t = i / (r * 0.22)
        col = tuple(int(BLUE[k] + (CYAN[k] - BLUE[k]) * t) for k in range(3))
        rr = r - i
        d.ellipse((c - rr, c - rr, c + rr, c + rr), outline=col, width=2)
    dot = r * 0.32
    d.ellipse((c - dot, c - dot, c + dot, c + dot), fill=WHITE)
    return img.resize((size, size), Image.LANCZOS)


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    for name, size, maskable in (("icon-192.png", 192, False), ("icon-512.png", 512, False),
                                 ("maskable-512.png", 512, True), ("apple-touch-icon.png", 180, True)):
        icon(size, maskable=maskable).save(OUT / name)
        print("wrote", OUT / name)
