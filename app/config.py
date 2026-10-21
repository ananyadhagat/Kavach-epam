from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    app_name: str = "KAVACH Field Worker Execution Agent"
    app_version: str = "1.0.0"
    api_prefix: str = "/api/v1"

    # Demo authentication is refused when app_env is "production".
    app_env: Literal["development", "test", "production"] = "development"

    # Demo credentials only. Replace with JWT/OIDC in production.
    # SecretStr keeps the value out of repr() and logs.
    demo_worker_token: SecretStr = Field(
        default=SecretStr("dev-worker-token"),
        min_length=8,
    )
    demo_worker_id: str = Field(default="worker-001", min_length=1)

    # PostgreSQL is the only storage backend. There is no fallback: the
    # application refuses to start when this is missing or unreachable.
    # Format: postgresql+asyncpg://USER:PASSWORD@HOST:5432/DBNAME
    database_url: SecretStr | None = None
    # Used only by the test suite. Its database name must end in "_test".
    test_database_url: SecretStr | None = None
    database_connect_timeout_seconds: float = Field(default=5.0, gt=0)
    # Inserts the demo worker and TASK-001 if missing. Never overwrites.
    seed_demo_data: bool = False

    image_storage_dir: Path = BASE_DIR / "private_uploads"
    max_image_size_bytes: int = Field(default=5 * 1024 * 1024, gt=0)
    allowed_image_types: tuple[str, ...] = (
        "image/jpeg",
        "image/png",
        "image/webp",
    )

    max_gps_accuracy_meters: float = Field(
        default=100.0,
        gt=0,
    )

    require_arrival_location: bool = False

    model_config = SettingsConfigDict(
        # Resolve .env from the project root, not the current directory.
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
