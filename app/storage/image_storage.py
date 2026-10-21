import asyncio
import os
from pathlib import Path
from uuid import uuid4

from app.config import settings

TEMP_PREFIX = ".tmp-"


class ImageStorage:
    def __init__(self):
        self.root = settings.image_storage_dir.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _write_atomically(self, path: Path, content: bytes) -> None:
        # Write to a temporary name, then rename. A crash mid-write leaves
        # only a ".tmp-" file, never a partial file under a real key.
        temp = self.root / f"{TEMP_PREFIX}{uuid4().hex}"

        try:
            with open(temp, "xb") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())

            os.replace(temp, path)
        except BaseException:
            temp.unlink(missing_ok=True)
            raise

    async def save(self, content: bytes, suffix: str) -> str:
        key = f"{uuid4().hex}{suffix}"
        path = self.resolve(key)

        await asyncio.to_thread(self._write_atomically, path, content)
        return key

    async def delete(self, storage_key: str) -> None:
        path = self.resolve(storage_key)

        if path.exists():
            await asyncio.to_thread(path.unlink)

    def resolve(self, storage_key: str) -> Path:
        path = (self.root / storage_key).resolve()

        if path.parent != self.root:
            raise ValueError("Invalid storage key")

        return path

    def list_keys(self) -> list[str]:
        return sorted(
            item.name for item in self.root.iterdir() if item.is_file()
        )
