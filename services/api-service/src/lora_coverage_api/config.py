"""Application config — 12-Factor F3 (env-only).

KHÔNG hardcode default cho secrets. Default chỉ cho dev convenience.
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_env: str = Field(default="development")
    log_level: str = Field(default="INFO")

    database_url: str = Field(
        default="postgresql+psycopg://lora:lora_test_pw@localhost:5432/lora_coverage",
        description="SQLAlchemy URL. Theo .env.template.",
    )

    cors_allowed_origins: str = Field(
        default="http://localhost:5173",
        description="Comma-separated; strict whitelist (xem rule-design-cors.md).",
    )

    ml_model_version: str = Field(default="stage1-loglike-v0.1.0")

    rate_limit_default: str = Field(default="60/minute")
    rate_limit_anon: str = Field(default="10/minute")

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_allowed_origins.split(",") if o.strip()]


def get_settings() -> Settings:
    return Settings()
