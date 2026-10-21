import hashlib
from collections.abc import Callable
from uuid import uuid4

from fastapi import HTTPException, UploadFile

from app.config import settings
from app.db.database import UnitOfWork
from app.schemas.evidence import (
    EvidenceRecord,
    EvidenceType,
)
from app.schemas.worker_task import TaskStatus
from app.storage.image_storage import ImageStorage
from app.validators.image_validator import (
    InvalidImageError,
    validate_image,
)


MIME_SUFFIXES = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}

UPLOAD_STATES = {
    TaskStatus.ACCEPTED,
    TaskStatus.IN_PROGRESS,
    TaskStatus.PAUSED,
}


def safe_display_filename(filename: str | None) -> str:
    # The client filename is metadata only; storage keys are random UUIDs.
    # Strip directory components and control characters anyway.
    name = (filename or "").replace("\\", "/").rsplit("/", 1)[-1]
    name = "".join(ch for ch in name if ch.isprintable()).strip()
    name = name.lstrip(".")

    return name[:255] or "upload"


async def _require_uploadable_task(uow: UnitOfWork, task_id: str,
                                   worker_id: str, for_update: bool = False):
    task = await uow.tasks.get_for_worker(task_id, worker_id,
                                          for_update=for_update)

    if task is None:
        raise HTTPException(404, "Task not found.")

    if task.status not in UPLOAD_STATES:
        raise HTTPException(
            409,
            "Evidence cannot be uploaded in this task state.",
        )

    return task


class EvidenceService:
    def __init__(
        self,
        unit_of_work: Callable[[], UnitOfWork],
        storage: ImageStorage,
    ):
        self.unit_of_work = unit_of_work
        self.storage = storage

    async def upload(
        self,
        task_id: str,
        worker_id: str,
        evidence_type: EvidenceType,
        file: UploadFile,
    ):
        async with self.unit_of_work() as uow:
            await _require_uploadable_task(uow, task_id, worker_id)

        # Read at most one byte past the limit so oversized uploads are
        # rejected without loading the whole body into memory.
        content = await file.read(settings.max_image_size_bytes + 1)

        if len(content) > settings.max_image_size_bytes:
            raise HTTPException(413, "Image exceeds the allowed size limit.")

        try:
            validate_image(
                content,
                file.content_type or "",
                evidence_type,
            )
        except InvalidImageError as exc:
            raise HTTPException(422, str(exc)) from exc

        digest = hashlib.sha256(content).hexdigest()

        # Check for an exact duplicate before writing another file.
        async with self.unit_of_work() as uow:
            existing = await uow.evidence.find_duplicate(
                task_id, worker_id, digest, evidence_type
            )

        if existing is not None:
            return existing, True

        mime_type = file.content_type.lower()
        storage_key = await self.storage.save(content, MIME_SUFFIXES[mime_type])

        record = EvidenceRecord(
            evidence_id=str(uuid4()),
            task_id=task_id,
            worker_id=worker_id,
            evidence_type=evidence_type,
            storage_key=storage_key,
            original_filename=safe_display_filename(file.filename),
            mime_type=mime_type,
            size_bytes=len(content),
            sha256=digest,
        )

        # The file exists before the record, so a committed record never
        # points at a missing file. If the transaction fails, the file is
        # removed. A crash between these steps can leave an orphan file;
        # see "python -m app.db.check_orphans".
        try:
            async with self.unit_of_work() as uow:
                # Re-check under a row lock: the task may have changed
                # state (e.g. completion submitted) since the first check.
                await _require_uploadable_task(uow, task_id, worker_id,
                                               for_update=True)
                saved, duplicate = await uow.evidence.save_or_get_duplicate(
                    record
                )
        except BaseException:
            await self.storage.delete(storage_key)
            raise

        if duplicate:
            await self.storage.delete(storage_key)

        return saved, duplicate
