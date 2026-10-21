from io import BytesIO

import pytest
from fastapi import HTTPException
from PIL import Image
from starlette.datastructures import UploadFile

from app.schemas.evidence import EvidenceType
from app.schemas.worker_task import TaskStatus
from app.services.evidence_service import EvidenceService
from app.storage.image_storage import ImageStorage
from app.tests.conftest import force_status
from app.validators.image_validator import (
    InvalidImageError,
    validate_image,
)


def make_png() -> bytes:
    image = Image.new("RGB", (10, 10), "white")
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def test_rejects_fake_png():
    with pytest.raises(InvalidImageError):
        validate_image(
            b"this is not an image",
            "image/png",
            EvidenceType.BEFORE,
        )


def test_rejects_mime_mismatch():
    with pytest.raises(InvalidImageError):
        validate_image(
            make_png(),
            "image/jpeg",
            EvidenceType.BEFORE,
        )


def test_accepts_valid_png():
    result = validate_image(
        make_png(),
        "image/png",
        EvidenceType.BEFORE,
    )
    assert result == "PNG"


@pytest.mark.asyncio
async def test_duplicate_evidence_reuses_record(database, tmp_path,
                                                monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "image_storage_dir", tmp_path)

    # Move the seeded task into a state where uploads are allowed.
    await force_status(database, "TASK-001", TaskStatus.ACCEPTED)

    service = EvidenceService(
        database.unit_of_work,
        ImageStorage(),
    )

    first = UploadFile(
        filename="before.png",
        file=BytesIO(make_png()),
        headers={"content-type": "image/png"},
    )

    record1, duplicate1 = await service.upload(
        "TASK-001", "worker-001", EvidenceType.BEFORE, first
    )

    second = UploadFile(
        filename="retry.png",
        file=BytesIO(make_png()),
        headers={"content-type": "image/png"},
    )

    record2, duplicate2 = await service.upload(
        "TASK-001", "worker-001", EvidenceType.BEFORE, second
    )

    assert duplicate1 is False
    assert duplicate2 is True
    assert record1.evidence_id == record2.evidence_id


@pytest.mark.asyncio
async def test_upload_rejected_for_unassigned_worker(database):
    service = EvidenceService(
        database.unit_of_work,
        ImageStorage(),
    )

    upload = UploadFile(
        filename="before.png",
        file=BytesIO(make_png()),
        headers={"content-type": "image/png"},
    )

    with pytest.raises(HTTPException) as exc:
        await service.upload(
            "TASK-001",
            "another-worker",
            EvidenceType.BEFORE,
            upload,
        )

    assert exc.value.status_code == 404