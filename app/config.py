import re
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

REASON_CODE_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]*$")
DEVELOPMENT_BLOCKER_REASON_CODES = (
    "DEV_ACCESS",
    "DEV_EQUIPMENT",
    "OTHER",
)


def validate_blocker_reason_codes(codes: tuple[str, ...]) -> tuple[str, ...]:
    if not isinstance(codes, tuple) or any(
        not isinstance(code, str) for code in codes
    ):
        raise ValueError("Blocker reason codes must be a tuple of strings")

    invalid = [
        code for code in codes
        if REASON_CODE_PATTERN.fullmatch(code) is None
    ]

    if invalid:
        raise ValueError(f"Invalid blocker reason codes: {invalid}")

    if len(set(codes)) != len(codes):
        raise ValueError("Duplicate blocker reason codes")

    return codes


BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    app_name: str = "KAVACH Field Worker Execution Task"
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

    # Demo Dispatch/Supervisor credentials for resolving blockers; also
    # refused in production. Must differ from the worker token.
    demo_operator_token: SecretStr = Field(
        default=SecretStr("dev-operator-token"),
        min_length=8,
    )
    demo_operator_id: str = Field(default="operator-demo", min_length=1)

    # This list is centrally configured. Development uses the explicitly
    # non-approved examples below only when no list is provided. Production
    # requires a configured list and BLOCKER_REASON_CODES_APPROVED=true.
    blocker_reason_codes: tuple[str, ...] = ()
    blocker_reason_codes_approved: bool = False

    # PostgreSQL is the only storage backend. There is no fallback: the
    # application refuses to start when this is missing or unreachable.
    # Format: postgresql+asyncpg://USER:PASSWORD@HOST:5432/DBNAME
    database_url: SecretStr | None = None
    # Used only by the test suite. Its database name must end in "_test".
    test_database_url: SecretStr | None = None
    database_connect_timeout_seconds: float = Field(default=5.0, gt=0)
    # Inserts the demo worker and TASK-001 if missing. Never overwrites.
    seed_demo_data: bool = False

    # Destructive demo-task reset is opt-in and limited to an explicitly
    # authorized local development environment.
    kavach_demo_reset_enabled: bool = Field(
        default=False,
        validation_alias="KAVACH_DEMO_RESET_ENABLED",
    )
    kavach_demo_reset_local_only: bool = Field(
        default=False,
        validation_alias="KAVACH_DEMO_RESET_LOCAL_ONLY",
    )

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

    @field_validator("blocker_reason_codes")
    @classmethod
    def validate_reason_codes(cls, codes: tuple[str, ...]):
        return validate_blocker_reason_codes(codes)

    @model_validator(mode="after")
    def configure_development_blocker_reason_codes(self):
        if (
            self.app_env != "production"
            and "blocker_reason_codes" not in self.model_fields_set
        ):
            self.blocker_reason_codes = DEVELOPMENT_BLOCKER_REASON_CODES

        return self

    @model_validator(mode="after")
    def validate_distinct_tokens(self):
        # A shared token would let a worker unblock their own task.
        if (self.demo_worker_token.get_secret_value()
                == self.demo_operator_token.get_secret_value()):
            raise ValueError(
                "DEMO_OPERATOR_TOKEN must differ from DEMO_WORKER_TOKEN"
            )

        return self

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
