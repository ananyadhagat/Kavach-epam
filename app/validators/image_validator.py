from io import BytesIO

from PIL import Image, UnidentifiedImageError

from app.config import settings
from app.schemas.evidence import EvidenceType


class InvalidImageError(ValueError):
    pass


def validate_image(
    content: bytes,
    declared_content_type: str,
    evidence_type: EvidenceType,
) -> str:
    if not content:
        raise InvalidImageError("Image file is empty.")

    if len(content) > settings.max_image_size_bytes:
        raise InvalidImageError("Image exceeds the allowed size limit.")

    allowed = {
        "image/jpeg": "JPEG",
        "image/png": "PNG",
        "image/webp": "WEBP",
    }

    expected_format = allowed.get(declared_content_type.lower())

    if expected_format is None:
        raise InvalidImageError("Unsupported MIME type.")

    try:
        with Image.open(BytesIO(content)) as image:
            actual_format = image.format

            if actual_format != expected_format:
                raise InvalidImageError(
                    "Declared MIME type does not match image content."
                )

            image.verify()

    except Image.DecompressionBombError as exc:
        raise InvalidImageError(
            "Image dimensions exceed the safe decoding limit."
        ) from exc

    except (UnidentifiedImageError, OSError, SyntaxError) as exc:
        raise InvalidImageError(
            "Uploaded file is not a valid, decodable image."
        ) from exc

    # Evidence type is deliberately checked at the service layer too.
    if evidence_type not in {EvidenceType.BEFORE, EvidenceType.AFTER}:
        raise InvalidImageError("Invalid evidence type.")

    return expected_format