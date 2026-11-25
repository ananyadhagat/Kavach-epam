"""Private local image storage.

Files live outside any static/public folder and are only served through an
authorized API route. Storage keys are generated server-side (random hex +
fixed extension), so client filenames never reach the filesystem.
Production should swap this for private object storage with the same
save/read/delete interface.
"""

import os
import re
import secrets
from pathlib import Path

EXTENSIONS = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}
_KEY_PATTERN = re.compile(r"^[0-9a-f]{32}\.(?:jpg|png|webp)$")


class StorageError(Exception):
    pass


class LocalImageStorage:
    def __init__(self, base_dir: Path) -> None:
        self.base_dir = Path(base_dir).resolve()
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _path_for(self, key: str) -> Path:
        if not _KEY_PATTERN.fullmatch(key):
            raise StorageError("Invalid storage key")
        path = (self.base_dir / key).resolve()
        if path.parent != self.base_dir:
            raise StorageError("Storage key escapes the storage directory")
        return path

    def save(self, data: bytes, mime_type: str) -> str:
        extension = EXTENSIONS.get(mime_type)
        if extension is None:
            raise StorageError(f"Unsupported image type {mime_type}")
        key = secrets.token_hex(16) + extension
        path = self._path_for(key)
        temp = path.with_suffix(path.suffix + ".part")
        with open(temp, "xb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
        return key

    def read(self, key: str) -> bytes:
        return self._path_for(key).read_bytes()

    def delete(self, key: str) -> None:
        try:
            self._path_for(key).unlink(missing_ok=True)
        except StorageError:
            pass
