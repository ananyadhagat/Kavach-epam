from io import BytesIO

from PIL import Image, UnidentifiedImageError


class EvidenceTaskMismatch(ValueError):
    pass


class InvalidStoredImage(ValueError):
    pass


def validate_image_bytes(data: bytes) -> str:
    """Decode and validate image bytes, returning a supported MIME type."""
    try:
        with Image.open(BytesIO(data)) as image:
            image.verify()
            image_format = (image.format or "").upper()
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise InvalidStoredImage("Image bytes are not a decodable supported image.") from exc
    mime_types = {"JPEG": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp"}
    mime_type = mime_types.get(image_format)
    if mime_type is None:
        raise InvalidStoredImage("Image format is unsupported; use JPEG, PNG, or WEBP.")
    return mime_type


def validate_evidence_task_ownership(task_id: str, evidence: list[dict]) -> None:
    for item in evidence:
        if item.get("task_id") != task_id:
            raise EvidenceTaskMismatch(f"Evidence {item.get('evidence_id', '<unknown>')} belongs to another task.")


def check_required_evidence(evidence: list[dict]) -> list[str]:
    ready = {item.get("type") for item in evidence if item.get("status") == "READY"}
    unavailable = [item.get("type", "UNKNOWN") for item in evidence if item.get("status") != "READY"]
    for required in ("BEFORE_IMAGE", "AFTER_IMAGE"):
        if required not in ready and required not in unavailable:
            unavailable.append(required)
    return sorted(set(unavailable))
