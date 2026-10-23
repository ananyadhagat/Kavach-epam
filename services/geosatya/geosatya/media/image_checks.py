"""Image validation and hashing (Pillow only)."""

from __future__ import annotations

import hashlib
import io
from dataclasses import dataclass

from PIL import Image, UnidentifiedImageError

FORMAT_TO_MIME = {"JPEG": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp"}


class ImageValidationError(Exception):
    def __init__(self, message: str, status_code: int = 422, code: str = "INVALID_IMAGE") -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code


@dataclass(frozen=True)
class ImageInfo:
    mime_type: str
    width: int
    height: int
    size_bytes: int
    sha256: str
    dhash: str


def validate_image(data: bytes, *, max_bytes: int, max_pixels: int) -> ImageInfo:
    """Check the bytes really are a JPEG/PNG/WebP image. The declared
    Content-Type and filename are ignored; the decoder decides."""
    if not data:
        raise ImageValidationError("The file is empty.", code="EMPTY_FILE")
    if len(data) > max_bytes:
        raise ImageValidationError(
            f"Image is larger than {max_bytes // (1024 * 1024)} MB.", 413, "FILE_TOO_LARGE")
    try:
        with Image.open(io.BytesIO(data)) as probe:
            fmt = probe.format
            width, height = probe.size
            if width * height > max_pixels:
                raise ImageValidationError("Image dimensions are too large.", code="IMAGE_TOO_LARGE")
            probe.verify()
    except ImageValidationError:
        raise
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError, Image.DecompressionBombError) as exc:
        raise ImageValidationError("The file is not a valid image.", code="NOT_AN_IMAGE") from exc

    mime_type = FORMAT_TO_MIME.get(fmt or "")
    if mime_type is None:
        raise ImageValidationError("Only JPEG, PNG and WebP images are accepted.", 415, "UNSUPPORTED_TYPE")

    with Image.open(io.BytesIO(data)) as image:
        image.load()
        digest = dhash(image)
    return ImageInfo(mime_type, width, height, len(data), hashlib.sha256(data).hexdigest(), digest)


def dhash(image: Image.Image, hash_size: int = 8) -> str:
    """64-bit difference hash: similar pictures get close hashes. Two honest
    photos of the same spot also score close, so it is only a review signal."""
    gray = image.convert("L").resize((hash_size + 1, hash_size), Image.Resampling.LANCZOS)
    pixels = list(gray.getdata())
    bits = 0
    for row in range(hash_size):
        for col in range(hash_size):
            left = pixels[row * (hash_size + 1) + col]
            right = pixels[row * (hash_size + 1) + col + 1]
            bits = (bits << 1) | (1 if left > right else 0)
    return f"{bits:0{hash_size * hash_size // 4}x}"


def hamming(hash_a: str, hash_b: str) -> int:
    return bin(int(hash_a, 16) ^ int(hash_b, 16)).count("1")
