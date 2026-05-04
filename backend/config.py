"""
config.py — Cấu hình ứng dụng theo chuẩn 12-Factor App.

Tất cả giá trị nhạy cảm (DATABASE_URL, WEBHOOK_SECRET) được
đặt qua biến môi trường — KHÔNG hard-code trong code.

Dùng pydantic-settings để validate và auto-load từ .env file.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Database (Backing Service — Factor 4) ───────────────────────────────
    database_url: str = "postgresql+asyncpg://lora:lora@localhost:5432/lora_db"

    # ── App ─────────────────────────────────────────────────────────────────
    app_env:    Literal["development", "staging", "production"] = "development"
    app_name:   str = "LoRa Coverage API"
    api_prefix: str = "/api/v1"
    log_level:  Literal["debug", "info", "warning", "error"] = "info"

    # ── CORS (cors.pdf Rule 1: whitelist, KHÔNG dùng "*") ──────────────────
    cors_origins: list[str] = Field(
        default_factory=lambda: ["http://localhost:3000", "http://localhost:5173"],
    )
    cors_max_age: int = 86400   # 24h — giảm preflight OPTIONS

    # ── Webhook security ───────────────────────────────────────────────────
    # Shared secret giữa backend và ChirpStack để verify HMAC signature
    # của payload webhook. KHÔNG phải auth user.
    webhook_secret: str = ""

    # ── ML ──────────────────────────────────────────────────────────────────
    ml_model_dir:   str = "ml_models"
    dem_dir:        str = "../DEM"
    gp_max_samples: int = 300

    # ── Mapbox (frontend dùng; backend chỉ cần khi generate tiles) ─────────
    mapbox_public_token: str = ""

    # ── LoRaWAN defaults ────────────────────────────────────────────────────
    default_freq_mhz: float = 868.0
    default_sf:       int   = 9

    # ── External APIs ──────────────────────────────────────────────────────
    lpwan_base_url: str = "https://api.lpwanmapper.com"

    # ── MQTT ingest (ChirpStack) ───────────────────────────────────────────
    # Đường ingest realtime song song với HTTP webhook. Disable mặc định.
    # Khi enable, listener subscribe broker và gọi cùng persist logic.
    mqtt_enabled:     bool = False
    mqtt_broker_host: str  = "localhost"
    mqtt_broker_port: int  = 1883
    mqtt_username:    str  = ""
    mqtt_password:    str  = ""
    mqtt_topic:       str  = "application/+/device/+/event/up"
    mqtt_client_id:   str  = "lora-coverage-backend"
    mqtt_tls:         bool = False

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()
