"""Safe image validation. Checks real content (not the filename) before anything decodes it further."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from io import BytesIO

from PIL import Image

# MPO = multi-picture JPEG written by many Android/Samsung cameras; Pillow reports it as "MPO".
# It is a normal JPEG for our purposes (first frame), so it is accepted as image/jpeg.
ALLOWED_FORMATS = {"JPEG": "image/jpeg", "MPO": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp"}
MAX_PIXELS = 40_000_000


class MediaValidationError(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class ValidatedImage:
    media_id: str
    content: bytes
    mime_type: str
    width: int
    height: int
    sha256: str
    perceptual_hash: str | None = None


def difference_hash(image: Image.Image, hash_size: int = 8) -> str:
    """64-bit dHash as 16 hex chars. Deterministic, Pillow-only (no extra dependency).

    Near-identical photos (re-saved, resized, recompressed) get hashes with a small Hamming distance.
    It does NOT prove two different photos show the same real-world event.
    """
    gray = image.convert("L").resize((hash_size + 1, hash_size), Image.Resampling.LANCZOS)
    # Pillow >= 12 has get_flattened_data(); getdata() is deprecated and removed in Pillow 14.
    # Same pixel values either way, so hashes are identical across Pillow versions.
    flat = getattr(gray, "get_flattened_data", None)
    px = list(flat() if flat else gray.getdata())
    bits = 0
    for row in range(hash_size):
        for col in range(hash_size):
            left = px[row * (hash_size + 1) + col]
            right = px[row * (hash_size + 1) + col + 1]
            bits = (bits << 1) | (1 if left > right else 0)
    return f"{bits:0{hash_size * hash_size // 4}x}"


def validate_image(media_id: str, content: bytes, max_bytes: int) -> ValidatedImage:
    if not content:
        raise MediaValidationError("EMPTY_FILE")
    if len(content) > max_bytes:
        raise MediaValidationError("FILE_TOO_LARGE")
    Image.MAX_IMAGE_PIXELS = MAX_PIXELS  # decompression-bomb guard
    try:
        with Image.open(BytesIO(content)) as probe:
            fmt, (w, h) = probe.format, probe.size
            if fmt not in ALLOWED_FORMATS:
                raise MediaValidationError("UNSUPPORTED_FORMAT")
            if w * h > MAX_PIXELS:
                raise MediaValidationError("IMAGE_TOO_LARGE")
            probe.verify()
        with Image.open(BytesIO(content)) as full:  # verify() invalidates the handle; decode once fully
            full.load()
            phash = difference_hash(full)
    except MediaValidationError:
        raise
    except Exception as exc:  # noqa: BLE001 - corrupt / bomb / truncated
        raise MediaValidationError("CORRUPT_OR_UNDECODABLE") from exc
    return ValidatedImage(media_id, content, ALLOWED_FORMATS[fmt], w, h,
                          hashlib.sha256(content).hexdigest(), phash)
