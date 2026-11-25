from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings for KAVACH Module 04 — Sanitation Planning."""

    app_name: str = "KAVACH Module 04 — Sanitation Planning"
    environment: str = "development"
    log_level: str = "INFO"
    contract_version: str = "1.0.0"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()