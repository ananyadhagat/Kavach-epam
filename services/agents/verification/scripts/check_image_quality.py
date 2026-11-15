"""Optional local image-quality check; never used by pytest or the API."""

import argparse
import json
from pathlib import Path

from app.config import Settings
from app.services.image_quality_service import ImageQualityService
from app.validators.evidence_validator import validate_image_bytes


def main() -> None:
    parser = argparse.ArgumentParser(description="Describe quality of one or two local images.")
    parser.add_argument("before", type=Path)
    parser.add_argument("after", type=Path, nargs="?")
    args = parser.parse_args()
    analyzer = ImageQualityService(Settings())
    records = []
    local_files = {}
    for kind, path in (("BEFORE_IMAGE", args.before), ("AFTER_IMAGE", args.after)):
        if path is None:
            continue
        evidence_id = "LOCAL-BEFORE" if kind == "BEFORE_IMAGE" else "LOCAL-AFTER"
        records.append({"evidence_id": evidence_id, "type": kind, "status": "READY", "storage_path": evidence_id})
        local_files[evidence_id] = path

    def load_local(record):
        data = local_files[record["evidence_id"]].read_bytes()
        return data, validate_image_bytes(data)

    result = analyzer.inspect_pair(records, load_local)
    print(json.dumps(result.model_dump(mode="json"), indent=2))


if __name__ == "__main__":
    main()
