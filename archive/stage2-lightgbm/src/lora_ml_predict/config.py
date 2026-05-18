"""Settings cho Predict-ML service (training + serving).

12-Factor III: tất cả config qua env var. Default value KHÔNG production-safe;
service refuse-to-start nếu thiếu trong production env (caller phải set).
"""

from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Env-driven config cho training pipeline + serving server.

    What: load env var, validate type + range, expose là Python field.
    Hidden: pydantic-settings parsing, .env file location, env name convention.
    """

    model_config = SettingsConfigDict(
        env_prefix="LORA_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",  # api-service settings cũng nằm trong .env, ignore.
    )

    # ── Database ─────────────────────────────────────────────────────────
    # Reuse api-service DB url (cùng instance). Training query ts.survey_training,
    # write ml.model_runs.
    db_url: str = Field(
        default="postgresql://lora_test_user:test_only_no_secrets@localhost:5432/lora_test",
        description="Postgres connection URL (psycopg format)",
    )

    # ── Feature pipeline raster paths (Phase 3) ──────────────────────────
    # `dem_path` = active DEM cho training/serving hiện tại (Đà Nẵng scope).
    # `dem_path_north_vn` = DEM Bắc Bộ (Hà Nội + HP + HD); dùng cho Stage 1
    # validation HP/HD và training future khi mở rộng scope ra Bắc Bộ.
    # Tách 2 field thay vì swap qua env: validation script có thể load đồng
    # thời cả 2 mà không cần restart service.
    dem_path: Path = Field(
        default=Path("E:/DATN/lora-data/dem/copernicus_glo30_danang.tif"),
        description="DEM GeoTIFF (Copernicus GLO-30 clip) — active region (feature pipeline)",
    )
    dem_path_north_vn: Path = Field(
        default=Path("E:/DATN/lora-data/dem/copernicus_glo30_north_vn.tif"),
        description="DEM GeoTIFF Bắc Bộ (Hải Phòng, Hải Dương, Hà Nội)",
    )
    # Stage1 ITU-R P.1812 backend cần directory chứa tile GeoTIFF, không phải
    # 1 file. crc-covlib tự auto-detect tile theo bbox của link.
    dem_directory: Path = Field(
        default=Path("E:/DATN/lora-data/dem"),
        description="Folder chứa DEM GeoTIFF tiles cho Stage 1 ITU-R P.1812 (crc-covlib).",
    )
    itu_percent_time: float = Field(
        default=50.0,
        gt=0.0,
        le=100.0,
        description="P.1812 percent_time. 50 = median (khớp api-service default).",
    )
    itu_percent_location: float = Field(
        default=50.0,
        gt=0.0,
        le=100.0,
        description="P.1812/P.2108 percent_location.",
    )
    urbanization_path: Path = Field(
        default=Path("E:/DATN/lora-data/osm/urbanization_vn.tif"),
        description="Urbanization GeoTIFF (precomputed từ OSM PBF)",
    )

    # ── Environment profile ──────────────────────────────────────────────
    env_profile: str = Field(
        default="suburban",
        description="EnvironmentProfile name (urban/suburban/rural). Khớp với api-service.",
    )

    # ── Training scope (Q6) ──────────────────────────────────────────────
    # Đà Nẵng bbox theo memory project_stage1_calibration_scope.md.
    train_bbox_min_lat: float = Field(default=15.8, description="Min lat (Đà Nẵng)")
    train_bbox_max_lat: float = Field(default=16.3, description="Max lat (Đà Nẵng)")
    train_bbox_min_lon: float = Field(default=107.9, description="Min lon (Đà Nẵng)")
    train_bbox_max_lon: float = Field(default=108.5, description="Max lon (Đà Nẵng)")

    train_val_start: str = Field(default="2025-11-01", description="train+val start (ISO date)")
    train_val_end: str = Field(default="2025-12-31", description="train+val end (inclusive)")
    test_start: str = Field(default="2026-01-01", description="test start")
    test_end: str = Field(default="2026-02-28", description="test end (inclusive)")

    # ── LightGBM training (Q7, Q8) ───────────────────────────────────────
    spatial_kfold: int = Field(default=5, ge=2, le=10, description="KMeans K (Q7=5)")
    optuna_trials: int = Field(default=100, ge=1, description="Optuna trial budget (Q8=100)")
    optuna_seed: int = Field(default=42, description="Sampler reproducibility")

    # ── Stage 2 artifact + registry (Q12) ────────────────────────────────
    stage2_artifact_dir: Path = Field(
        default=Path("archive/stage2-lightgbm/artifacts/stage2"),
        description="Local artifact dir (R2 defer)",
    )

    # ── Serving (Phase 5) ────────────────────────────────────────────────
    stage2_auth_token: str = Field(
        default="stage2-dev-please-change",
        description="Bearer token cho api-service → ml-service-predict (Q9 defer auth)",
    )
    stage2_serving_port: int = Field(default=8001, description="Internal port")


def get_settings() -> Settings:
    """Single source of Settings. Cache nếu cần performance — chưa cần Phase 4."""
    return Settings()
