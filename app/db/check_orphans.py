"""Report evidence files that have no database record.

Usage:
    python -m app.db.check_orphans                      # report only
    python -m app.db.check_orphans --delete             # delete orphans
    python -m app.db.check_orphans --delete --min-age-minutes 120

An orphan can be left if the server crashes after writing an image file
but before committing its evidence record. Recent files are skipped
because their upload may still be in progress. Nothing is deleted unless
--delete is given.
"""

import argparse
import asyncio
import time

from app.config import get_settings
from app.db.database import Database
from app.storage.image_storage import ImageStorage


async def find_orphans(database: Database, storage: ImageStorage,
                       min_age_seconds: float) -> list[str]:
    async with database.unit_of_work() as uow:
        known = await uow.evidence.list_storage_keys()

    cutoff = time.time() - min_age_seconds

    return [
        key
        for key in storage.list_keys()
        if key not in known
        and storage.resolve(key).stat().st_mtime < cutoff
    ]


async def run(delete: bool, min_age_minutes: float) -> list[str]:
    database = await Database.connect(get_settings())

    try:
        storage = ImageStorage()
        orphans = await find_orphans(database, storage, min_age_minutes * 60)

        if delete:
            for key in orphans:
                await storage.delete(key)

        return orphans
    finally:
        await database.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--delete", action="store_true",
                        help="Delete the orphan files that are found.")
    parser.add_argument("--min-age-minutes", type=float, default=60,
                        help="Ignore files newer than this (default 60).")
    args = parser.parse_args()

    orphans = asyncio.run(run(args.delete, args.min_age_minutes))
    action = "Deleted" if args.delete else "Found"

    print(f"{action} {len(orphans)} orphan file(s).")
    for key in orphans:
        print(f"  {key}")


if __name__ == "__main__":
    main()
