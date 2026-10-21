"""Optional manual smoke test. Never run as part of pytest/CI."""
import argparse
import os
from dataclasses import replace
from pathlib import Path

from app.config import Settings
from app.services.vision_model_service import VisionConfigurationError, build_vision_adapter
from app.validators.evidence_validator import validate_image_bytes


def main() -> int:
    parser = argparse.ArgumentParser(description="Describe a before/after image pair with Gemini.")
    parser.add_argument("before_image", type=Path)
    parser.add_argument("after_image", type=Path)
    args = parser.parse_args()
    image_paths = {"BEFORE_IMAGE": args.before_image, "AFTER_IMAGE": args.after_image}

    def load_image(reference: dict) -> tuple[bytes, str]:
        image_path = image_paths[reference["type"]].resolve(strict=True)
        data = image_path.read_bytes()
        return data, validate_image_bytes(data)

    base_settings = Settings()
    settings = replace(base_settings, vision_provider="gemini", gemini_model=os.getenv("GEMINI_MODEL"))
    try:
        adapter = build_vision_adapter(settings, image_loader=load_image)
    except VisionConfigurationError as exc:
        print(f"Configuration error: {exc}")
        return 2
    references = [
        {"evidence_id": "LOCAL-BEFORE", "type": "BEFORE_IMAGE", "status": "READY", "task_id": "LOCAL"},
        {"evidence_id": "LOCAL-AFTER", "type": "AFTER_IMAGE", "status": "READY", "task_id": "LOCAL"},
    ]
    result = adapter.analyze({}, references)
    if result is None:
        print(f"UNAVAILABLE: {adapter.unavailable_reason or 'Image analysis unavailable.'}")
        if adapter.diagnostic_reason:
            print(f"Gemini diagnostic: {adapter.diagnostic_reason}")
        return 1
    print(result.model_dump_json(indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
