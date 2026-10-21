"""Where accepted original images are kept so downstream agents/reviewers can reference them.

In-memory for tests/prototype; a local directory when KAVACH_MEDIA_DIR is set. Files are named by
their SHA-256 (content-addressed), so the same photo uploaded twice is stored once.
Cloud/object storage and retention policy are a team decision - swap the class, keep the interface.
"""
from __future__ import annotations

import os
import threading
from abc import ABC, abstractmethod
from pathlib import Path

_EXT = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}


class MediaStorageError(Exception):
    pass


class MediaStore(ABC):
    @abstractmethod
    def put(self, sha256: str, mime_type: str, content: bytes) -> str:
        """Store bytes; return a storage reference string."""

    @abstractmethod
    def get(self, storage_ref: str) -> bytes | None: ...


class InMemoryMediaStore(MediaStore):
    def __init__(self) -> None:
        self._blobs: dict[str, bytes] = {}
        self._lock = threading.Lock()

    def put(self, sha256: str, mime_type: str, content: bytes) -> str:
        ref = f"memory://{sha256}{_EXT.get(mime_type, '')}"
        with self._lock:
            self._blobs[ref] = content
        return ref

    def get(self, storage_ref: str) -> bytes | None:
        return self._blobs.get(storage_ref)


class LocalDirectoryMediaStore(MediaStore):
    def __init__(self, directory: str) -> None:
        self._dir = Path(directory)
        self._dir.mkdir(parents=True, exist_ok=True)

    def put(self, sha256: str, mime_type: str, content: bytes) -> str:
        name = f"{sha256}{_EXT.get(mime_type, '')}"
        path = self._dir / name
        try:
            if not path.exists():
                tmp = path.with_suffix(path.suffix + ".tmp")
                tmp.write_bytes(content)
                os.replace(tmp, path)
        except OSError as exc:
            raise MediaStorageError("could not store media") from exc
        return f"file://{name}"

    def get(self, storage_ref: str) -> bytes | None:
        if not storage_ref.startswith("file://"):
            return None
        name = Path(storage_ref[len("file://"):]).name  # no path traversal
        path = self._dir / name
        return path.read_bytes() if path.exists() else None
